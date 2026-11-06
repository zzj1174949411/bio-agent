"""Real Docling/E5/Qdrant API acceptance; only model answers are mocked.

Run: uv run --extra rag --offline python scripts/verify_literature_retrieval.py
All PDFs are self-authored Task38 samples. No API keys, paid APIs or user papers.
"""

import argparse
import json
import time
from pathlib import Path
from types import SimpleNamespace

import psutil
from fastapi.testclient import TestClient

from bioagent.api.app import create_app
from bioagent.config import Settings


class MemorySecrets:
    def set(self, ref, value):
        raise AssertionError("No credential writes in acceptance")

    def get(self, ref):
        raise AssertionError("No credential reads in acceptance")

    def delete(self, ref):
        raise AssertionError("No credential deletes in acceptance")


class MockAdapter:
    calls = 0

    def prepare(self, identity, fixed):
        assert fixed.model == "mock-local-acceptance"
        return self, fixed

    async def ainvoke(self, messages):
        self.calls += 1
        assert messages[0].type == "system" and "untrusted" in messages[0].content
        evidence = json.loads(messages[-1].content)["evidence"]
        assert len(evidence) <= 6
        assert all(
            set(item)
            == {"chunk_id", "text", "context", "section", "page", "kind", "visual_semantics"}
            for item in evidence
        )
        return SimpleNamespace(
            content=json.dumps(
                {
                    "answer": "Mock answer; citation ownership checked, semantic truth unverified.",
                    "citations": [evidence[0]["chunk_id"]],
                }
            )
        )


def wait(client, url, active, seconds=240):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        response = client.get(url)
        assert response.status_code == 200, response.text
        value = response.json()
        if value["status"] not in active:
            return value
        time.sleep(0.1)
    raise AssertionError(f"Timeout: {url}")


