"""Replaceable single-owner persistent vector backend, without a server."""

from __future__ import annotations

import importlib
import json
import shutil
import struct
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from bioagent.knowledge.store import KnowledgeError, file_hash


class VectorStore(Protocol):
    def storage_hash(self, revision: str) -> str: ...
    def create(
        self, revision: str, ids: list[str], vectors: list[list[float]], dim: int
    ) -> str: ...
    def verify(self, revision: str, expected: str) -> None: ...
    def search(self, revision: str, query: list[float], limit: int) -> list[tuple[str, float]]: ...
    def prune(self, keep: set[str]) -> None: ...
    def close(self) -> None: ...


class QdrantLocal:
    def __init__(self, path: Path, trusted: dict[str, tuple[str, int]] | None = None) -> None:
        self.path = path.resolve()
        self._guard(trusted or {})
        qdrant = importlib.import_module("qdrant_client")
        self.models: Any = importlib.import_module("qdrant_client.models")
        try:
            self.client: Any = qdrant.QdrantClient(
                path=str(path), force_disable_check_same_thread=True
            )
        except RuntimeError as error:
            raise KnowledgeError("INDEX_OWNER_CONFLICT") from error

    @staticmethod
    def _name(revision: str) -> str:
        return "revision_" + revision.replace("-", "")

    def storage_hash(self, revision: str) -> str:
        path = self.path / "collection" / self._name(revision) / "storage.sqlite"
        if not path.resolve().is_relative_to(self.path) or any(
            part.is_symlink() for part in (path, *path.parents) if part != self.path.parent
        ):
            raise KnowledgeError("INDEX_INTEGRITY_FAILED")
        return file_hash(path)

    def _guard(self, trusted: dict[str, tuple[str, int]]) -> None:
        # qdrant-client stores pickles in SQLite. Validate bytes BEFORE loading.
        # Synthesize metadata solely from authoritative complete manifests.
        self.path.mkdir(parents=True, exist_ok=True)
        collections = {}
        for revision, (expected, dimension) in trusted.items():
            try:
                if self.storage_hash(revision) != expected:
                    raise KnowledgeError("INDEX_INTEGRITY_FAILED")
            except OSError as error:
                raise KnowledgeError("INDEX_INTEGRITY_FAILED") from error
            collections[self._name(revision)] = {"vectors": {"size": dimension, "distance": "Dot"}}
        metadata, temporary = self.path / "meta.json", self.path / "meta.json.tmp"
        if metadata.is_symlink() or temporary.is_symlink():
            raise KnowledgeError("INDEX_INTEGRITY_FAILED")
        temporary.write_text(
            json.dumps({"collections": collections, "aliases": {}}), encoding="utf-8"
        )
        temporary.replace(metadata)
        root = self.path / "collection"
        if root.is_symlink():
            raise KnowledgeError("INDEX_INTEGRITY_FAILED")
        if root.is_dir():
            for folder in root.iterdir():
                if folder.name in collections:
                    continue
                if folder.is_symlink() or not folder.resolve().is_relative_to(self.path):
                    raise KnowledgeError("INDEX_INTEGRITY_FAILED")
                if folder.is_dir():
                    shutil.rmtree(folder)

    def create(self, revision: str, ids: list[str], vectors: list[list[float]], dim: int) -> str:
        name = self._name(revision)
        if not vectors or len(ids) != len(vectors):
            raise KnowledgeError("INDEX_EMPTY")
        self.client.create_collection(
            name,
            vectors_config=self.models.VectorParams(size=dim, distance=self.models.Distance.DOT),
        )
        for start in range(0, len(ids), 64):
            self.client.upsert(
                name,
                wait=True,
                points=[
                    self.models.PointStruct(
                        id=key,
                        vector=[struct.unpack("f", struct.pack("f", value))[0] for value in vector],
                    )
                    for key, vector in zip(
                        ids[start : start + 64], vectors[start : start + 64], strict=True
                    )
                ],
            )
        return self._digest(revision)

    def _digest(self, revision: str) -> str:
        name = self._name(revision)
        points: list[tuple[str, Any]] = []
        offset = None
        while True:
            batch, offset = self.client.scroll(
                name, limit=256, offset=offset, with_vectors=True, with_payload=False
            )
            points.extend((str(point.id), point.vector) for point in batch)
            if offset is None:
                break
        # Record the actual float32 values persisted by Qdrant.
        data = {
            "config": self.client.get_collection(name).config.params.vectors.model_dump(
                mode="json"
            ),
            "points": sorted(points),
        }
        return sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()

    def verify(self, revision: str, expected: str) -> None:
        try:
            if self._digest(revision) != expected:
                raise ValueError
        except Exception as error:
            raise KnowledgeError("INDEX_INTEGRITY_FAILED") from error

    def search(self, revision: str, query: list[float], limit: int) -> list[tuple[str, float]]:
        points = self.client.query_points(
            self._name(revision), query=query, limit=limit, with_payload=False
        ).points
        return [(str(point.id), float(point.score)) for point in points]

    def prune(self, keep: set[str]) -> None:
        names = {self._name(revision) for revision in keep}
        for collection in self.client.get_collections().collections:
            if collection.name not in names:
                self.client.delete_collection(collection.name)

    def close(self) -> None:
        self.client.close()
