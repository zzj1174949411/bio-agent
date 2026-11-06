import asyncio
import json
from types import SimpleNamespace

import pytest
import test_wiki as fixtures

from bioagent.knowledge.answers import AnswerService
from bioagent.knowledge.hybrid import HybridRetriever
from bioagent.knowledge.retrieval_models import AskRequest
from bioagent.knowledge.store import KnowledgeError

prepared = fixtures.prepared
engine = fixtures.wiki_engine


def test_hybrid_keeps_all_six_originals_before_adding_distinct_wiki_sources(engine, monkeypatch):
    from uuid import uuid4

    wiki, doc, profile = fixtures.service_for(engine)

    async def scenario():
        await fixtures.build(wiki, doc["base_id"], profile, fixtures.MockWiki())
        router = HybridRetriever(wiki.engine, wiki)
        scope = [doc["base_id"]]
        response = wiki.engine.search("Methods", scope)
        template = response.items[0]
        originals = tuple(
            template.model_copy(
                update={
                    "chunk": template.chunk.model_copy(
                        update={"id": uuid4(), "text": f"Original ranked paragraph {i}."}
                    )
                }
            )
            for i in range(6)
        )
        monkeypatch.setattr(
            wiki.engine, "search", lambda *a, **k: response.model_copy(update={"items": originals})
        )
        result = router.retrieve(
            "Methods", scope, "hybrid", wiki.engine.snapshot(scope), router.snapshot(scope), 24000
        )
        sent = {h.chunk.id for h in result.page.items}
        assert {h.chunk.id for h in originals} <= sent
        assert result.navigation and len(sent) > 6
        assert result.audit.context_bytes <= 24000
        assert result.audit.wiki_bytes <= 6000

    asyncio.run(scenario())


def test_hybrid_routes_budget_and_wiki_ablation_never_searches(engine, monkeypatch):
    wiki, doc, profile = fixtures.service_for(engine)

    async def scenario():
        await fixtures.build(wiki, doc["base_id"], profile, fixtures.MockWiki())
        router = HybridRetriever(wiki.engine, wiki)
        scope = [doc["base_id"]]
        fixed = wiki.engine.snapshot(scope)
        frozen = router.snapshot(scope)
        # Original retrieval intentionally returns only the table; Wiki resolves a different chunk.
        original = wiki.engine.search("Mass", scope, 6, fixed=fixed)
        table = next(h for h in original.items if h.chunk.kind == "table")
        monkeypatch.setattr(
            wiki.engine, "search", lambda *a, **k: original.model_copy(update={"items": (table,)})
        )
        result = router.retrieve("Methods", scope, "hybrid", fixed, frozen, 24000)
        assert result.actual_mode == "hybrid"
        assert len(result.page.items) > 1
        assert result.navigation and result.audit.original_retrieved == 1
        assert result.audit.original_sent == len(result.page.items)
        assert result.audit.wiki_sent == len(result.navigation)
        assert result.audit.context_bytes <= 24000
        assert set(result.audit.sent_chunk_ids) == {h.chunk.id for h in result.page.items}
        monkeypatch.setattr(
            wiki.engine, "search", lambda *a, **k: pytest.fail("wiki must not search original")
        )
        ablation = router.retrieve("Methods", scope, "wiki", fixed, frozen, 24000, strict=True)
        assert ablation.actual_mode == "wiki" and ablation.audit.original_retrieved == 0
        assert ablation.page.items and ablation.navigation
        foreign = wiki.store.create_base("foreign")
        with pytest.raises(KnowledgeError, match="WIKI_SNAPSHOT_MISMATCH"):
            router.retrieve("Methods", [foreign["id"]], "hybrid", (), frozen, 24000)

    asyncio.run(scenario())


def test_no_wiki_fallback_is_explicit_and_experiments_fail_closed(engine):
    wiki, doc, profile = fixtures.service_for(engine)
    router = HybridRetriever(wiki.engine, wiki)
    scope = [doc["base_id"]]
    result = router.retrieve(
        "Mass", scope, "hybrid", wiki.engine.snapshot(scope), router.snapshot(scope), 24000
    )
    assert result.actual_mode == "rag" and result.fallback_reason == "WIKI_NO_MATCH"
    with pytest.raises(KnowledgeError, match="WIKI_NO_MATCH"):
        router.retrieve(
            "Mass",
            scope,
            "hybrid",
            wiki.engine.snapshot(scope),
            router.snapshot(scope),
            24000,
            strict=True,
        )


