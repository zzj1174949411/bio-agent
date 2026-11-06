import asyncio
import json
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
import test_retrieval as retrieval_fixtures

from bioagent.knowledge.store import KnowledgeError
from bioagent.knowledge.wiki import WikiService
from bioagent.knowledge.wiki_models import BuildRequest
from bioagent.models.profiles import ModelSnapshot

prepared = retrieval_fixtures.prepared
wiki_engine = retrieval_fixtures.engine


class MockWiki:
    def __init__(self, mode="valid"):
        self.mode, self.calls, self.inputs = mode, 0, []

    def bind(self, **kwargs):
        self.options = kwargs
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        data = json.loads(messages[-1].content)
        self.inputs.append(data)
        if self.mode == "wait":
            await asyncio.sleep(30)
        if self.mode == "fail":
            raise RuntimeError("private credential must never persist")
        ref = data["evidence"][0]
        citation = {
            "chunk_id": ref["chunk_id"],
            "quote": ref["text"][:80],
            "content_sha256": ref["content_sha256"],
        }
        if self.mode == "forged":
            citation["chunk_id"] = str(uuid4())
        if self.mode == "quote":
            citation["quote"] = "Not in source"
        if self.mode == "hash":
            citation["content_sha256"] = "0" * 64
        kinds = ["paper"] if data["stage"] == "paper" else ["concept", "topic"]
        return SimpleNamespace(
            content=json.dumps(
                {
                    "pages": [
                        {
                            "key": data["page_key"] if kind == "paper" else kind + "-methods",
                            "kind": kind,
                            "title": "Methods " + kind,
                            "statements": [
                                {
                                    "text": "Mock claim; inspect original.",
                                    "conditions": "Sample and timing must be checked",
                                    "candidate_disagreement": True,
                                    "citations": [citation],
                                }
                            ],
                            "links": data["page_keys"] if kind != "paper" else [],
                        }
                        for kind in kinds
                    ]
                }
            )
        )


def service_for(retrieval_fixture):
    retrieval, doc = retrieval_fixture
    retrieval.build(doc["id"])
    snapshot = ModelSnapshot(
        provider="ollama",
        model="mock-wiki",
        base_url="http://localhost:11434",
        revision=1,
        structured_method="function_calling",
        thinking="default",
    )
    profile = uuid4()
    profiles = SimpleNamespace(get=lambda identity: SimpleNamespace(snapshot=lambda: snapshot))
    return WikiService(retrieval, profiles, SimpleNamespace()), doc, profile


async def build(service, base, profile, model, **limits):
    request = BuildRequest(model_profile_id=profile, **limits)
    preflight = service.preflight(base, request)
    job = await service.submit(
        base,
        request.model_copy(update={"preflight_sha256": preflight.preflight_sha256}),
        model=model,
    )
    for _ in range(300):
        job = service.get(base, str(job.id))
        if job.status not in {"QUEUED", "BUILDING"}:
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("Wiki did not finish")


@pytest.mark.parametrize("mode", ["forged", "quote", "hash"])
def test_only_actual_input_citations_publish(wiki_engine, mode):
    service, doc, profile = service_for(wiki_engine)

    async def scenario():
        job = await build(service, doc["base_id"], profile, MockWiki(mode))
        assert job.status == "FAILED" and job.error_code == "WIKI_CITATION_INVALID"
        assert not service.pages(doc["base_id"]).items

    asyncio.run(scenario())


@pytest.mark.parametrize("mutation", ["delete", "parse", "rebuild"])
def test_source_changes_during_model_call_cannot_publish(wiki_engine, mutation):
    service, doc, profile = service_for(wiki_engine)

    class Mutating(MockWiki):
        async def ainvoke(self, messages):
            if mutation == "delete":
                service.store.delete_document(doc["id"])
            elif mutation == "parse":
                with service.store._db() as db:
                    revision = str(uuid4())
                    service.store._new_job(db, doc["id"], revision, doc["source_sha256"], 2)
                    db.execute(
                        "UPDATE documents SET current_revision=?,status='QUEUED' WHERE id=?",
                        (revision, doc["id"]),
                    )
            else:
                service.engine.enqueue(doc["id"])
            return await super().ainvoke(messages)

    async def scenario():
        job = await build(service, doc["base_id"], profile, Mutating())
        assert job.status == "FAILED" and not service.pages(doc["base_id"]).items

    asyncio.run(scenario())


def test_publish_transaction_failure_preserves_old_generation(wiki_engine, monkeypatch):
    service, doc, profile = service_for(wiki_engine)

    async def scenario():
        assert (await build(service, doc["base_id"], profile, MockWiki())).status == "COMPLETED"
        old = service.pages(doc["base_id"])
        original = service.catalog.save

        def fail_after_pointer(job, **changes):
            if changes.get("stage") == "published":
                raise RuntimeError("simulated commit failure")
            return original(job, **changes)

        monkeypatch.setattr(service.catalog, "save", fail_after_pointer)
        job = await build(service, doc["base_id"], profile, MockWiki(), input_max_bytes=16000)
        assert job.status == "FAILED"
        assert service.pages(doc["base_id"]) == old

    asyncio.run(scenario())


