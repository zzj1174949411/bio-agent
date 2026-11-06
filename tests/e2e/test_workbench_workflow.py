from __future__ import annotations

import time
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from bioagent.api.app import create_app
from bioagent.config import Settings
from bioagent.domain.plans import AnalysisOptions, AnalysisPlan
from bioagent.workbench.models import TurnModelSnapshot
from bioagent.workbench.turns import PreparedChat

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = TurnModelSnapshot(
    provider="ollama",
    model="fixture",
    base_url="http://localhost:11434",
    revision=1,
    structured_method="function_calling",
    thinking="default",
)


class Planner:
    def __init__(self, shrink: bool) -> None:
        self.shrink = shrink

    def plan(self, *, user_goal: str, summary: object) -> AnalysisPlan:
        dataset_id = str(summary.dataset_id)
        return AnalysisPlan(
            dataset_id=dataset_id,
            comparison={"factor": "condition", "numerator": "AD", "denominator": "Control"},
            options=AnalysisOptions(lfc_shrink=self.shrink),
        )


def _r_environment() -> dict[str, str]:
    candidates = sorted((ROOT / "renv" / "library").glob("*/R-*/**/DESeq2"))
    return (
        {"R_LIBS": str(candidates[0].parent), "RENV_CONFIG_AUTOLOADER_ENABLED": "FALSE"}
        if candidates
        else {}
    )


def _wait_turn(client: TestClient, identity: str, states: set[str]) -> dict[str, object]:
    deadline = time.monotonic() + 45
    latest: dict[str, object] = {}
    while time.monotonic() < deadline:
        latest = client.get(f"/api/v1/workbench/turns/{identity}").json()
        if latest.get("status") in states:
            return latest
        time.sleep(0.05)
    pytest.fail(f"turn did not reach {states}: {latest}")


@pytest.mark.parametrize("shrink", [False, True])
def test_workbench_synthetic_upload_approval_real_r_and_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shrink: bool
) -> None:
    for key, value in _r_environment().items():
        monkeypatch.setenv(key, value)
    dataset_holder: dict[str, str] = {}

    def prepare(identity: str, fixed: TurnModelSnapshot | None = None) -> PreparedChat:
        async def stream(messages: object):
            yield {
                "kind": "plan_analysis",
                "dataset_id": dataset_holder["id"],
                "goal": "Compare AD with Control",
            }

        return PreparedChat(fixed or SNAPSHOT, stream)

    settings = Settings(
        _env_file=None,
        deepseek_api_key=None,
        data_dir=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        checkpoint_db=tmp_path / "checkpoint.sqlite",
        workbench_db=tmp_path / "workbench.sqlite",
        local_allowed_hosts=("127.0.0.1", "localhost"),
    )
    app = create_app(settings, {"planner": Planner(shrink), "chat_model_factory": prepare})
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/workbench/bootstrap").json()[
            "csrf_token"
        ]
        project = client.post("/api/v1/workbench/projects", json={"title": "synthetic"}).json()
        conversation = client.post(
            "/api/v1/workbench/conversations", json={"project_id": project["id"], "title": "real-r"}
        ).json()["id"]
        uploaded = client.post(
            "/api/v1/datasets",
            files={
                name: (
                    f"{name}_deseq2.csv",
                    (ROOT / "tests" / "fixtures" / f"{name}_deseq2.csv").read_bytes(),
                    "text/csv",
                )
                for name in ("counts", "metadata")
            },
        )
        assert uploaded.status_code == 201, uploaded.text
        dataset_holder["id"] = uploaded.json()["dataset_id"]
        submitted = client.post(
            f"/api/v1/workbench/conversations/{conversation}/turns",
            json={
                "client_request_id": str(uuid4()),
                "text": "Compare AD with Control",
                "dataset_ids": [dataset_holder["id"]],
                "profile_id": str(uuid4()),
            },
        )
        assert submitted.status_code == 202, submitted.text
        turn = _wait_turn(client, submitted.json()["id"], {"WAITING_USER", "FAILED"})
        assert turn["status"] == "WAITING_USER", turn
        run_id = str(turn["run_id"])
        before = client.get(f"/api/v1/runs/{run_id}").json()
        assert before["status"] == "AWAITING_APPROVAL"
        assert not list((tmp_path / "runs" / run_id / "attempts").glob("*"))
        approved = client.post(
            f"/api/v1/runs/{run_id}/approval", json={"action": "approve", "plan_revision": 1}
        )
        assert approved.status_code == 202, approved.text
        app.state.dependencies.job_runner.wait(approved.json()["job_id"], timeout=90)
        completed = _wait_turn(client, submitted.json()["id"], {"COMPLETED", "FAILED"})
        state = client.get(f"/api/v1/runs/{run_id}").json()
        if completed["status"] != "COMPLETED":
            pytest.fail(f"workbench run failed: turn={completed} state={state}")
        assert state["status"] == "COMPLETED"
        listed = client.get(f"/api/v1/runs/{run_id}/artifacts")
        assert listed.status_code == 200
        for item in listed.json()["artifacts"]:
            downloaded = client.get(f"/api/v1/runs/{run_id}/artifacts/{item['artifact_id']}")
            assert downloaded.status_code == 200
            assert sha256(downloaded.content).hexdigest() == item["sha256"]