def test_wiki_revocation_removes_answer_and_sse_even_when_original_survives(engine):
    wiki, doc, profile = fixtures.service_for(engine)
    answers = AnswerService(wiki.engine, wiki.profiles, SimpleNamespace(), wiki=wiki)

    class Model:
        async def ainvoke(self, messages):
            data = json.loads(messages[-1].content)
            assert data["wiki_navigation"]
            return SimpleNamespace(
                content=json.dumps(
                    {"answer": "Mock answer", "citations": [data["evidence"][0]["chunk_id"]]}
                )
            )

    async def scenario():
        await fixtures.build(wiki, doc["base_id"], profile, fixtures.MockWiki())
        task = await answers.submit(
            AskRequest(
                question="Methods",
                knowledge_base_ids=(doc["base_id"],),
                model_profile_id=profile,
                mode="hybrid",
            ),
            model=Model(),
        )
        await answers._tasks[str(task.id)]
        task = answers.get(str(task.id))
        assert task.status == "COMPLETED" and task.actual_mode == "hybrid"
        wiki.catalog.invalidate(task.audit.sent_page_ids[0])
        assert wiki.engine.search("Mass", [doc["base_id"]]).items  # Original index remains live.
        revoked = answers.get(str(task.id))
        assert revoked.error_code == "EVIDENCE_STALE" and not revoked.answer
        assert not revoked.evidence and not revoked.wiki_navigation
        assert not any(
            e.kind in {"answer.delta", "completed"} for e in answers.events(str(task.id), 0)
        )

    asyncio.run(scenario())


def test_navigation_omits_statements_whose_original_was_not_sent(engine, monkeypatch):
    wiki, doc, profile = fixtures.service_for(engine)

    class TwoStatements(fixtures.MockWiki):
        async def ainvoke(self, messages):
            response = await super().ainvoke(messages)
            data = json.loads(messages[-1].content)
            draft = json.loads(response.content)
            if len(data["evidence"]) > 1:
                second = data["evidence"][1]
                for page in draft["pages"]:
                    page["statements"].append(
                        {
                            "text": "UNSENT STATEMENT",
                            "conditions": "requires the second original excerpt",
                            "citations": [
                                {
                                    "chunk_id": second["chunk_id"],
                                    "content_sha256": second["content_sha256"],
                                    "quote": second["text"][:50],
                                }
                            ],
                        }
                    )
            response.content = json.dumps(draft)
            return response

    async def scenario():
        await fixtures.build(wiki, doc["base_id"], profile, TwoStatements())
        scope = [doc["base_id"]]
        response = wiki.engine.search("untrusted", scope)
        first = next(h for h in response.items if h.chunk.kind == "text")
        monkeypatch.setattr(
            wiki.engine, "search", lambda *a, **k: response.model_copy(update={"items": (first,)})
        )
        router = HybridRetriever(wiki.engine, wiki)
        # This guard concerns missing actual originals, independent of candidate top_k.
        monkeypatch.setattr(router, "_linked", lambda *a, **k: ())
        result = router.retrieve(
            "Methods",
            scope,
            "hybrid",
            wiki.engine.snapshot(scope),
            router.snapshot(scope),
            24000,
            top_k=1,
        )
        assert result.navigation
        assert result.audit.original_sent == 1
        assert "UNSENT STATEMENT" not in str(result.navigation)

    asyncio.run(scenario())


def test_failed_rebuild_revokes_old_rag_even_if_history_was_not_read_during_rebuild(engine):
    wiki, doc, profile = fixtures.service_for(engine)
    answers = AnswerService(wiki.engine, wiki.profiles, SimpleNamespace(), wiki=wiki)

    class Model:
        async def ainvoke(self, messages):
            data = json.loads(messages[-1].content)
            return SimpleNamespace(
                content=json.dumps(
                    {"answer": "Mock", "citations": [data["evidence"][0]["chunk_id"]]}
                )
            )

    async def scenario():
        task = await answers.submit(
            AskRequest(
                question="Mass", knowledge_base_ids=(doc["base_id"],), model_profile_id=profile
            ),
            model=Model(),
        )
        await answers._tasks[str(task.id)]
        assert answers.get(str(task.id)).status == "COMPLETED"
        job = wiki.engine.enqueue(doc["id"])
        wiki.engine.catalog.fail(str(job.id), "TEST_REBUILD_FAILED")
        assert wiki.engine.search("Mass", [doc["base_id"]]).items
        assert answers.get(str(task.id)).error_code == "EVIDENCE_STALE"
        assert not any(e.kind == "answer.delta" for e in answers.events(str(task.id), 0))

    asyncio.run(scenario())
