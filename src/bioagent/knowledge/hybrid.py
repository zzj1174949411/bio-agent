"""Current Wiki navigation and original evidence with separate, auditable budgets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from bioagent.knowledge.chunks import source_map
from bioagent.knowledge.retrieval import RetrievalEngine, _bm25
from bioagent.knowledge.retrieval_models import (
    ContextAudit,
    KnowledgeMode,
    RetrievalInfo,
    SearchHit,
    SearchResponse,
    WikiNavigation,
    WikiSnapshot,
)
from bioagent.knowledge.store import KnowledgeError
from bioagent.knowledge.wiki import WikiService
from bioagent.knowledge.wiki_models import Statement, WikiPage


def evidence(hit: SearchHit) -> dict[str, Any]:
    item = {
        "chunk_id": str(hit.chunk.id),
        "text": hit.chunk.text,
        "context": hit.chunk.context,
        "section": hit.chunk.section,
        "page": hit.reference.page,
        "kind": hit.chunk.kind,
        "visual_semantics": "not_performed",
    }
    if hit.chunk.sources:
        item["sources"] = source_map(hit.chunk)
        item["navigation_anchor_only"] = True
        item["token_overflow"] = hit.chunk.token_overflow
    return item


def context_payload(
    hits: tuple[SearchHit, ...], navigation: tuple[WikiNavigation, ...]
) -> dict[str, Any]:
    payload: dict[str, Any] = {"evidence": [evidence(hit) for hit in hits]}
    if navigation:
        payload["wiki_navigation"] = [item.model_dump(mode="json") for item in navigation]
    return payload


def _bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


@dataclass(frozen=True)
class HybridResult:
    page: SearchResponse
    navigation: tuple[WikiNavigation, ...]
    actual_mode: KnowledgeMode
    fallback_reason: str | None
    audit: ContextAudit


class HybridRetriever:
    def __init__(self, engine: RetrievalEngine, wiki: WikiService) -> None:
        self.engine, self.wiki = engine, wiki

    def snapshot(self, bases: list[str] | tuple[UUID, ...]) -> tuple[WikiSnapshot, ...]:
        result = []
        with self.engine._lock, self.engine.store._db():
            for base in dict.fromkeys(str(key) for key in bases):
                pages = self.wiki.pages(base)
                result.append(
                    WikiSnapshot(
                        base_id=UUID(base),
                        generation=pages.generation,
                        page_ids=tuple(p.id for p in pages.items if p.status == "CURRENT"),
                    )
                )
        return tuple(result)

    def check(
        self, frozen: tuple[WikiSnapshot, ...], navigation: tuple[WikiNavigation, ...]
    ) -> None:
        for item in navigation:
            fixed = next((s for s in frozen if s.base_id == item.base_id), None)
            if (
                fixed is None
                or fixed.generation != item.generation
                or item.page_id not in fixed.page_ids
            ):
                raise KnowledgeError("EVIDENCE_STALE")
            current = self.wiki.pages(str(item.base_id))
            if current.generation != item.generation:
                raise KnowledgeError("EVIDENCE_STALE")
            page = self.wiki.page(str(item.base_id), str(item.page_id))
            if page.generation != item.generation:
                raise KnowledgeError("EVIDENCE_STALE")

    def _pages(
        self, bases: list[str], frozen: tuple[WikiSnapshot, ...], fixed: tuple[UUID, ...]
    ) -> list[WikiPage]:
        if {str(s.base_id) for s in frozen} != set(bases) or len(frozen) != len(set(bases)):
            raise KnowledgeError("WIKI_SNAPSHOT_MISMATCH")
        pages = []
        for snapshot in frozen:
            current = self.wiki.pages(str(snapshot.base_id))
            if snapshot.generation is None:
                continue  # A later build cannot expand an already submitted turn.
            if current.generation != snapshot.generation:
                raise KnowledgeError("EVIDENCE_STALE")
            if not set(snapshot.page_ids) <= {p.id for p in current.items if p.status == "CURRENT"}:
                raise KnowledgeError("EVIDENCE_STALE")
            for page in current.items:
                if page.id not in snapshot.page_ids or page.status != "CURRENT":
                    continue
                if all(
                    c.reference.base_id == page.base_id and c.reference.index_revision in fixed
                    for s in page.statements
                    for c in s.citations
                ):
                    pages.append(page)
        return pages

    def _rank(self, query: str, pages: list[WikiPage], top_k: int) -> list[WikiPage]:
        if not pages:
            return []
        texts = [
            (
                str(p.id),
                p.title + "\n" + "\n".join(s.text + " " + s.conditions for s in p.statements),
            )
            for p in pages
        ]
        keywords = _bm25(query, texts)
        # Reuse the offline E5 runtime, no additional model/API or vector collection.
        embed, _ = self.engine._runtime()
        vectors = embed.encode([text[:4000] for _, text in texts])
        q = embed.encode([query], query=True)[0]
        dense = sorted(
            (
                (key, sum(a * b for a, b in zip(vector, q, strict=True)))
                for (key, _), vector in zip(texts, vectors, strict=True)
            ),
            key=lambda x: (-x[1], x[0]),
        )
        scores: dict[str, float] = {}
        for ranking in (keywords, dense):
            for rank, (key, _) in enumerate(ranking, 1):
                scores[key] = scores.get(key, 0) + 1 / (60 + rank)
        by_id = {str(p.id): p for p in pages}
        return [by_id[key] for key in sorted(scores, key=lambda k: (-scores[k], k))[:top_k]]

    def _linked(
        self, pages: list[WikiPage], all_pages: list[WikiPage], top_k: int
    ) -> tuple[SearchHit, ...]:
        linked = list(pages)
        for page in pages:
            linked.extend(p for p in all_pages if p.base_id == page.base_id and p.key in page.links)
        hits: dict[UUID, SearchHit] = {}
        for page in linked:
            for statement in page.statements:
                for citation in statement.citations:
                    ref = citation.reference
                    if ref.base_id != page.base_id:
                        raise KnowledgeError("WIKI_CITATION_INVALID")
                    chunk = self.wiki._validate_citation(citation)
                    prefix = f"/api/v1/knowledge/documents/{ref.document_id}"
                    hits.setdefault(
                        chunk.id,
                        SearchHit(
                            reference=ref,
                            chunk=chunk,
                            score=0,
                            pdf_url=f"{prefix}/pdf#page={ref.page}",
                            asset_url=f"{prefix}/revisions/{ref.parse_revision}/assets/{chunk.asset_id}"
                            if chunk.asset_id
                            else None,
                        ),
                    )
        return tuple(hits.values())[:top_k]

    def retrieve(
        self,
        query: str,
        bases: list[str],
        mode: KnowledgeMode,
        fixed: tuple[UUID, ...],
        frozen: tuple[WikiSnapshot, ...],
        context_max_bytes: int,
        *,
        strict: bool = False,
        top_k: int = 6,
    ) -> HybridResult:
        bases = list(dict.fromkeys(bases))
        self.engine.check_snapshot(bases, fixed)
        empty = SearchResponse(
            code="NO_EVIDENCE",
            retrieval=RetrievalInfo(
                method="bm25+dense-rrf60",
                model_identity=self.engine.identity,
                dimension=self.engine.dimension,
                index_revisions=fixed,
                scope=tuple(UUID(b) for b in bases),
            ),
        )
        candidates = self._pages(bases, frozen, fixed) if mode != "rag" else []
        original = self.engine.search(query, bases, top_k, fixed=fixed) if mode != "wiki" else empty
        ranked = self._rank(query, candidates, top_k) if candidates else []
        actual: KnowledgeMode = mode
        fallback = None
        if mode != "rag" and not ranked:
            if strict or mode == "wiki":
                raise KnowledgeError("WIKI_NO_MATCH")
            actual, fallback = "rag", "WIKI_NO_MATCH"
        linked = self._linked(ranked, candidates, top_k) if ranked else ()
        navigation: tuple[WikiNavigation, ...] = ()
        # Navigation cannot consume the budget reserved for complete original chunks.
        reserved: tuple[SearchHit, ...] = ()
        for hit in original.items:
            if _bytes(context_payload((*reserved, hit), ())) <= context_max_bytes:
                reserved = (*reserved, hit)
        wiki_limit = min(
            context_max_bytes // 4,
            max(0, context_max_bytes - _bytes(context_payload(reserved, ())) - 32),
        )
        for page in ranked:
            chosen: list[Statement] = []
            item = None
            for statement in page.statements:
                statements = [*chosen, statement]
                candidate = WikiNavigation(
                    base_id=page.base_id,
                    generation=page.generation,
                    page_id=page.id,
                    title=page.title,
                    statements=tuple(s.text + " Conditions: " + s.conditions for s in statements),
                    source_chunk_ids=tuple(
                        dict.fromkeys(c.chunk_id for s in statements for c in s.citations)
                    ),
                )
                if (
                    _bytes([n.model_dump(mode="json") for n in (*navigation, candidate)])
                    <= wiki_limit
                ):
                    chosen, item = statements, candidate
            if item is not None:
                navigation = (*navigation, item)
        if mode != "rag" and ranked and not navigation:
            if strict or mode == "wiki":
                raise KnowledgeError("WIKI_CONTEXT_LIMIT")
            actual, fallback, linked = "rag", "WIKI_CONTEXT_LIMIT", ()
        # Keep the original ranking, then supplement with distinct Wiki sources.
        # top_k limits retrieval candidates, not the union's final evidence count.
        ordered: dict[UUID, SearchHit] = {}
        for hit in (*original.items, *linked):
            ordered.setdefault(hit.chunk.id, hit)
        kept: tuple[SearchHit, ...] = ()
        for hit in ordered.values():
            selected_hits = (*kept, hit)
            if _bytes(context_payload(selected_hits, navigation)) <= context_max_bytes:
                kept = selected_hits
        if strict and ordered and not kept:
            raise KnowledgeError("EVALUATION_CONTEXT_LIMIT")
        # Only advertise navigation backed by an original excerpt actually supplied to the model.
        sent = {h.chunk.id for h in kept}
        backed = []
        for nav in navigation:
            page = next(p for p in ranked if p.id == nav.page_id)
            statements = [
                s
                for s in page.statements
                if s.text + " Conditions: " + s.conditions in nav.statements
                and all(c.chunk_id in sent for c in s.citations)
            ]
            if statements:
                backed.append(
                    nav.model_copy(
                        update={
                            "statements": tuple(
                                s.text + " Conditions: " + s.conditions for s in statements
                            ),
                            "source_chunk_ids": tuple(
                                dict.fromkeys(c.chunk_id for s in statements for c in s.citations)
                            ),
                        }
                    )
                )
        navigation = tuple(backed)
        if not navigation and actual != "rag":
            if strict or mode == "wiki":
                raise KnowledgeError("WIKI_CONTEXT_LIMIT")
            actual, fallback = "rag", "WIKI_CONTEXT_LIMIT"
        if actual == "rag" and mode != "rag":
            # A RAG fallback must have the same original-only candidate path.
            kept = ()
            for hit in original.items:
                candidate_hits = (*kept, hit)
                if _bytes(context_payload(candidate_hits, ())) <= context_max_bytes:
                    kept = candidate_hits
        audit = ContextAudit(
            original_retrieved=len(original.items),
            wiki_retrieved=len(ranked),
            linked_original_retrieved=len(linked),
            original_sent=len(kept),
            wiki_sent=len(navigation),
            original_bytes=_bytes([evidence(h) for h in kept]),
            wiki_bytes=_bytes([n.model_dump(mode="json") for n in navigation]) if navigation else 0,
            context_bytes=_bytes(context_payload(kept, navigation)),
            sent_chunk_ids=tuple(h.chunk.id for h in kept),
            sent_page_ids=tuple(n.page_id for n in navigation),
            original_search_sent=sum(
                h.chunk.id in {o.chunk.id for o in original.items} for h in kept
            ),
            linked_only_sent=sum(
                h.chunk.id not in {o.chunk.id for o in original.items} for h in kept
            ),
            duplicate_candidates=len(original.items) + len(linked) - len(ordered),
            selection_version="original-first-budget-v2",
        )
        self.check(frozen, navigation)
        response = original.model_copy(
            update={
                "items": kept,
                "code": "OK" if kept else "NO_EVIDENCE",
                "requested_mode": mode,
                "actual_mode": actual,
                "fallback_reason": fallback,
                "wiki_navigation": navigation,
                "audit": audit,
            }
        )
        return HybridResult(response, navigation, actual, fallback, audit)
