from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from bioagent.domain.plans import AnalysisPlan
from bioagent.domain.qc import QCIssue, QCReport, QCStatus
from bioagent.domain.runs import RunStatus
from bioagent.execution.controller import (
    ExecutionRejectedError,
    ExecutionResult,
    calculate_plan_hash,
)
from bioagent.execution.r_runner import RExecutionCancelledError
from bioagent.llm.planner import PlanningDatasetSummary
from bioagent.workflow.graph import build_graph

DATASET_ID = "12345678-1234-4234-8234-123456789012"
RUN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ATTEMPT_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def _plan() -> AnalysisPlan:
    return AnalysisPlan(
        dataset_id=DATASET_ID,
        comparison={
            "factor": "condition",
            "numerator": "AD",
            "denominator": "Control",
        },
    )


def _execution_result(
    *,
    status: RunStatus = RunStatus.COMPLETED,
    qc: QCReport | None = None,
) -> ExecutionResult:
    return ExecutionResult(
        attempt_id=ATTEMPT_ID,
        execution_key="e" * 64,
        status=status,
        qc=qc or QCReport(status=QCStatus.PASS),
        reused=False,
    )


@dataclass
class FakePlanner:
    plan_result: AnalysisPlan = field(default_factory=_plan)
    calls: int = 0

    def plan(
        self, *, user_goal: str, summary: PlanningDatasetSummary
    ) -> AnalysisPlan:
        self.calls += 1
        return self.plan_result


@dataclass
class SpyExecutor:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, state: dict[str, Any]) -> ExecutionResult:
        self.calls.append(state)
        return _execution_result()


class StateOverrideExecutor:
    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "COMPLETED",
            "attempt_id": "executor-controlled-attempt",
            "approval": {"status": "BYPASSED"},
        }


@dataclass
class OutputExecutor:
    output: dict[str, Any]

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return self.output


class FailingPlanner:
    def plan(
        self, *, user_goal: str, summary: PlanningDatasetSummary
    ) -> AnalysisPlan:
        raise RuntimeError("provider unavailable")


class CancelledExecutor:
    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        raise RExecutionCancelledError


class RejectedExecutor:
    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        raise ExecutionRejectedError("PLAN_HASH_MISMATCH")


class MutatingExecutor:
    def __call__(self, state: dict[str, Any]) -> ExecutionResult:
        state["approval"]["status"] = "BYPASSED"
        state["plan"]["comparison"]["numerator"] = "MUTATED"
        return _execution_result()


class FailedResultExecutor:
    def __call__(self, state: dict[str, Any]) -> ExecutionResult:
        return _execution_result(
            status=RunStatus.FAILED,
            qc=QCReport(
                status=QCStatus.FAIL,
                issues=(
                    QCIssue(
                        code="R_EXECUTION_FAILED",
                        status=QCStatus.FAIL,
                        message="R execution failed",
                    ),
                ),
            ),
        )


def _initial_state() -> dict[str, Any]:
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


def test_graph_interrupts_before_execution(
    fake_planner: FakePlanner, spy_executor: SpyExecutor
) -> None:
    graph = build_graph(fake_planner, spy_executor, InMemorySaver())
    config = {"configurable": {"thread_id": RUN_ID}}

    result = graph.invoke(_initial_state(), config)

    assert result["status"] == "AWAITING_APPROVAL"
    assert spy_executor.calls == []


