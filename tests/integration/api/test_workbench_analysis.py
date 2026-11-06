import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from bioagent.api.app import create_app
from bioagent.config import Settings
from bioagent.domain.plans import AnalysisPlan
from bioagent.domain.qc import QCReport, QCStatus
from bioagent.domain.runs import RunStatus
from bioagent.execution.controller import ExecutionResult
from bioagent.workbench.actions import parse_action
from bioagent.workbench.models import TurnModelSnapshot
from bioagent.workbench.turns import PreparedChat


class _Planner:
    def plan(self, *, user_goal, summary):
        return AnalysisPlan(
            dataset_id=summary.dataset_id,
            comparison={"factor": "condition", "numerator": "AD", "denominator": "Control"},
        )


class _Executor:
    def execute(self, state):
        return ExecutionResult(
            attempt_id=str(uuid4()),
            execution_key="e" * 64,
            status=RunStatus.COMPLETED,
            qc=QCReport(status=QCStatus.PASS, issues=()),
            reused=False,
        )


SNAPSHOT = TurnModelSnapshot(
    provider="ollama",
    model="fixture",
    base_url="http://localhost:11434",
    revision=1,
    structured_method="function_calling",
    thinking="default",
)


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "approve", "approved": True},
        {"kind": "answer", "text": "ok", "code": "print(1)"},
        {"kind": "plan_analysis", "dataset_id": str(uuid4()), "goal": "AD", "approved": True},
    ],
)
def test_model_cannot_approve_or_inject_fields(payload):
    with pytest.raises(ValidationError):
        parse_action(payload)


def test_three_actions_are_validated():
    assert parse_action({"kind": "answer", "text": "ok"}).text == "ok"
    assert parse_action({"kind": "clarify", "question": "which?"}).question == "which?"
    identity = uuid4()
    assert (
        parse_action(
            {"kind": "plan_analysis", "dataset_id": str(identity), "goal": "AD"}
        ).dataset_id
        == identity
    )


def wait_turn(client, identity, states):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        turn = client.get(f"/api/v1/workbench/turns/{identity}").json()
        if turn["status"] in states:
            return turn
        time.sleep(0.02)
    pytest.fail(f"turn did not reach {states}: {turn}")


def make_app(tmp_path, outputs, *, executor=None, real=False):
    def prepare(identity, fixed=None):
        async def stream(messages):
            for output in outputs:
                yield output

        return PreparedChat(fixed or SNAPSHOT, stream)

    overrides = {"planner": _Planner(), "chat_model_factory": prepare}
    if not real:
        overrides["executor"] = executor or _Executor()
    return create_app(
        Settings(
            _env_file=None,
            deepseek_api_key=None,
            data_dir=tmp_path / "data",
            runs_dir=tmp_path / "runs",
            checkpoint_db=tmp_path / "checkpoint.sqlite",
            workbench_db=tmp_path / "wb.sqlite",
            local_allowed_hosts=("127.0.0.1", "localhost"),
        ),
        overrides,
    )


def setup_chat(client):
    client.headers["X-CSRF-Token"] = client.get("/api/v1/workbench/bootstrap").json()["csrf_token"]
    project = client.post("/api/v1/workbench/projects", json={"title": "fixture"}).json()
    return client.post(
        "/api/v1/workbench/conversations", json={"project_id": project["id"], "title": "chat"}
    ).json()["id"]


def submit(client, conversation, datasets=()):
    result = client.post(
        f"/api/v1/workbench/conversations/{conversation}/turns",
        json={
            "client_request_id": str(uuid4()),
            "text": "Compare AD with Control",
            "profile_id": str(uuid4()),
            "dataset_ids": list(datasets),
        },
    )
    assert result.status_code == 202, result.text
    return result.json()["id"]


def upload(client, suffix="valid"):
    result = client.post(
        "/api/v1/datasets",
        files={
            name: (
                f"{name}.csv",
                Path(f"tests/fixtures/{name}_{suffix}.csv").read_bytes(),
                "text/csv",
            )
            for name in ("counts", "metadata")
        },
    )
    assert result.status_code == 201, result.text
    return result.json()["dataset_id"]


def test_chat_plan_waits_for_original_api_approval(tmp_path):
    outputs = []
    app = make_app(tmp_path, outputs)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        conversation = setup_chat(client)
        dataset = upload(client)
        outputs.append(
            {"kind": "plan_analysis", "dataset_id": dataset, "goal": "Compare AD with Control"}
        )
        identity = submit(client, conversation, [dataset])
        turn = wait_turn(client, identity, {"WAITING_USER", "FAILED"})
        assert turn["status"] == "WAITING_USER", turn.get("error_code") or turn
        run_id = turn["run_id"]
        state = client.get(f"/api/v1/runs/{run_id}").json()
        assert state["status"] == "AWAITING_APPROVAL"
        assert state["agent_context"]["turn_id"] == identity
        assert state["agent_context"]["model_snapshot"] == SNAPSHOT.model_dump(mode="json")
        assert not list((tmp_path / "runs" / run_id / "attempts").glob("*"))
        approved = client.post(
            f"/api/v1/runs/{run_id}/approval", json={"action": "approve", "plan_revision": 1}
        )
        assert approved.status_code == 202
        app.state.dependencies.job_runner.wait(approved.json()["job_id"], timeout=10)
        assert wait_turn(client, identity, {"COMPLETED", "FAILED"})["status"] == "COMPLETED"


def test_model_cannot_select_another_conversations_dataset(tmp_path):
    outputs = []
    app = make_app(tmp_path, outputs)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        first = setup_chat(client)
        dataset = upload(client)
        outputs.append({"kind": "answer", "text": "registered"})
        wait_turn(client, submit(client, first, [dataset]), {"COMPLETED"})
        other = setup_chat(client)
        outputs[:] = [{"kind": "plan_analysis", "dataset_id": dataset, "goal": "AD"}]
        turn = wait_turn(client, submit(client, other), {"FAILED"})
        assert turn["error_code"] == "DATASET_NOT_SELECTED"
        assert client.get("/api/v1/runs").json()["runs"] == []
