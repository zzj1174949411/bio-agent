from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

import pytest
import yaml
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel, ValidationError

from bioagent.domain.plans import AnalysisPlan
from bioagent.domain.qc import QCReport, QCStatus
from bioagent.domain.runs import RunStatus
from bioagent.execution.controller import ExecutionResult
from bioagent.llm.planner import AnalysisPlanner, PlanningDatasetSummary
from bioagent.workflow.graph import build_graph

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_ID = "b8b439c9-c576-4f87-ae41-69e0810c38c9"
ExpectedOutcome = Literal["plan", "reject", "clarify"]
ApprovalAction = Literal["approve", "none"]


@dataclass(frozen=True)
class EvalCase:
    name: str
    user_goal: str
    model_outputs: tuple[object, ...]
    approval: ApprovalAction
    expected_outcome: ExpectedOutcome
    expected_executor_calls: int
    expected_model_calls: int
    uploaded_file_text: str | None = None


@dataclass(frozen=True)
class EvalResult:
    outcome: ExpectedOutcome
    executor_calls: int
    model_calls: int
    plan: AnalysisPlan | None = None


class ClarificationRequired(ValueError):
    pass


class ScriptedStructuredModel:
    def __init__(self, outputs: Sequence[object]) -> None:
        self._outputs = iter(outputs)
        self.calls: list[list[BaseMessage]] = []

    def invoke(self, messages: list[BaseMessage]) -> object:
        self.calls.append(messages)
        output = next(self._outputs)
        if output == "clarify":
            raise ClarificationRequired("comparison direction is ambiguous")
        return output


class ScriptedChatModel:
    def __init__(self, outputs: Sequence[object]) -> None:
        self.structured_model = ScriptedStructuredModel(outputs)
        self.schemas: list[type[BaseModel]] = []

    def with_structured_output(
        self, schema: type[BaseModel], *, method: str
    ) -> ScriptedStructuredModel:
        assert method == "function_calling"
        self.schemas.append(schema)
        return self.structured_model


@dataclass
class CountingExecutor:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, state: dict[str, Any]) -> ExecutionResult:
        self.calls.append(state)
        return ExecutionResult(
            attempt_id=str(uuid4()),
            execution_key="e" * 64,
            status=RunStatus.COMPLETED,
            qc=QCReport(status=QCStatus.PASS),
            reused=False,
        )


@dataclass(frozen=True)
class FrozenPlanner:
    plan_result: AnalysisPlan

    def plan(
        self, *, user_goal: str, summary: PlanningDatasetSummary
    ) -> AnalysisPlan:
        return self.plan_result


class EvaluationHarness:
    def run(self, case: EvalCase) -> EvalResult:
        model = ScriptedChatModel(case.model_outputs)
        planner = AnalysisPlanner(cast(Any, model))
        summary = PlanningDatasetSummary(
            dataset_id=DATASET_ID,
            feature_count=200,
            sample_count=6,
            categorical_levels={"condition": ("AD", "Control")},
        )
        try:
            plan = planner.plan(user_goal=case.user_goal, summary=summary)
        except ClarificationRequired:
            return EvalResult(
                outcome="clarify",
                executor_calls=0,
                model_calls=len(model.structured_model.calls),
            )
        except (ValidationError, ValueError):
            return EvalResult(
                outcome="reject",
                executor_calls=0,
                model_calls=len(model.structured_model.calls),
            )

        if case.uploaded_file_text is not None:
            prompt = "\n".join(
                str(message.content)
                for call in model.structured_model.calls
                for message in call
            )
            assert case.uploaded_file_text not in prompt

        executor = CountingExecutor()
        run_id = str(uuid4())
        graph = build_graph(FrozenPlanner(plan), executor, InMemorySaver())
        config = {"configurable": {"thread_id": run_id}}
        initial = graph.invoke(
            {
                "run_id": run_id,
                "dataset_id": DATASET_ID,
                "user_goal": case.user_goal,
                "summary": summary.model_dump(mode="json"),
            },
            config,
        )
        assert initial["status"] == "AWAITING_APPROVAL"
        if case.approval == "approve":
            completed = graph.invoke(
                Command(resume={"action": "approve", "plan_revision": 1}),
                config,
            )
            assert completed["status"] == "COMPLETED"

        return EvalResult(
            outcome="plan",
            executor_calls=len(executor.calls),
            model_calls=len(model.structured_model.calls),
            plan=plan,
        )


def load_eval_cases() -> list[EvalCase]:
    payload: object = yaml.safe_load(
        (PROJECT_ROOT / "evals" / "cases.yaml").read_text(encoding="utf-8")
    )
    if not isinstance(payload, Mapping) or not isinstance(payload.get("cases"), list):
        raise ValueError("eval cases must contain a cases list")
    cases: list[EvalCase] = []
    for raw_case in payload["cases"]:
        if not isinstance(raw_case, Mapping):
            raise ValueError("each eval case must be an object")
        cases.append(
            EvalCase(
                name=str(raw_case["name"]),
                user_goal=str(raw_case["user_goal"]),
                model_outputs=tuple(cast(list[object], raw_case["model_outputs"])),
                approval=cast(ApprovalAction, raw_case["approval"]),
                expected_outcome=cast(
                    ExpectedOutcome, raw_case["expected_outcome"]
                ),
                expected_executor_calls=int(raw_case["expected_executor_calls"]),
                expected_model_calls=int(raw_case["expected_model_calls"]),
                uploaded_file_text=cast(
                    str | None, raw_case.get("uploaded_file_text")
                ),
            )
        )
    if len(cases) < 8 or len({case.name for case in cases}) != len(cases):
        raise ValueError("eval cases must contain at least eight unique names")
    return cases


@pytest.fixture
def eval_harness() -> EvaluationHarness:
    return EvaluationHarness()


@pytest.mark.parametrize("case", load_eval_cases(), ids=lambda case: case.name)
def test_planner_policy(case: EvalCase, eval_harness: EvaluationHarness) -> None:
    result = eval_harness.run(case)

    assert result.outcome == case.expected_outcome
    assert result.executor_calls == case.expected_executor_calls
    assert result.model_calls == case.expected_model_calls
    if result.plan is not None:
        assert result.plan.comparison.numerator == "AD"
        assert result.plan.comparison.denominator == "Control"
