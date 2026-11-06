"""Real Task 38 API acceptance using only the three self-authored PDF samples.

Run: uv run --extra rag python scripts/verify_literature_ingestion.py
Uses ignored data/task38/api-acceptance; no model API or user literature is read.
"""

import argparse
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from bioagent.api.app import create_app
from bioagent.config import Settings


def verify(root: Path, models: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        _env_file=None,
        deepseek_api_key=None,
        data_dir=root / "data",
        runs_dir=root / "runs",
        workbench_db=root / "workbench.sqlite",
        checkpoint_db=root / "checkpoint.sqlite",
        knowledge_dir=root / "knowledge",
        knowledge_models_dir=models,
    )
    names = ["digital_twocolumn_figure_table.pdf", "scan_ocr.pdf", "cross_page_table.pdf"]
    prefix = "/api/v1/knowledge"
    summaries = []
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/workbench/bootstrap").json()[
            "csrf_token"
        ]
        ready = client.get(prefix + "/readiness").json()
        assert ready["ready"], ready
        base = client.post(prefix + "/bases", json={"name": "Self-authored Task38 acceptance"})
        assert base.status_code == 201, base.text
        base_id = base.json()["id"]
        response = client.post(
            prefix + f"/bases/{base_id}/documents",
            files=[
                (
                    "files",
                    (name, (Path("data/task38/samples") / name).read_bytes(), "application/pdf"),
                )
                for name in names
            ],
        )
        assert response.status_code == 202, response.text
        deadline = time.monotonic() + 240
        for item in response.json()["items"]:
            doc = item["document"]
            while doc["status"] in {"QUEUED", "PARSING"} and time.monotonic() < deadline:
                time.sleep(0.2)
                result = client.get(prefix + f"/documents/{doc['id']}")
                assert result.status_code == 200, result.text
                doc = result.json()
            assert doc["status"] == "PARSED", doc
            assert doc["index_revision"] is None
            result = client.get(
                prefix + f"/documents/{doc['id']}/revisions/{doc['published_revision']}"
            )
            assert result.status_code == 200, result.text
            parsed = result.json()
            for element in parsed["elements"]:
                assert all(1 <= loc["page"] <= parsed["page_count"] for loc in element["locations"])
            if doc["filename"] == "scan_ocr.pdf":
                text = " ".join(element["text"] for element in parsed["elements"])
                assert all(token in text for token in ["SCAN-ALPHA", "12.5 mg", "30 s"])
                assert any(cell["from_ocr"] for cell in parsed["page_text_cells"]["1"])
            if doc["filename"] == "digital_twocolumn_figure_table.pdf":
                pictures = [e for e in parsed["elements"] if e["kind"] == "picture"]
                assert pictures and pictures[0]["captions"] and pictures[0]["asset_id"]
                assert pictures[0]["ocr_text"]
                assert pictures[0]["visual_semantics"] == "not_performed"
                tables = [e for e in parsed["elements"] if e["kind"] == "table"]
                assert tables and tables[0]["footnotes"]
                assert "Mass (mg)" in tables[0]["text"] and "Time (s)" in tables[0]["text"]
            if doc["filename"] == "cross_page_table.pdf":
                assert parsed["page_count"] == 2
                tables = [e for e in parsed["elements"] if e["kind"] == "table"]
                assert {loc["page"] for e in tables for loc in e["locations"]} == {1, 2}
                warning = "TABLE_STRUCTURE_AND_CROSS_PAGE_CONTINUITY_REQUIRE_REVIEW"
                assert warning in parsed["warnings"]
            for asset in parsed["assets"]:
                result = client.get(
                    prefix + f"/documents/{doc['id']}/revisions/"
                    f"{doc['published_revision']}/assets/{asset['id']}"
                )
                assert result.status_code == 200 and result.content.startswith(b"\x89PNG\r\n\x1a\n")
            metrics_path = (
                root
                / "knowledge"
                / "documents"
                / doc["id"]
                / (doc["published_revision"])
                / "metrics.json"
            )
            summaries.append(
                {
                    "filename": doc["filename"],
                    "status": doc["status"],
                    "pages": parsed["page_count"],
                    "elements": len(parsed["elements"]),
                    "assets": len(parsed["assets"]),
                    "warnings": parsed["warnings"],
                    **json.loads(metrics_path.read_bytes()),
                }
            )
            print(json.dumps(summaries[-1], ensure_ascii=False), flush=True)
        # Resource access is revoked by the deletion transaction.
        assert client.delete(prefix + f"/bases/{base_id}").status_code == 204
        assert client.get(prefix + f"/documents/{doc['id']}/pdf").status_code == 404
    (root / "acceptance.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/task38/api-acceptance"))
    parser.add_argument("--models", type=Path, default=Path("data/task38/models"))
    arguments = parser.parse_args()
    verify(arguments.output, arguments.models)
