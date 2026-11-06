from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from langgraph.types import interrupt
from pydantic import BaseModel, ValidationError

from bioagent.domain.plans import AnalysisPlan
from bioagent.domain.qc import QCReport, QCStatus
from bioagent.domain.runs import RunStatus, ensure_transition
from bioagent.execution.controller import (
    ExecutionRejectedError,
    ExecutionResult,
    calculate_plan_hash,
)
from bioagent.execution.r_runner import RExecutionCancelledError, RRunnerError
from bioagent.llm.planner import PlanningDatasetSummary
from bioagent.workflow.state import WorkflowState, validate_workflow_state

Planner = Any
Executor = Any


def _status(state: Mapping[str, object]) -> RunStatus:
    return RunStatus(str(state.get("status", RunStatus.DRAFT.value)))


def _transition(state: Mapping[str, object], target: RunStatus) -> None:
    current = _status(state)
    if current is not target:
        ensure_transition(current, target)


def _plan_payload(value: object) -> dict[str, object]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python", round_trip=True)
    if not isinstance(value, dict):
        raise TypeError("planner must return an AnalysisPlan or object mapping")
    plan = AnalysisPlan.model_validate(value)
    payload = cast(dict[str, object], plan.model_dump(mode="json"))
    return payload


def load_summary(state: WorkflowState) -> dict[str, object]:
    current = _status(state)
    if current in {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.VALIDATION_FAILED,
    }:
        return {}
    summary = state.get("summary")
    if not isinstance(summary, dict):
        return _summary_failure(state, "SUMMARY_MISSING")
    dataset_id = state.get("dataset_id")
    if dataset_id is not None and summary.get("dataset_id") != dataset_id:
        return _summary_failure(state, "SUMMARY_DATASET_MISMATCH")
    try:
        PlanningDatasetSummary.model_validate(summary)
    except ValidationError:
        return _summary_failure(state, "SUMMARY_INVALID")
    if current is RunStatus.DRAFT:
        _transition(state, RunStatus.VALIDATING)
        return {"status": RunStatus.VALIDATING.value}
    return {}


def make_plan(state: WorkflowState, *, planner: Planner) -> dict[str, object]:
    current = _status(state)
    if current in {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.VALIDATION_FAILED,
    } or state.get("plan"):
        return {}
    existing_error = state.get("error")
    if isinstance(existing_error, dict):
        code = existing_error.get("code")
        stable_code = code if isinstance(code, str) else "SUMMARY_INVALID"
        return _failure(state, stable_code, RunStatus.VALIDATION_FAILED)
    summary_value = state.get("summary")
    user_goal = state.get("user_goal")
    if not isinstance(summary_value, dict) or not isinstance(user_goal, str):
        return _failure(state, "PLANNING_INPUT_MISSING", RunStatus.VALIDATION_FAILED)
    try:
        summary = PlanningDatasetSummary.model_validate(summary_value)
    except ValidationError:
        return _failure(state, "PLAN_INVALID", RunStatus.VALIDATION_FAILED)
    try:
        plan_method = cast(
            Callable[..., object], getattr(planner, "plan", None) or planner
        )
        raw_plan = plan_method(user_goal=user_goal, summary=summary)
    except (TypeError, ValueError):
        return _failure(state, "PLAN_INVALID", RunStatus.VALIDATION_FAILED)
    except Exception:
        return _failure(state, "PLANNER_FAILED", RunStatus.VALIDATION_FAILED)
    try:
        payload = _plan_payload(raw_plan)
        if payload.get("dataset_id") != summary.dataset_id:
            raise ValueError("plan dataset_id does not match dataset summary")
    except (TypeError, ValueError):
        return _failure(state, "PLAN_INVALID", RunStatus.VALIDATION_FAILED)
    return {"plan": payload, "plan_revision": 1}


