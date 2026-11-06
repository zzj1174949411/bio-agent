"""Serial local indexing, scoped hybrid retrieval and live evidence validation."""

from __future__ import annotations

import json
import math
import re
import shutil
import time
from collections import Counter
from contextlib import suppress
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any
from uuid import UUID

from bioagent.knowledge.chunks import ALGORITHM, LEGACY, chunks, digest_chunk, validate_sources
from bioagent.knowledge.embedding import IDENTITY, Embedding, LocalE5, readiness
from bioagent.knowledge.index_catalog import IndexCatalog
from bioagent.knowledge.models import ParsedDocument
from bioagent.knowledge.owner import ProcessLease
from bioagent.knowledge.retrieval_models import (
    Chunk,
    IndexJob,
    LocalEvidence,
    RetrievalInfo,
    RetrievalReadiness,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from bioagent.knowledge.store import KnowledgeError, KnowledgeStore, file_hash
from bioagent.knowledge.vector import QdrantLocal, VectorStore


def _tokens(text: str) -> list[str]:
    # English word matching and Han bigrams; cross-language matching is E5's job.
    words = re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", text.casefold())
    return [
        token
        for word in words
        for token in (
            [word[i : i + 2] for i in range(len(word) - 1)]
            if len(word) > 1 and "\u3400" <= word[0] <= "\u9fff"
            else [word]
        )
    ]


def _bm25(query: str, items: list[tuple[str, str]]) -> list[tuple[str, float]]:
    counts = [(key, Counter(_tokens(text))) for key, text in items]
    average = sum(sum(count.values()) for _, count in counts) / max(1, len(counts))
    terms = set(_tokens(query))
    frequencies = {term: sum(term in count for _, count in counts) for term in terms}
    result = []
    for key, count in counts:
        length = sum(count.values())
        score = sum(
            math.log(1 + (len(counts) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
            * (count[term] * 2.2)
            / (count[term] + 1.2 * (0.25 + 0.75 * length / max(average, 1)))
            for term in terms
            if count[term]
        )
        if score > 0:
            result.append((key, score))
    return sorted(result, key=lambda item: (-item[1], item[0]))


class RetrievalEngine:
    def __init__(
        self,
        store: KnowledgeStore,
        models: Path,
        *,
        embedding: Embedding | None = None,
        vectors: VectorStore | None = None,
    ) -> None:
        self.store, self.models = store, models.resolve()
        self.catalog = IndexCatalog(store)
        self._embedding, self._vectors = embedding, vectors
        self._lock = RLock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._lease: ProcessLease | None = None

    def _own(self) -> None:
        if self._lease is None:
            self._lease = ProcessLease(self.store._path("index-owner.lock"))

    @property
    def identity(self) -> str:
        return self._embedding.identity if self._embedding else IDENTITY

    @property
    def dimension(self) -> int:
        return self._embedding.dimension if self._embedding else 384

    def readiness(self) -> RetrievalReadiness:
        return readiness(self.models)

    def _runtime(self) -> tuple[Embedding, VectorStore]:
        # Held by the process engine lock; one lazily constructed client for all collections.
        self._own()
        if self._embedding is None:
            self._embedding = LocalE5(self.models)
        if self._vectors is None:
            trusted = {}
            for row in self.catalog.active():
                path = self.catalog.manifest_path(row["id"])
                self.store._verify(path, row["manifest_sha256"])
                manifest = json.loads(path.read_bytes())
                trusted[row["id"]] = (manifest["storage_sha256"], row["dimension"])
            self._vectors = QdrantLocal(self.store._path("vectors"), trusted)
            self._prune()
        return self._embedding, self._vectors

    def _prune(self) -> None:
        keep = {row["id"] for row in self.catalog.active()}
        if self._vectors is not None:
            self._vectors.prune(keep)
        root = self.store._path("indexes")
        if root.is_dir():
            for folder in root.iterdir():
                if folder.name not in keep and folder.is_dir() and not folder.is_symlink():
                    with suppress(OSError):
                        shutil.rmtree(folder)

    def start(self) -> None:
        self._own()
        self.catalog.recover()
        self._thread = Thread(target=self._loop, name="literature-index", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=60)
            if self._thread.is_alive():
                raise RuntimeError("index worker did not stop")
        with self._lock:
            if self._vectors is not None:
                self._vectors.close()
                self._vectors = None
            if self._lease is not None:
                self._lease.close()
                self._lease = None

    def enqueue(self, document_id: str) -> IndexJob:
        self._own()
        if self._embedding is None:
            ready = self.readiness()
            if not ready.ready:
                raise KnowledgeError(ready.code)
        return self.catalog.enqueue(document_id, self.identity, self.dimension)

    def build(self, document_id: str) -> IndexJob:
        job = self.enqueue(document_id)
        self.run_one()
        return self.catalog.job(str(job.id))

    def _loop(self) -> None:
        last_cleanup = 0.0
        while not self._stop.is_set():
            if not self.run_one():
                if time.monotonic() - last_cleanup > 2:
                    with self._lock:
                        self._prune()
                    last_cleanup = time.monotonic()
                self._stop.wait(0.1)

    def run_one(self) -> bool:
        with self._lock:
            job = self.catalog.claim()
            if job is None:
                return False
            try:
                self._build(job)
            except KnowledgeError as error:
                self.catalog.fail(str(job.id), error.code)
            except Exception:
                # No document text, local paths, credentials or provider errors in diagnostics.
                self.catalog.fail(str(job.id), "INDEX_BUILD_FAILED")
            finally:
                self._prune()
            return True

    def _check_job(self, job: IndexJob) -> None:
        current = self.catalog.job(str(job.id))
        doc = self.store.document(str(job.document_id))
        if self._stop.is_set() or current.status != "INDEXING":
            raise KnowledgeError("INDEX_CANCELLED")
        if doc["published_revision"] != str(job.parse_revision) or (
            doc["current_revision"] != str(job.parse_revision)
        ):
            raise KnowledgeError("INDEX_CONFLICT")

    def _build(self, job: IndexJob) -> None:
        self._check_job(job)
        if job.chunking_algorithm != ALGORITHM:
            raise KnowledgeError("INDEX_ALGORITHM_REBUILD_REQUIRED")
        parsed = self.store.parsed(str(job.document_id), str(job.parse_revision))
        document = ParsedDocument.model_validate(
            {key: value for key, value in parsed.items() if key in ParsedDocument.model_fields}
        )
        embed, vectors = self._runtime()
        fragments = chunks(document, count_tokens=getattr(embed, "count_tokens", None))
        if not fragments:
            raise KnowledgeError("INDEX_EMPTY")
        if job.model_identity != embed.identity or job.dimension != embed.dimension:
            raise KnowledgeError("INDEX_MODEL_MISMATCH")
        encoded = []
        for start in range(0, len(fragments), 8):
            self._check_job(job)
            batch = fragments[start : start + 8]
            encoded.extend(
                embed.encode(
                    ["\n".join([*chunk.section, chunk.text, chunk.context]) for chunk in batch]
                )
            )
        if len(encoded) != len(fragments) or any(
            len(vector) != embed.dimension
            or not all(math.isfinite(v) for v in vector)
            or sum(v * v for v in vector) == 0
            for vector in encoded
        ):
            raise KnowledgeError("INDEX_VECTOR_INVALID")
        self._check_job(job)
        vector_hash = vectors.create(
            str(job.index_revision),
            [str(chunk.id) for chunk in fragments],
            encoded,
            embed.dimension,
        )
        manifest = {
            "schema_version": "local-index.v1",
            "chunking_algorithm": ALGORITHM,
            "job": job.model_dump(mode="json"),
            "provenance": {
                key: value
                for key, value in parsed.items()
                if key not in {"elements", "page_text_cells"}
            },
            "chunks": [chunk.model_dump(mode="json") for chunk in fragments],
            "vector_sha256": vector_hash,
            "storage_sha256": vectors.storage_hash(str(job.index_revision)),
        }
        path = self.catalog.manifest_path(str(job.index_revision))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(manifest, sort_keys=True, ensure_ascii=False), encoding="utf-8"
        )
        temporary.replace(path)
        vectors.verify(str(job.index_revision), vector_hash)
        self._check_job(job)
        if not self.catalog.publish(str(job.id), file_hash(path)):
            raise KnowledgeError("INDEX_CONFLICT")

    def _manifest(self, row: dict[str, Any], *, verify_vectors: bool = True) -> dict[str, Any]:
        if row["model_identity"] != self.identity or row["dimension"] != self.dimension:
            raise KnowledgeError("INDEX_MODEL_MISMATCH")
        path = self.catalog.manifest_path(row["id"])
        try:
            self.store._verify(path, row["manifest_sha256"])
            manifest: dict[str, Any] = json.loads(path.read_bytes())
            parsed = self.store.parsed(row["document_id"], row["parse_revision"])
            if manifest["provenance"]["parsed_sha256"] != parsed["parsed_sha256"]:
                raise KnowledgeError("INDEX_INTEGRITY_FAILED")
            algorithm = manifest.get("chunking_algorithm", LEGACY)
            if algorithm not in {LEGACY, ALGORITHM}:
                raise KnowledgeError("INDEX_ALGORITHM_UNSUPPORTED")
            document = (
                ParsedDocument.model_validate(
                    {
                        key: value
                        for key, value in parsed.items()
                        if key in ParsedDocument.model_fields
                    }
                )
                if algorithm != LEGACY
                else None
            )
            for data in manifest["chunks"]:
                chunk = Chunk.model_validate(data)
                if (
                    digest_chunk(chunk) != chunk.content_sha256
                    or chunk.chunking_algorithm != algorithm
                    or (
                        algorithm == LEGACY
                        and (chunk.sources or chunk.token_count is not None or chunk.token_overflow)
                    )
                ):
                    raise KnowledgeError("INDEX_INTEGRITY_FAILED")
                if document is not None:
                    validate_sources(chunk, document)
            storage = self.store._path(
                "vectors", "collection", "revision_" + row["id"].replace("-", ""), "storage.sqlite"
            )
            self.store._verify(storage, manifest["storage_sha256"])
            if verify_vectors:
                _, vectors = self._runtime()
                vectors.verify(row["id"], manifest["vector_sha256"])
            return manifest
        except (OSError, ValueError) as error:
            if isinstance(error, KnowledgeError) and error.code != "RESOURCE_INTEGRITY_FAILED":
                raise
            raise KnowledgeError("INDEX_INTEGRITY_FAILED") from error

    def snapshot(self, base_ids: list[str]) -> tuple[UUID, ...]:
        """Capture only currently published READY versions, without loading a model."""
        for base in base_ids:
            self.store.base(base)
        with self._lock:
            rows = self.catalog.active(base_ids)
            for row in rows:
                self._manifest(row, verify_vectors=False)
            return tuple(UUID(row["id"]) for row in rows)

    def check_snapshot(self, base_ids: list[str], fixed: tuple[UUID, ...]) -> None:
        try:
            for base in base_ids:
                self.store.base(base)
            active = {UUID(row["id"]) for row in self.catalog.active(base_ids)}
            if not set(fixed) <= active:
                raise KnowledgeError("EVIDENCE_STALE")
        except KnowledgeError as error:
            raise KnowledgeError("EVIDENCE_STALE") from error

    def search(
        self,
        query: str,
        base_ids: list[str],
        top_k: int = 6,
        *,
        fixed: tuple[UUID, ...] | None = None,
    ) -> SearchResponse:
        request = SearchRequest(
            query=query, knowledge_base_ids=tuple(UUID(key) for key in base_ids), top_k=top_k
        )
        bases = list(dict.fromkeys(str(key) for key in request.knowledge_base_ids))
        for base in bases:
            self.store.base(base)
        with self._lock:
            rows = self.catalog.active(bases)
            if fixed is not None:
                self.check_snapshot(bases, fixed)
                rows = [row for row in rows if UUID(row["id"]) in fixed]
            information = RetrievalInfo(
                method="bm25+dense-rrf60",
                model_identity=self.identity,
                dimension=self.dimension,
                index_revisions=tuple(UUID(row["id"]) for row in rows),
                scope=tuple(UUID(base) for base in bases),
            )
            if not rows:
                return SearchResponse(code="NO_EVIDENCE", retrieval=information)
            embed, vectors = self._runtime()
            manifests = [(row, self._manifest(row)) for row in rows]
            information = information.model_copy(
                update={
                    "chunking_algorithms": tuple(
                        dict.fromkeys(m.get("chunking_algorithm", LEGACY) for _, m in manifests)
                    )
                }
            )
            query_vector = embed.encode([request.query], query=True)[0]
            all_chunks = {}
            dense = []
            for row, manifest in manifests:
                for data in manifest["chunks"]:
                    chunk = Chunk.model_validate(data)
                    all_chunks[str(chunk.id)] = (row, chunk)
                dense.extend(vectors.search(row["id"], query_vector, min(100, top_k * 5)))
            dense = sorted(dense, key=lambda item: (-item[1], item[0]))[:100]
            keywords = _bm25(
                request.query,
                [
                    (key, "\n".join([*chunk.section, chunk.text, chunk.context]))
                    for key, (_, chunk) in all_chunks.items()
                ],
            )[:100]
            scores: dict[str, float] = {}
            for ranking in [dense, keywords]:
                for rank, (key, _) in enumerate(ranking, 1):
                    scores[key] = scores.get(key, 0) + 1 / (60 + rank)
            result = []
            for key in sorted(scores, key=lambda key: (-scores[key], key))[:top_k]:
                row, chunk = all_chunks[key]
                ref = LocalEvidence(
                    base_id=row["base_id"],
                    document_id=row["document_id"],
                    parse_revision=row["parse_revision"],
                    index_revision=row["id"],
                    chunk_id=chunk.id,
                    element_id=chunk.element_id,
                    page=chunk.locations[0].page,
                    content_sha256=chunk.content_sha256,
                )
                prefix = f"/api/v1/knowledge/documents/{ref.document_id}"
                asset = (
                    f"{prefix}/revisions/{ref.parse_revision}/assets/{chunk.asset_id}"
                    if chunk.asset_id
                    else None
                )
                result.append(
                    SearchHit(
                        reference=ref,
                        chunk=chunk,
                        score=scores[key],
                        dense_score=dict(dense).get(key),
                        keyword_score=dict(keywords).get(key),
                        pdf_url=f"{prefix}/pdf#page={ref.page}",
                        asset_url=asset,
                    )
                )
            # Linearize final visibility against deletion/rebuild; revalidate returned evidence.
            with self.store._db():
                for hit in result:
                    self.validate(hit.reference)
            return SearchResponse(
                code="OK" if result else "NO_EVIDENCE", items=tuple(result), retrieval=information
            )

    def validate(self, ref: LocalEvidence, actual: tuple[SearchHit, ...] | None = None) -> Chunk:
        if actual is not None and not any(hit.reference == ref for hit in actual):
            raise KnowledgeError("EVIDENCE_INVALID")
        with self._lock:
            rows = [
                row
                for row in self.catalog.active([str(ref.base_id)])
                if row["document_id"] == str(ref.document_id)
                and row["id"] == str(ref.index_revision)
                and row["parse_revision"] == str(ref.parse_revision)
            ]
            if not rows:
                raise KnowledgeError("EVIDENCE_STALE")
            # Source/citation verification needs no embedding inference or optional imports.
            manifest = self._manifest(rows[0], verify_vectors=False)
            for data in manifest["chunks"]:
                chunk = Chunk.model_validate(data)
                if (
                    chunk.id == ref.chunk_id
                    and chunk.content_sha256 == ref.content_sha256
                    and (chunk.element_id == ref.element_id and chunk.locations[0].page == ref.page)
                ):
                    return chunk
            raise KnowledgeError("EVIDENCE_INVALID")
