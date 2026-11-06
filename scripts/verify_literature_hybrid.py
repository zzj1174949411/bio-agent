"""Task44 real local parser/E5/Qdrant/Wiki integration; all LLMs remain Mock."""

import argparse
import json
from pathlib import Path

from verify_literature_retrieval import wait
from verify_literature_wiki import verify


def run(root: Path) -> None:
    output = {"model": "Mock; semantic quality NOT VERIFIED"}

    def inspect(client, app, base, profile, pages, docs):
        prefix = "/api/v1/knowledge"
        engine = app.state.dependencies.retrieval_engine
        adapter = app.state.dependencies.model_adapter
        original = adapter.ainvoke
        inputs = []

        async def capture(messages):
            inputs.append(json.loads(messages[-1].content))
            return await original(messages)

        adapter.ainvoke = capture
        answers = {}
        for mode in ("rag", "wiki", "hybrid"):
            result = client.post(
                prefix + "/ask",
                json={
                    "question": "table Mass mg Wiki",
                    "knowledge_base_ids": [base],
                    "model_profile_id": profile,
                    "mode": mode,
                },
            )
            assert result.status_code == 202, result.text
            task = wait(
                client,
                prefix + f"/asks/{result.json()['id']}",
                {"QUEUED", "RETRIEVING", "GENERATING", "VALIDATING"},
            )
            assert task["status"] == "COMPLETED", task
            assert task["actual_mode"] == mode and task["fallback_reason"] is None
            assert task["audit"]["context_bytes"] <= 24000
            assert task["audit"]["original_sent"] == len(task["evidence"])
            for ref in task["citations"]:
                assert client.post(prefix + "/evidence/validate", json=ref).status_code == 200
            answers[mode] = task
        assert "wiki_navigation" not in inputs[0]
        assert inputs[1]["wiki_navigation"] and inputs[2]["wiki_navigation"]
        assert answers["wiki"]["audit"]["original_retrieved"] == 0
        assert answers["hybrid"]["audit"]["original_retrieved"] > 0
        assert answers["hybrid"]["audit"]["linked_original_retrieved"] > 0
        # Ensure the actual API wiki path cannot call original search.
        search = engine.search

        def forbidden(*args, **kwargs):
            raise AssertionError("wiki ablation invoked original search")

        engine.search = forbidden
        result = client.post(
            prefix + "/search", json={"query": "Wiki", "knowledge_base_ids": [base], "mode": "wiki"}
        )
        engine.search = search
        assert result.status_code == 200 and result.json()["actual_mode"] == "wiki"
        empty = client.post(prefix + "/bases", json={"name": "No Wiki"}).json()["id"]
        result = client.post(
            prefix + "/search",
            json={"query": "Wiki", "knowledge_base_ids": [empty], "mode": "hybrid"},
        )
        assert result.status_code == 200 and result.json()["fallback_reason"] == "WIKI_NO_MATCH"
        # Cancel is durable; late mock output never publishes a delta.
        adapter.delay = 2
        result = client.post(
            prefix + "/ask",
            json={
                "question": "Wiki",
                "knowledge_base_ids": [base],
                "model_profile_id": profile,
                "mode": "hybrid",
            },
        ).json()
        assert client.post(prefix + f"/asks/{result['id']}/cancel").json()["status"] == "CANCELLED"
        replay = client.get(prefix + f"/asks/{result['id']}/events").text
        assert "answer.delta" not in replay
        # Wiki-only revocation: original revision stays available, old derived answer vanishes.
        page_id = answers["hybrid"]["audit"]["sent_page_ids"][0]
        app.state.dependencies.wiki_service.catalog.invalidate(page_id)
        assert engine.search("Mass", [base]).items
        for mode in ("hybrid", "wiki"):
            task = client.get(prefix + f"/asks/{answers[mode]['id']}").json()
            assert (
                task["error_code"] == "EVIDENCE_STALE"
                and not task["answer"]
                and not task["wiki_navigation"]
            )
            assert "answer.delta" not in client.get(task["events_url"]).text
        assert client.get(prefix + f"/asks/{answers['rag']['id']}").json()["status"] == "COMPLETED"
        document = answers["rag"]["citations"][0]["document_id"]
        rebuilding = client.post(prefix + f"/documents/{document}/index")
        assert rebuilding.status_code == 202
        assert (
            client.get(prefix + f"/asks/{answers['rag']['id']}").json()["error_code"]
            == "EVIDENCE_STALE"
        )
        assert (
            wait(client, prefix + f"/index-jobs/{rebuilding.json()['id']}", {"QUEUED", "INDEXING"})[
                "status"
            ]
            == "READY"
        )
        assert client.delete(prefix + f"/documents/{document}").status_code == 204
        assert client.get(prefix + f"/documents/{document}/pdf").status_code == 404
        output.update(
            {
                "answers": answers,
                "actual_context_payloads": inputs[:3],
                "wiki_no_original_search": True,
                "cancellation": True,
                "wiki_only_revocation": True,
                "source_rebuild_and_delete": True,
                "source_pdf_count": len(docs),
                "generation": pages["generation"],
            }
        )
        adapter.ainvoke = original

    verify(root, inspect=inspect)
    (root / "hybrid-acceptance.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: value
                for key, value in output.items()
                if key not in {"answers", "actual_context_payloads"}
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/task44/acceptance"))
    run(parser.parse_args().output.resolve())
