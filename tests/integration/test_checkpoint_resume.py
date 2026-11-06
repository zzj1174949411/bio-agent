from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langgraph.types import Command
from pydantic import ValidationError

from bioagent.domain.plans import AnalysisPlan
from bioagent.domain.qc import QCReport, QCStatus
from bioagent.domain.runs import RunStatus
from bioagent.execution.controller import ExecutionResult
from bioagent.llm.planner import PlanningDatasetSummary
from bioagent.storage.checkpoint import sqlite_checkpoint
from bioagent.storage.runs import RunRepository
from bioagent.workflow.graph import build_graph

DATASET_ID = "12345678-1234-4234-8234-123456789012"
RUN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@dataclass
class ResumePlanner:
    calls: int = 0

    def plan(
        self, *, user_goal: str, summary: PlanningDatasetSummary
    ) -> AnalysisPlan:
        self.calls += 1
        return AnalysisPlan(
            dataset_id=DATASET_ID,
            comparison={
                "factor": "condition",
                "numerator": "AD",
                "denominator": "Control",
            },
        )


@dataclass
class ResumeExecutor:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, state: dict[str, Any]) -> ExecutionResult:
        self.calls.append(state)
        return ExecutionResult(
            attempt_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            execution_key="e" * 64,
            status=RunStatus.COMPLETED,
            qc=QCReport(status=QCStatus.PASS),
            reused=False,
        )


def _state() -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "dataset_id": DATASET_ID,
        "user_goal": "AD vs Control",
        "summary": {
            "dataset_id": DATASET_ID,
            "feature_count": 2,
            "sample_count": 4,
            "categorical_levels": {"condition": ["AD", "Control"]},
        },
    }


def test_sqlite_checkpoint_resumes_approval_across_graph_instances(tmp_path: Path) -> None:
    database = tmp_path / "checkpoints.sqlite"
    config = {"configurable": {"thread_id": RUN_ID}}
    planner = ResumePlanner()
    executor = ResumeExecutor()

    with sqlite_checkpoint(database) as checkpointer:
        first_graph = build_graph(planner, executor, checkpointer)
        first = first_graph.invoke(_state(), config)
        assert first["status"] == "AWAITING_APPROVAL"
        assert executor.calls == []

    with sqlite_checkpoint(database) as checkpointer:
        resumed_graph = build_graph(planner, executor, checkpointer)
        result = resumed_graph.invoke(
            Command(resume={"action": "approve", "plan_revision": 1}),
            config,
        )

    assert result["status"] == "COMPLETED"
    assert len(executor.calls) == 1
    assert planner.calls == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] > 0


def test_run_repository_atomically_round_trips_json_state(tmp_path: Path) -> None:
    repository = RunRepository(tmp_path / "runs")
    run_id = str(uuid4())
    state = {
        "run_id": run_id,
        "status": "AWAITING_APPROVAL",
        "plan_revision": 1,
        "approval": {"status": "PENDING"},
    }

    path = repository.write(run_id, state)

    assert path == tmp_path / "runs" / run_id / "run.json"
    assert repository.read(run_id) == state
    assert repository.exists(run_id)
    assert not path.with_suffix(".json.tmp").exists()


def test_non_json_input_is_rejected_before_sqlite_checkpoint(tmp_path: Path) -> None:
    database = tmp_path / "checkpoints.sqlite"
    planner = ResumePlanner()
    executor = ResumeExecutor()
    invalid = {**_state(), "approval": Path("not-json")}

    with sqlite_checkpoint(database) as checkpointer:
        graph = build_graph(planner, executor, checkpointer)
        with pytest.raises(ValidationError):
            graph.invoke(
                invalid,
                {"configurable": {"thread_id": RUN_ID}},
            )

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "checkpoints" in tables:
            count = connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
            assert count == 0


@pytest.mark.parametrize("run_id", ["sample.", "CON", "../escape", "not-a-uuid"])
def test_run_repository_rejects_non_uuid_run_ids(
    tmp_path: Path, run_id: str
) -> None:
    repository = RunRepository(tmp_path / "runs")

    with pytest.raises(ValueError, match="invalid run id"):
        repository.write(run_id, {"run_id": run_id, "status": "DRAFT"})


def test_run_repository_rejects_payload_identity_mismatch(tmp_path: Path) -> None:
    repository = RunRepository(tmp_path / "runs")

    with pytest.raises(ValueError, match="does not match"):
        repository.write(
            str(uuid4()),
            {"run_id": str(uuid4()), "status": "DRAFT"},
        )