def test_atomic_incremental_failure_cross_base_and_recursive_revocation(wiki_engine):
    service, doc, profile = service_for(wiki_engine)
    base = doc["base_id"]

    async def scenario():
        model = MockWiki()
        first = await build(service, base, profile, model)
        assert first.status == "COMPLETED", first
        pages = service.pages(base)
        assert {p.kind for p in pages.items} == {"paper", "concept", "topic"}
        assert all(
            p.statements[0].citations[0].reference.base_id.hex == base.replace("-", "")
            for p in pages.items
        )
        other = service.store.create_base("other")["id"]
        with pytest.raises(KnowledgeError, match="WIKI_PAGE_NOT_FOUND"):
            service.page(other, str(pages.items[0].id))
        skipped = await build(service, base, profile, model)
        assert skipped.status == "SKIPPED" and model.calls == 2
        # A different construction profile must rebuild and failure retains valid old pages.
        failed = await build(service, base, profile, MockWiki("fail"), input_max_bytes=16000)
        assert failed.status == "FAILED"
        assert service.pages(base).generation == pages.generation
        service.engine.enqueue(doc["id"])
        assert all(p.status == "STALE" for p in service.pages(base).items)
        assert service.preflight(base, BuildRequest(model_profile_id=profile)).ready_count == 0
        for page in pages.items:
            with pytest.raises(KnowledgeError, match="WIKI_PAGE_STALE"):
                service.page(base, str(page.id))
        # Rebuilding failure cannot revive withdrawn pages, including aggregate links.
        service.engine.run_one()
        assert (await build(service, base, profile, MockWiki("fail"))).status == "FAILED"
        assert all(p.status == "STALE" for p in service.pages(base).items)
        service.store.delete_document(doc["id"])
        assert all(p.status == "STALE" for p in service.pages(base).items)

    asyncio.run(scenario())


def test_budget_coverage_cancel_restart_and_source_hash(wiki_engine):
    service, doc, profile = service_for(wiki_engine)
    base = doc["base_id"]

    async def scenario():
        request = BuildRequest(model_profile_id=profile, max_calls=1, input_max_bytes=4000)
        check = service.preflight(base, request)
        assert check.required_calls > request.max_calls
        assert check.coverage and check.protocol_limits_verified is False
        job = await build(service, base, profile, MockWiki(), max_calls=1, input_max_bytes=4000)
        assert job.status == "FAILED" and job.calls == 1 and job.error_code == "WIKI_CALL_LIMIT"
        waiting = MockWiki("wait")
        request = BuildRequest(model_profile_id=profile)
        check = service.preflight(base, request)
        job = await service.submit(
            base,
            request.model_copy(update={"preflight_sha256": check.preflight_sha256}),
            model=waiting,
        )
        while not waiting.calls:
            await asyncio.sleep(0.01)
        with pytest.raises(KnowledgeError, match="WIKI_BUILD_CONFLICT"):
            await service.submit(
                base,
                request.model_copy(update={"preflight_sha256": check.preflight_sha256}),
                model=waiting,
            )
        await service.cancel(base, str(job.id))
        assert service.get(base, str(job.id)).status == "CANCELLED"
        # Simulate durable in-flight task at process death; no automatic model invocation.
        service.catalog.save(service.get(base, str(job.id)), status="BUILDING")
        await service.start()
        assert service.get(base, str(job.id)).error_code == "WIKI_INTERRUPTED"
        await service.close()
        service.store.original(doc["id"]).write_bytes(b"%PDF-corrupted")
        with pytest.raises(KnowledgeError):
            service.preflight(base, request)

    asyncio.run(scenario())


def test_truncated_provider_json_is_explicit_and_never_publishes(wiki_engine):
    service, doc, profile = service_for(wiki_engine)

    class Truncated(MockWiki):
        async def ainvoke(self, messages):
            return SimpleNamespace(
                content='{"pages":[',
                response_metadata={"finish_reason": "length"},
                usage_metadata={"input_tokens": 10, "output_tokens": 2000, "total_tokens": 2010},
            )

    async def scenario():
        job = await build(service, doc["base_id"], profile, Truncated())
        assert job.error_code == "WIKI_OUTPUT_TRUNCATED"
        assert job.calls == 1 and job.usage["output_tokens"] == 2000
        assert not service.pages(doc["base_id"]).items

    asyncio.run(scenario())