def test_initial_input_cannot_inject_workflow_control_fields(
    fake_planner: FakePlanner, spy_executor: SpyExecutor
) -> None:
    graph = build_graph(fake_planner, spy_executor, InMemorySaver())
    injected = {
        **_initial_state(),
        "status": "QUEUED",
        "plan": _plan().model_dump(mode="json"),
        "plan_revision": 1,
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        graph.invoke(
            injected,
            {"configurable": {"thread_id": RUN_ID}},
        )

    assert spy_executor.calls == []


def test_graph_exposes_required_nodes_and_error_destinations(
    fake_planner: FakePlanner, spy_executor: SpyExecutor
) -> None:
    graph = build_graph(fake_planner, spy_executor, InMemorySaver())

    assert set(graph.get_graph().nodes) == {
        "__start__",
        "load_summary",
        "plan",
        "validate_plan",
        "approval_interrupt",
        "execute",
        "validate_outputs",
        "report",
        "complete",
        "await_user",
        "failed",
        "__end__",
    }


def test_approval_executes_once_and_completes(
    fake_planner: FakePlanner, spy_executor: SpyExecutor
) -> None:
    graph = build_graph(fake_planner, spy_executor, InMemorySaver())
    config = {"configurable": {"thread_id": RUN_ID}}
    graph.invoke(_initial_state(), config)

    result = graph.invoke(
        Command(resume={"action": "approve", "plan_revision": 1}),
        config,
    )

    assert result["status"] == "COMPLETED"
    assert len(spy_executor.calls) == 1
    assert "attempt_id" not in spy_executor.calls[0]
    assert result["attempt_id"] == ATTEMPT_ID

    with pytest.raises(ValueError, match="already exists"):
        graph.invoke(_initial_state(), config)

    assert len(spy_executor.calls) == 1


def test_approval_binds_current_plan_hash(
    fake_planner: FakePlanner,
    spy_executor: SpyExecutor,
) -> None:
    graph = build_graph(
        fake_planner,
        spy_executor,
        InMemorySaver(),
    )
    config = {"configurable": {"thread_id": RUN_ID}}

    graph.invoke(_initial_state(), config)

    result = graph.invoke(
        Command(
            resume={
                "action": "approve",
                "plan_revision": 1,
            }
        ),
        config,
    )

    approval = result["approval"]
    assert approval == {
        "action": "approve",
        "status": "APPROVED",
        "plan_revision": 1,
        "plan_hash": calculate_plan_hash(_plan()),
        "actor": "user",
        "decided_at": approval["decided_at"],
    }
    decided_at = datetime.fromisoformat(approval["decided_at"])
    assert decided_at.tzinfo is not None


def test_existing_thread_rejects_replacement_initial_input(
    fake_planner: FakePlanner, spy_executor: SpyExecutor
) -> None:
    graph = build_graph(fake_planner, spy_executor, InMemorySaver())
    config = {"configurable": {"thread_id": RUN_ID}}
    graph.invoke(_initial_state(), config)
    replacement = _initial_state()
    replacement["user_goal"] = "replace checkpointed goal"

    with pytest.raises(ValueError, match="already exists"):
        graph.invoke(replacement, config)

    assert spy_executor.calls == []


def test_invalid_summary_fails_validation_without_planning_or_execution(
    fake_planner: FakePlanner, spy_executor: SpyExecutor
) -> None:
    graph = build_graph(fake_planner, spy_executor, InMemorySaver())
    invalid = _initial_state()
    invalid["summary"] = {"dataset_id": DATASET_ID}

    result = graph.invoke(
        invalid,
        {"configurable": {"thread_id": RUN_ID}},
    )

    assert result["status"] == "VALIDATION_FAILED"
    assert result["error"] == {"code": "SUMMARY_INVALID"}
    assert fake_planner.calls == 0
    assert spy_executor.calls == []


def test_graph_revalidates_plan_against_checkpointed_summary(
    spy_executor: SpyExecutor,
) -> None:
    planner = FakePlanner(
        plan_result=AnalysisPlan(
            dataset_id=DATASET_ID,
            comparison={
                "factor": "cohort",
                "numerator": "AD",
                "denominator": "Control",
            },
        )
    )
    graph = build_graph(planner, spy_executor, InMemorySaver())

    result = graph.invoke(
        _initial_state(),
        {"configurable": {"thread_id": RUN_ID}},
    )

    assert result["status"] == "VALIDATION_FAILED"
    assert result["error"] == {"code": "PLAN_VALIDATION_FAILED"}
    assert spy_executor.calls == []


def test_planner_runtime_failure_uses_distinct_stable_error(
    spy_executor: SpyExecutor,
) -> None:
    graph = build_graph(FailingPlanner(), spy_executor, InMemorySaver())

    result = graph.invoke(
        _initial_state(),
        {"configurable": {"thread_id": RUN_ID}},
    )

    assert result["status"] == "VALIDATION_FAILED"
    assert result["error"] == {"code": "PLANNER_FAILED"}
    assert spy_executor.calls == []


def test_executor_cannot_override_workflow_control_fields(
    fake_planner: FakePlanner,
) -> None:
    graph = build_graph(fake_planner, StateOverrideExecutor(), InMemorySaver())
    config = {"configurable": {"thread_id": RUN_ID}}
    graph.invoke(_initial_state(), config)

    result = graph.invoke(
        Command(resume={"action": "approve", "plan_revision": 1}),
        config,
    )

    assert result["status"] == "FAILED"
    assert result["error"] == {"code": "EXECUTOR_OUTPUT_INVALID"}
    assert "attempt_id" not in result
    assert result["approval"]["status"] == "APPROVED"


@pytest.mark.parametrize(
    ("output", "expected_error"),
    [
        ({}, "EXECUTOR_OUTPUT_INVALID"),
        (
            {
                "attempt_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                "qc": {"status": "BANANA", "issues": []},
            },
            "EXECUTOR_OUTPUT_INVALID",
        ),
        (
            {
                "attempt_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                "qc": {
                    "status": "FAIL",
                    "issues": [
                        {
                            "code": "MISSING_OUTPUT",
                            "status": "FAIL",
                            "message": "required output is missing",
                            "evidence": {},
                        }
                    ],
                }
            },
            "EXECUTOR_OUTPUT_INVALID",
        ),
        (
            {
                "attempt_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                "qc": {"status": "PASS", "issues": []},
                "report": {"forged": True},
            },
            "EXECUTOR_OUTPUT_INVALID",
        ),
    ],
)
def test_invalid_or_failed_executor_qc_never_completes(
    fake_planner: FakePlanner,
    output: dict[str, Any],
    expected_error: str,
) -> None:
    graph = build_graph(fake_planner, OutputExecutor(output), InMemorySaver())
    config = {"configurable": {"thread_id": RUN_ID}}
    graph.invoke(_initial_state(), config)

    result = graph.invoke(
        Command(resume={"action": "approve", "plan_revision": 1}),
        config,
    )

    assert result["status"] == "FAILED"
    assert result["error"] == {"code": expected_error}
    assert "report" not in result


