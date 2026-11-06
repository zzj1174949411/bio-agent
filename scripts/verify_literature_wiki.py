"""Real offline Docling/E5/Qdrant API acceptance, Wiki and Ask models only Mock."""

import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient
from literature_wiki_mock import MockWikiAdapter
from verify_literature_retrieval import MemorySecrets, wait

from bioagent.api.app import create_app
from bioagent.config import Settings


def verify(root: Path, inspect=None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        _env_file=None,
        deepseek_api_key=None,
        data_dir=root / "data",
        runs_dir=root / "runs",
        checkpoint_db=root / "cp.sqlite",
        workbench_db=root / "wb.sqlite",
        knowledge_dir=root / "knowledge",
        knowledge_models_dir=Path("data/task38/models").resolve(),
        knowledge_embedding_models_dir=Path("data/embedding-models").resolve(),
    )
    prefix = "/api/v1/knowledge"
    adapter = MockWikiAdapter()
    app = create_app(settings, {"secret_store": MemorySecrets(), "model_adapter": adapter})
    output = {"model": "Mock only; semantic quality NOT VERIFIED", "documents": []}
    with TestClient(app, base_url="http://localhost") as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/workbench/bootstrap").json()[
            "csrf_token"
        ]
        base = client.post(prefix + "/bases", json={"name": "Task43 real local Wiki"}).json()["id"]
        other = client.post(prefix + "/bases", json={"name": "Isolation"}).json()["id"]
        docs = []
        for name in ["digital_twocolumn_figure_table.pdf", "scan_ocr.pdf", "cross_page_table.pdf"]:
            result = client.post(
                prefix + f"/bases/{base}/documents",
                files={
                    "files": (
                        name,
                        (Path("data/task38/samples") / name).read_bytes(),
                        "application/pdf",
                    )
                },
            )
            assert result.status_code == 202, result.text
            doc = wait(
                client,
                prefix + f"/documents/{result.json()['items'][0]['document']['id']}",
                {"QUEUED", "PARSING"},
            )
            assert doc["status"] == "PARSED", doc
            indexed = client.post(prefix + f"/documents/{doc['id']}/index")
            assert indexed.status_code == 202, indexed.text
            assert (
                wait(
                    client, prefix + f"/index-jobs/{indexed.json()['id']}", {"QUEUED", "INDEXING"}
                )["status"]
                == "READY"
            )
            docs.append(doc)
        wiki = prefix + f"/bases/{base}/wiki"
        assert client.get(wiki + "/status").json() is None and adapter.calls == 0
        profile = client.post(
            "/api/v1/model-profiles",
            json={
                "label": "Mock acceptance",
                "provider": "ollama",
                "model": "mock-wiki-acceptance",
                "base_url": "http://localhost:11434",
                "structured_method": "function_calling",
            },
        ).json()["id"]
        request = {"model_profile_id": profile, "max_calls": 16}

        def build():
            preflight = client.post(wiki + "/preflight", json=request)
            assert preflight.status_code == 200, preflight.text
            result = client.post(
                wiki + "/build",
                json={**request, "preflight_sha256": preflight.json()["preflight_sha256"]},
            )
            assert result.status_code == 202, result.text
            job = wait(client, wiki + f"/jobs/{result.json()['id']}", {"QUEUED", "BUILDING"})
            assert job["status"] in {"COMPLETED", "SKIPPED"}, job
            return job

        job = build()
        pages = client.get(wiki + "/pages").json()
        expected_calls = sum(c["segments"] for c in job["coverage"]) + 1
        assert len(pages["items"]) == 5 and job["calls"] == expected_calls
        assert job["usage"] is None and not job["usage_complete"]
        assert not pages["pending_update"]
        for page in pages["items"]:
            assert client.get(prefix + f"/bases/{other}/wiki/pages/{page['id']}").status_code == 404
            assert client.get(wiki + f"/pages/{page['id']}/export").status_code == 200
            for statement in page["statements"]:
                for citation in statement["citations"]:
                    ref = citation["reference"]
                    chunk = client.post(prefix + "/evidence/validate", json=ref)
                    assert chunk.status_code == 200 and citation["quote"] in chunk.json()["text"]
        chosen = pages["items"][0]
        citation = chosen["statements"][0]["citations"][0]
        evidence = wiki + f"/pages/{chosen['id']}/evidence/{citation['chunk_id']}"
        preview = client.get(evidence + "/page")
        assert preview.status_code == 200 and preview.content.startswith(b"\x89PNG")
        assert build()["status"] == "SKIPPED" and adapter.calls == expected_calls
        asked = client.post(
            prefix + "/ask",
            json={
                "question": "table Mass mg",
                "knowledge_base_ids": [base],
                "model_profile_id": profile,
            },
        )
        assert asked.status_code == 202
        answer = wait(
            client,
            prefix + f"/asks/{asked.json()['id']}",
            {"QUEUED", "RETRIEVING", "GENERATING", "VALIDATING"},
        )
        assert answer["status"] == "COMPLETED" and answer["citations"]
        if inspect is not None:
            inspect(client, app, base, profile, pages, docs)
            return  # Caller owns mutation/revocation assertions for its independent acceptance.
        output.update(
            {
                "base_id": base,
                "generation": pages["generation"],
                "initial_calls": job["calls"],
                "documents": [d["id"] for d in docs],
            }
        )
    # Restart with the same real local store. No paid client or user service involved.
    with TestClient(
        create_app(settings, {"secret_store": MemorySecrets(), "model_adapter": adapter}),
        base_url="http://localhost",
    ) as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/workbench/bootstrap").json()[
            "csrf_token"
        ]
        assert client.get(wiki + "/pages").json() == pages
        doc_id = citation["reference"]["document_id"]
        result = client.post(prefix + f"/documents/{doc_id}/index")
        assert result.status_code == 202
        stale = client.get(wiki + "/pages").json()
        affected = [
            p for p in stale["items"] if p["kind"] != "paper" or p["key"] == f"paper:{doc_id}"
        ]
        assert all(
            p["status"] == "STALE" and not p["statements"] and not p["links"] for p in affected
        )
        assert client.get(evidence).status_code == 409
        assert (
            wait(client, prefix + f"/index-jobs/{result.json()['id']}", {"QUEUED", "INDEXING"})[
                "status"
            ]
            == "READY"
        )
        preflight = client.post(wiki + "/preflight", json=request).json()
        incremental_calls = (
            next(c["segments"] for c in preflight["coverage"] if c["document_id"] == doc_id) + 1
        )
        assert preflight["required_calls"] == incremental_calls  # Two unchanged papers reused.
        result = client.post(
            wiki + "/build", json={**request, "preflight_sha256": preflight["preflight_sha256"]}
        )
        rebuilt = wait(client, wiki + f"/jobs/{result.json()['id']}", {"QUEUED", "BUILDING"})
        assert rebuilt["status"] == "COMPLETED" and rebuilt["calls"] == incremental_calls
        current = client.get(wiki + "/pages").json()
        assert current["generation"] != pages["generation"]
        assert client.delete(prefix + f"/documents/{doc_id}").status_code == 204
        revoked = client.get(wiki + "/pages").json()
        assert revoked["pending_update"]
        assert all(p["status"] == "STALE" for p in revoked["items"] if p["kind"] != "paper")
        output.update(
            {
                "incremental_calls": rebuilt["calls"],
                "restart_consistent": True,
                "rebuild_and_delete_cascade": True,
            }
        )
    with TestClient(
        create_app(settings, {"secret_store": MemorySecrets(), "model_adapter": adapter}),
        base_url="http://localhost",
    ) as client:
        assert client.get(wiki + "/pages").json() == revoked
    (root / "acceptance.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/task43/acceptance"))
    verify(parser.parse_args().output.resolve())