def verify(root: Path, parser_models: Path, embedding_models: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        _env_file=None,
        deepseek_api_key=None,
        data_dir=root / "data",
        runs_dir=root / "runs",
        checkpoint_db=root / "cp.sqlite",
        workbench_db=root / "wb.sqlite",
        knowledge_dir=root / "knowledge",
        knowledge_models_dir=parser_models,
        knowledge_embedding_models_dir=embedding_models,
    )
    prefix = "/api/v1/knowledge"
    measurements = {"imports": [], "queries": []}
    adapter = MockAdapter()
    overrides = {"secret_store": MemorySecrets(), "model_adapter": adapter}
    with TestClient(create_app(settings, overrides), base_url="http://localhost") as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/workbench/bootstrap").json()[
            "csrf_token"
        ]
        assert client.get(prefix + "/retrieval/readiness").json()["ready"]
        base = client.post(prefix + "/bases", json={"name": "Real retrieval acceptance"}).json()[
            "id"
        ]
        empty = client.post(prefix + "/bases", json={"name": "Scope isolation"}).json()["id"]
        names = ["digital_twocolumn_figure_table.pdf", "scan_ocr.pdf", "cross_page_table.pdf"]
        started = time.monotonic()
        imported = client.post(
            prefix + f"/bases/{base}/documents",
            files=[
                (
                    "files",
                    (name, (Path("data/task38/samples") / name).read_bytes(), "application/pdf"),
                )
                for name in names
            ],
        )
        assert imported.status_code == 202, imported.text
        documents = []
        for item in imported.json()["items"]:
            doc = wait(
                client, prefix + f"/documents/{item['document']['id']}", {"QUEUED", "PARSING"}
            )
            assert doc["status"] == "PARSED" and doc["index_revision"] is None, doc
            result = client.post(prefix + f"/documents/{doc['id']}/index")
            assert result.status_code == 202, result.text
            indexing = time.monotonic()
            job = wait(
                client, prefix + f"/index-jobs/{result.json()['id']}", {"QUEUED", "INDEXING"}
            )
            assert job["status"] == "READY", job
            doc = client.get(prefix + f"/documents/{doc['id']}").json()
            assert doc["status"] == "READY"
            assert (
                client.get(
                    prefix + f"/documents/{doc['id']}/revisions/{doc['published_revision']}"
                ).status_code
                == 200
            )
            measurements["imports"].append(
                {
                    "name": doc["filename"],
                    "index_seconds": time.monotonic() - indexing,
                    "parse_revision": doc["published_revision"],
                    "index_revision": doc["index_revision"],
                }
            )
            documents.append(doc)
        measurements["build_total_seconds"] = time.monotonic() - started
        queries = [
            ("扫描样本的质量是12.5毫克，测量时间是30秒", "text", "scan_ocr.pdf"),
            ("表格中Beta的质量和时间，质量单位mg和时间单位s", "table", names[0]),
            ("图1的柱高是否表示实验结果还是仅用于展示排版", "picture", names[0]),
        ]
        for query, kind, filename in queries:
            started = time.monotonic()
            result = client.post(
                prefix + "/search", json={"query": query, "knowledge_base_ids": [base], "top_k": 6}
            )
            assert result.status_code == 200, result.text
            page = result.json()
            hits = page["items"]
            expected_doc = next(doc["id"] for doc in documents if doc["filename"] == filename)
            rank = next(
                (
                    i
                    for i, hit in enumerate(hits, 1)
                    if hit["chunk"]["kind"] == kind
                    and hit["reference"]["document_id"] == expected_doc
                ),
                None,
            )
            measurements["queries"].append(
                {
                    "query": query,
                    "expected_kind": kind,
                    "rank": rank,
                    "seconds": time.monotonic() - started,
                    "hits": hits,
                    "retrieval": page["retrieval"],
                }
            )
            print(
                json.dumps(
                    {"query": query, "rank": rank, "kinds": [hit["chunk"]["kind"] for hit in hits]},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            assert rank is not None and rank <= 6, measurements["queries"][-1]
        first = measurements["queries"][1]["hits"][0]
        assert (
            client.post(prefix + "/evidence/validate", json=first["reference"]).status_code == 200
        )
        forged = {**first["reference"], "content_sha256": "0" * 64}
        assert client.post(prefix + "/evidence/validate", json=forged).status_code == 422
        isolated = client.post(
            prefix + "/search", json={"query": "质量", "knowledge_base_ids": [empty]}
        )
        assert isolated.json()["code"] == "NO_EVIDENCE"
        profile = client.post(
            "/api/v1/model-profiles",
            json={
                "label": "Mock only",
                "provider": "ollama",
                "model": "mock-local-acceptance",
                "base_url": "http://localhost:11434",
            },
        ).json()["id"]
        answer = client.post(
            prefix + "/ask",
            json={
                "question": queries[1][0],
                "knowledge_base_ids": [base],
                "model_profile_id": profile,
            },
        )
        assert answer.status_code == 202, answer.text
        answer = wait(client, answer.json()["status_url"], {"QUEUED", "RETRIEVING", "GENERATING"})
        assert answer["status"] == "COMPLETED" and answer["citations"]
        events = client.get(answer["events_url"]).text
        assert "answer.delta" in events and "retrieval.completed" in events
        measurements["ask"] = {
            "status": answer["status"],
            "mock_calls": adapter.calls,
            "events_verified": True,
            "visual_semantics": answer["visual_semantics"],
        }
        measurements["rss_bytes"] = psutil.Process().memory_info().rss
    # A new application and Qdrant owner must load the actual persisted vectors.
    with TestClient(create_app(settings, overrides), base_url="http://localhost") as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/workbench/bootstrap").json()[
            "csrf_token"
        ]
        page = client.post(
            prefix + "/search",
            json={"query": queries[1][0], "knowledge_base_ids": [base], "top_k": 6},
        ).json()
        assert page["items"] == measurements["queries"][1]["hits"]
        measurements["restart_equal"] = True
        doc_id = first["reference"]["document_id"]
        job = client.post(prefix + f"/documents/{doc_id}/index").json()
        assert (
            wait(client, prefix + f"/index-jobs/{job['id']}", {"QUEUED", "INDEXING"})["status"]
            == "READY"
        )
        assert (
            client.post(prefix + "/evidence/validate", json=first["reference"]).status_code == 409
        )
        measurements["rebuild_revoked_old_evidence"] = True
        assert client.get(answer["status_url"]).json()["error_code"] == "EVIDENCE_STALE"
        assert "answer.delta" not in client.get(answer["events_url"]).text
        assert client.delete(prefix + f"/bases/{base}").status_code == 204
        assert (
            client.post(prefix + "/evidence/validate", json=first["reference"]).status_code == 409
        )
        measurements["delete_revoked_evidence"] = True
    (root / "acceptance.json").write_text(
        json.dumps(measurements, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in measurements.items() if key != "queries"},
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/task39/acceptance"))
    parser.add_argument("--parser-models", type=Path, default=Path("data/task38/models"))
    parser.add_argument("--embedding-models", type=Path, default=Path("data/embedding-models"))
    args = parser.parse_args()
    verify(args.output, args.parser_models, args.embedding_models)