def test_failed_execution_result_preserves_attempt_and_stable_error(
    fake_planner: FakePlanner,
) -> None:
    graph = build_graph(fake_planner, FailedResultExecutor(), InMemorySaver())
    config = {"configurable": {"thread_id": RUN_ID}}
    graph.invoke(_initial_state(), config)

    result = graph.invoke(
        Command(resume={"action": "approve", "plan_revision": 1}),
        config,
    )

    assert result["status"] == "FAILED"
    assert result["attempt_id"] == ATTEMPT_ID
    assert result["error"] == {"code": "R_EXECUTION_FAILED"}


def test_plan_revision_requires_fresh_approval(
    fake_planner: FakePlanner, spy_executor: SpyExecutor
) -> None:
    graph = build_graph(fake_planner, spy_executor, InMemorySaver())
    config = {"configurable": {"thread_id": RUN_ID}}
    graph.invoke(_initial_state(), config)
    revised_payload = _plan().model_dump(mode="python")
    revised_payload["options"]["alpha"] = 0.1
    revised_plan = AnalysisPlan.model_validate(revised_payload)

    revised = graph.invoke(
        Command(
            resume={
                "action": "revise",
                "plan_revision": 1,
                "plan": revised_plan.model_dump(mode="json"),
            }
        ),
        config,
    )

    assert revised["status"] == "AWAITING_APPROVAL"
    assert revised["plan_revision"] == 2
    assert revised["approval"] == {"status": "PENDING", "plan_revision": 2}
    assert spy_executor.calls == []

    completed = graph.invoke(
        Command(resume={"action": "approve", "plan_revision": 2}),
        config,
    )

    assert completed["status"] == "COMPLETED"
    assert len(spy_executor.calls) == 1


