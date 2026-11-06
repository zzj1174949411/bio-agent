from __future__ import annotations

import json
import tempfile
import time
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bioagent.api.app import create_app
from bioagent.config import Settings
from bioagent.domain.plans import AnalysisPlan

ROOT = Path(__file__).resolve().parents[2]


class FixturePlanner:
    def __init__(self, lfc_shrink: bool = False) -> None:
        self.lfc_shrink = lfc_shrink

    def plan(self, *, user_goal: str, summary: object) -> AnalysisPlan:
        return AnalysisPlan.model_validate(
            {
                "dataset_id": summary.dataset_id,
                "comparison": {
                    "factor": "condition",
                    "numerator": "AD",
                    "denominator": "Control",
                },
                "options": {"lfc_shrink": self.lfc_shrink},
            }
        )


@pytest.mark.parametrize("lfc_shrink", [False, True])
def test_real_api_downloads_report_manifest_and_all_hashes(
    monkeypatch: pytest.MonkeyPatch, lfc_shrink: bool
) -> None:
    libraries = sorted((ROOT / "renv/library").glob("*/R-*/**/DESeq2"))
    if libraries:
        monkeypatch.setenv("R_LIBS", str(libraries[0].parent))
    with tempfile.TemporaryDirectory(prefix=".task15-api-", dir=ROOT) as raw:
        work = Path(raw)
        app = create_app(
            Settings(
                _env_file=None,
                data_dir=work / "data",
                runs_dir=work / "runs",
                checkpoint_db=work / "checkpoints.sqlite",
            ),
            overrides={"planner": FixturePlanner(lfc_shrink)},
        )
        with TestClient(app) as client:
            upload = client.post(
                "/api/v1/datasets",
                files={
                    name: (
                        f"{name}.csv",
                        (ROOT / f"tests/fixtures/{name}_deseq2.csv").read_bytes(),
                        "text/csv",
                    )
                    for name in ("counts", "metadata")
                },
            )
            assert upload.status_code == 201
            created = client.post(
                "/api/v1/runs",
                json={
                    "dataset_id": upload.json()["dataset_id"],
                    "goal": "Compare AD with Control",
                },
            )
            run_id = created.json()["run_id"]
            assert created.json()["status"] == "AWAITING_APPROVAL"
            assert not list((work / "runs" / run_id / "attempts").glob("*"))
            approved = client.post(
                f"/api/v1/runs/{run_id}/approval",
                json={
                    "action": "approve",
                    "plan_revision": 1,
                },
            )
            assert approved.status_code == 202
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                state = client.get(f"/api/v1/runs/{run_id}").json()
                if state["status"] not in {"QUEUED", "RUNNING"}:
                    break
                time.sleep(0.1)
            assert state["status"] == "COMPLETED", state
            records = client.get(f"/api/v1/runs/{run_id}/artifacts").json()["artifacts"]
            downloaded = {}
            for record in records:
                response = client.get(f"/api/v1/runs/{run_id}/artifacts/{record['artifact_id']}")
                assert response.status_code == 200
                assert sha256(response.content).hexdigest() == record["sha256"]
                name = response.headers["content-disposition"].split('filename="')[1][:-1]
                downloaded[name] = response.content
            assert "report.html" in downloaded
            assert "manifest.json" in downloaded
            manifest = json.loads(downloaded["manifest.json"])
            assert "AD" in downloaded["report.html"].decode()
            for record in manifest["artifacts"]:
                assert (
                    sha256(downloaded[Path(record["relative_path"]).name]).hexdigest()
                    == record["sha256"]
                )