def validate_plan(state: WorkflowState) -> dict[str, object]:
    current = _status(state)
    if current is not RunStatus.VALIDATING:
        return {}
    try:
        payload = state.get("plan")
        if not isinstance(payload, dict):
            raise ValueError("plan is missing")
        plan = AnalysisPlan.model_validate(payload)
        if plan.dataset_id != state.get("dataset_id"):
            raise ValueError("plan dataset_id does not match run")
        summary_payload = state.get("summary")
        if not isinstance(summary_payload, dict):
            raise ValueError("dataset summary is missing")
        summary = PlanningDatasetSummary.model_validate(summary_payload)
        _validate_plan_semantics(plan, summary)
        revision = state.get("plan_revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError("plan revision is invalid")
    except (TypeError, ValueError):
        return _failure(state, "PLAN_VALIDATION_FAILED", RunStatus.VALIDATION_FAILED)
    _transition(state, RunStatus.AWAITING_APPROVAL)
    return {"status": RunStatus.AWAITING_APPROVAL.value}


def _validate_plan_semantics(
    plan: AnalysisPlan, summary: PlanningDatasetSummary
) -> None:
    if plan.dataset_id != summary.dataset_id:
        raise ValueError("plan dataset_id does not match dataset summary")
    factor = plan.comparison.factor
    if factor not in summary.categorical_levels:
        raise ValueError("plan factor is not present in dataset summary")
    observed_levels = summary.categorical_levels[factor]
    if len(observed_levels) != 2 or len(set(observed_levels)) != 2:
        raise ValueError("planning factor must have exactly two observed levels")
    comparison_levels = {
        plan.comparison.numerator,
        plan.comparison.denominator,
    }
    if comparison_levels != set(observed_levels):
        raise ValueError("plan comparison levels do not match observed levels")


def approval_interrupt(state: WorkflowState) -> dict[str, object]:
    if _status(state) is not RunStatus.AWAITING_APPROVAL:
        return {}
    plan_revision = state.get("plan_revision")
    decision = interrupt(
        {
            "type": "approval_required",
            "run_id": state.get("run_id"),
            "plan": state.get("plan"),
            "plan_revision": plan_revision,
            "actions": ["approve", "revise", "reject", "cancel"],
        }
    )
    if not isinstance(decision, dict):
        return _failure(state, "APPROVAL_INVALID", RunStatus.CANCELLED)
    action = decision.get("action")
    if action in {"reject", "cancel"}:
        _transition(state, RunStatus.CANCELLED)
        return {
            "approval": {"action": action, "status": "CANCELLED"},
            "status": RunStatus.CANCELLED.value,
        }
    if action in {"revise", "modify"}:
        if decision.get("plan_revision") != plan_revision:
            return _failure(state, "APPROVAL_INVALID", RunStatus.CANCELLED)
        try:
            revised_plan = _plan_payload(decision.get("plan"))
            summary_payload = state.get("summary")
            if not isinstance(summary_payload, dict):
                raise ValueError("dataset summary is missing")
            summary = PlanningDatasetSummary.model_validate(summary_payload)
            validated_plan = AnalysisPlan.model_validate(revised_plan)
            _validate_plan_semantics(validated_plan, summary)
        except (TypeError, ValueError):
            return {
                "approval": {"status": "PENDING", "plan_revision": plan_revision},
                "status": RunStatus.AWAITING_APPROVAL.value,
                "error": {"code": "PLAN_VALIDATION_FAILED"},
            }
        if not isinstance(plan_revision, int) or isinstance(plan_revision, bool):
            return _failure(state, "APPROVAL_INVALID", RunStatus.CANCELLED)
        next_revision = plan_revision + 1
        return {
            "plan": revised_plan,
            "plan_revision": next_revision,
            "approval": {"status": "PENDING", "plan_revision": next_revision},
            "status": RunStatus.AWAITING_APPROVAL.value,
            "error": {},
        }
    if action != "approve" or decision.get("plan_revision") != plan_revision:
        return _failure(state, "APPROVAL_INVALID", RunStatus.CANCELLED)

    approved_plan = AnalysisPlan.model_validate(state.get("plan"))
    _transition(state, RunStatus.QUEUED)
    return {
        "approval": {
            "action": "approve",
            "status": "APPROVED",
            "plan_revision": plan_revision,
            "plan_hash": calculate_plan_hash(approved_plan),
            "actor": "user",
            "decided_at": datetime.now(UTC).isoformat(),
        },
        "status": RunStatus.QUEUED.value,
        "error": {},
    }


def execute(state: WorkflowState, *, executor: Executor) -> dict[str, object]:
    if _status(state) is not RunStatus.QUEUED:
        return {}
    _transition(state, RunStatus.RUNNING)
    running_state = cast(
        dict[str, object],
        json.loads(json.dumps(state, allow_nan=False, separators=(",", ":"))),
    )
    running_state.update({"status": RunStatus.RUNNING.value})
    try:
        execute_method = cast(
            Callable[..., object], getattr(executor, "execute", None) or executor
        )
        output = execute_method(cast(WorkflowState, running_state))
        if not isinstance(output, ExecutionResult):
            return {
                "status": RunStatus.FAILED.value,
                "error": {"code": "EXECUTOR_OUTPUT_INVALID"},
            }
        if not _is_uuid4(output.attempt_id):
            return {
                "status": RunStatus.FAILED.value,
                "error": {"code": "EXECUTOR_OUTPUT_INVALID"},
            }
        result_output = output.workflow_output()
        validate_workflow_state(cast(WorkflowState, result_output))
        if output.status in {RunStatus.FAILED, RunStatus.CANCELLED}:
            fallback = (
                "R_EXECUTION_CANCELLED"
                if output.status is RunStatus.CANCELLED
                else "EXECUTION_FAILED"
            )
            code = output.qc.issues[0].code if output.qc.issues else fallback
            return {
                **cast(dict[str, object], result_output),
                "status": output.status.value,
                "error": {"code": code},
            }
        if output.status is not RunStatus.COMPLETED:
            return {
                "status": RunStatus.FAILED.value,
                "error": {"code": "EXECUTOR_OUTPUT_INVALID"},
            }
    except RExecutionCancelledError as error:
        return {
            "status": RunStatus.CANCELLED.value,
            "error": {"code": error.code},
        }
    except ExecutionRejectedError as error:
        return {
            "status": RunStatus.FAILED.value,
            "error": {"code": error.code},
        }
    except RRunnerError as error:
        return {
            "status": RunStatus.FAILED.value,
            "error": {"code": error.code},
        }
    except Exception:
        return {
            "status": RunStatus.FAILED.value,
            "error": {"code": "EXECUTION_FAILED"},
        }
    result: dict[str, object] = {
        "status": RunStatus.RUNNING.value,
    }
    result.update(cast(dict[str, object], result_output))
    return result


def _is_uuid4(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return parsed.version == 4 and str(parsed) == value


def validate_outputs(state: WorkflowState) -> dict[str, object]:
    if _status(state) is not RunStatus.RUNNING:
        return {}
    qc = state.get("qc")
    try:
        if not isinstance(qc, dict):
            raise ValueError("executor did not return QC")
        validated_qc = QCReport.model_validate(qc)
    except (TypeError, ValueError):
        return {
            "status": RunStatus.FAILED.value,
            "error": {"code": "OUTPUT_VALIDATION_FAILED"},
        }
    qc_payload = validated_qc.model_dump(mode="json")
    if validated_qc.status is QCStatus.FAIL:
        return {
            "qc": qc_payload,
            "status": RunStatus.FAILED.value,
            "error": {"code": "OUTPUT_VALIDATION_FAILED"},
        }
    return {"qc": qc_payload}


def report(state: WorkflowState) -> dict[str, object]:
    if _status(state) is not RunStatus.RUNNING:
        return {}
    return {
        "report": {
            "status": "completed",
            "run_id": state.get("run_id"),
            "attempt_id": state.get("attempt_id"),
        }
    }


def complete(state: WorkflowState) -> dict[str, object]:
    validate_workflow_state(state)
    if _status(state) is RunStatus.RUNNING:
        if not isinstance(state.get("report"), dict):
            return {
                "status": RunStatus.FAILED.value,
                "error": {"code": "REPORT_FAILED"},
            }
        _transition(state, RunStatus.COMPLETED)
        return {"status": RunStatus.COMPLETED.value}
    return {}


def await_user(state: WorkflowState) -> dict[str, object]:
    validate_workflow_state(state)
    return {}


def failed(state: WorkflowState) -> dict[str, object]:
    validate_workflow_state(state)
    return {}


def _failure(
    state: Mapping[str, object], code: str, target: RunStatus
) -> dict[str, object]:
    current = _status(state)
    if current is not target:
        ensure_transition(current, target)
    return {"status": target.value, "error": {"code": code}}


def _summary_failure(state: Mapping[str, object], code: str) -> dict[str, object]:
    current = _status(state)
    if current is RunStatus.DRAFT:
        ensure_transition(current, RunStatus.VALIDATING)
        return {"status": RunStatus.VALIDATING.value, "error": {"code": code}}
    return _failure(state, code, RunStatus.VALIDATION_FAILED)