def test_paper_navigation_candidates_are_filtered_without_trusting_model_links(wiki_engine):
    service, doc, profile = service_for(wiki_engine)

    class NavigationCandidates(MockWiki):
        async def ainvoke(self, messages):
            response = await super().ainvoke(messages)
            data = json.loads(messages[-1].content)
            draft = json.loads(response.content)
            if data["stage"] == "paper":
                draft["pages"][0]["links"] = ["concept:unpublished", "paper:foreign"]
            else:
                for page in draft["pages"]:
                    page["links"].append("topic:unpublished")
            response.content = json.dumps(draft)
            return response

    async def scenario():
        job = await build(service, doc["base_id"], profile, NavigationCandidates())
        assert job.status == "COMPLETED"
        assert job.discarded_navigation_links == 4
        assert not next(p for p in service.pages(doc["base_id"]).items if p.kind == "paper").links
        assert not any(
            "unpublished" in link or "foreign" in link
            for p in service.pages(doc["base_id"]).items
            for link in p.links
        )

    asyncio.run(scenario())


def test_wiki_can_filter_tiny_labels_with_explicit_coverage_and_keep_tables(wiki_engine):
    service, doc, profile = service_for(wiki_engine)
    request = BuildRequest(model_profile_id=profile, min_context_chars=80)
    _, batches, coverage, _ = service._inputs(doc["base_id"], request)
    selected = [item for segments in batches.values() for segment in segments for item in segment]
    assert selected and all(
        len(item["text"].strip()) >= 80
        or item["reference"]["element_id"].startswith("#/table")
        for item in selected
    )
    assert coverage[0].filtered_short_chunks == 2
    assert coverage[0].included_chunks < coverage[0].total_chunks


def test_long_input_incremental_and_published_coverage(wiki_engine):
    service, doc, profile = service_for(wiki_engine)
    base = doc["base_id"]

    async def scenario():
        model = MockWiki()
        limits = {"input_max_bytes": 4000, "max_segments_per_document": 1}
        assert (await build(service, base, profile, model, **limits)).status == "COMPLETED"
        new = service.store.import_pdf(base, "long.pdf", b"%PDF-new-long-paper")["document"]
        assert service.pages(base).pending_update and model.calls == 2
        skipped = await build(service, base, profile, model, **limits)
        assert skipped.status == "SKIPPED" and model.calls == 2
        job = service.store.claim()
        folder = service.store.job_dir(job["id"])
        folder.mkdir()
        for name in ["docling.json", "settings.json", "models.json"]:
            (folder / name).write_bytes(b"{}")
        elements = [
            {
                "id": f"#/text/{i}",
                "kind": "text",
                "order": i,
                "text": f"Paragraph {i}: " + "condition and sample " * 35,
                "section": ["Methods"],
                "locations": [{"page": 1, "bbox": [0, 0, 10, 10], "origin": "TOPLEFT"}],
            }
            for i in range(20)
        ]
        digest = sha256(b"{}").hexdigest()
        (folder / "parsed.json").write_text(
            json.dumps(
                {
                    "source_sha256": new["source_sha256"],
                    "parser_version": "fixture",
                    "settings_sha256": digest,
                    "models_sha256": digest,
                    "raw_sha256": digest,
                    "page_count": 1,
                    "elements": elements,
                    "warnings": [],
                    "assets": [],
                }
            ),
            encoding="utf-8",
        )
        assert service.store.publish(job["id"])
        service.engine.build(new["id"])
        rebuilt = await build(service, base, profile, model, **limits)
        assert rebuilt.status == "COMPLETED" and rebuilt.calls == 2
        listing = service.pages(base)
        coverage = next(c for c in listing.coverage if str(c.document_id) == new["id"])
        assert coverage.truncated and 0 < coverage.included_chunks < coverage.total_chunks
        paper = next(p for p in listing.items if p.key == f"paper:{new['id']}")
        assert paper.coverage == (coverage,)
        assert all(
            len(
                json.dumps(
                    payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode()
            )
            < 4000
            for payload in model.inputs
        )

    asyncio.run(scenario())


def test_physical_source_tamper_revokes_persistently(wiki_engine):
    service, doc, profile = service_for(wiki_engine)

    async def scenario():
        assert (await build(service, doc["base_id"], profile, MockWiki())).status == "COMPLETED"
        path = service.store.original(doc["id"])
        original = path.read_bytes()
        path.write_bytes(b"%PDF-source-tampered")
        assert all(
            p.status == "STALE" and not p.statements for p in service.pages(doc["base_id"]).items
        )
        path.write_bytes(original)
        # Restoring bytes cannot restore already withdrawn generated assertions.
        assert all(p.status == "STALE" for p in service.pages(doc["base_id"]).items)

    asyncio.run(scenario())


def test_prompt_change_rebuilds_papers_instead_of_mixing_snapshots(wiki_engine, monkeypatch):
    import bioagent.knowledge.wiki as wiki_module

    service, doc, profile = service_for(wiki_engine)

    async def scenario():
        model = MockWiki()
        assert (await build(service, doc["base_id"], profile, model)).calls == 2
        monkeypatch.setattr(
            wiki_module, "SYSTEM", wiki_module.SYSTEM + "\nPreserve source conditions."
        )
        request = BuildRequest(model_profile_id=profile)
        assert service.preflight(doc["base_id"], request).required_calls == 2
        assert (await build(service, doc["base_id"], profile, model)).calls == 2

    asyncio.run(scenario())