def test_invalid_plan_revision_returns_to_approval(
    fake_planner: FakePlanner, spy_executor: SpyExecutor
) -> None:
    graph = build_graph(fake_planner, spy_executor, InMemorySaver())
    config = {"configurable": {"thread_id": RUN_ID}}
    graph.invoke(_initial_state(), config)
    invalid_plan = _plan().model_dump(mode="python")
    invalid_plan["comparison"]["factor"] = "cohort"

    result = graph.invoke(
        Command(
            resume={
                "action": "revise",
                "plan_revision": 1,
                "plan": invalid_plan,
            }
        ),
        config,
    )

    assert result["status"] == "AWAITING_APPROVAL"
    assert result["error"] == {"code": "PLAN_VALIDATION_FAILED"}
    assert result["approval"] == {"status": "PENDING", "plan_revision": 1}
    assert spy_executor.calls == []


def test_executor_cancellation_uses_cancelled_terminal_state(
    fake_planner: FakePlanner,
) -> None:
    graph = build_graph(fake_planner, CancelledExecutor(), InMemorySaver())
    config = {"configurable": {"thread_id": RUN_ID}}
    graph.invoke(_initial_state(), config)

    result = graph.invoke(
        Command(resume={"action": "approve", "plan_revision": 1}),
        config,
    )

    assert result["status"] == "CANCELLED"
    assert result["error"] == {"code": "R_EXECUTION_CANCELLED"}


def test_controller_rejection_preserves_stable_error_code(
    fake_planner: FakePlanner,
) -> None:
    graph = build_graph(fake_planner, RejectedExecutor(), InMemorySaver())
    config = {"configurable": {"thread_id": RUN_ID}}
    graph.invoke(_initial_state(), config)

    result = graph.invoke(
        Command(resume={"action": "approve", "plan_revision": 1}),
        config,
    )

    assert result["status"] == "FAILED"
    assert result["error"] == {"code": "PLAN_HASH_MISMATCH"}


@pytest.mark.parametrize(
    "action, expected_status",
    [("reject", "CANCELLED"), ("cancel", "CANCELLED")],
)
def test_rejection_and_cancellation_never_execute(
    fake_planner: FakePlanner,
    spy_executor: SpyExecutor,
    action: str,
    expected_status: str,
) -> None:
    graph = build_graph(fake_planner, spy_executor, InMemorySaver())
    config = {"configurable": {"thread_id": RUN_ID}}
    graph.invoke(_initial_state(), config)

    result = graph.invoke(Command(resume={"action": action}), config)

    assert result["status"] == expected_status
    assert spy_executor.calls == []


def test_thread_id_must_match_run_id(
    fake_planner: FakePlanner, spy_executor: SpyExecutor
) -> None:
    graph = build_graph(fake_planner, spy_executor, InMemorySaver())

    with pytest.raises(ValueError, match="thread_id must match run_id"):
        graph.invoke(
            _initial_state(),
            {
                "configurable": {
                    "thread_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
                }
            },
        )

    assert spy_executor.calls == []


def test_executor_receives_deeply_isolated_state(
    fake_planner: FakePlanner,
) -> None:
    graph = build_graph(fake_planner, MutatingExecutor(), InMemorySaver())
    config = {"configurable": {"thread_id": RUN_ID}}
    graph.invoke(_initial_state(), config)

    result = graph.invoke(
        Command(resume={"action": "approve", "plan_revision": 1}),
        config,
    )

    assert result["status"] == "COMPLETED"
    assert result["approval"]["status"] == "APPROVED"
    assert result["plan"]["comparison"]["numerator"] == "AD"


@pytest.fixture
def fake_planner() -> FakePlanner:
    return FakePlanner()


@pytest.fixture
def spy_executor() -> SpyExecutor:
    return SpyExecutor()
