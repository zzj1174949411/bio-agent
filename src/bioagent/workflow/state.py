from __future__ import annotations

import json
import math
from typing import Literal, Self, TypedDict
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


class WorkflowState(TypedDict, total=False):
    """The JSON-only state persisted by LangGraph.

    Runtime objects such as planners, DataFrames, Paths, subprocess handles, and
    model instances deliberately do not appear here. They are dependencies of
    graph nodes and are recreated when a graph is rebuilt for checkpoint resume.
    """

    run_id: str
    dataset_id: str
    user_goal: str
    summary: dict[str, JsonValue]
    plan: dict[str, JsonValue]
    plan_revision: int
    approval: dict[str, JsonValue]
    attempt_id: str
    status: str
    qc: dict[str, JsonValue]
    error: dict[str, JsonValue]
    report: dict[str, JsonValue]


class WorkflowInput(BaseModel):
    """Strict public input; workflow control fields can only come from nodes."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    run_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    dataset_id: str = Field(min_length=36, max_length=36)
    user_goal: str = Field(min_length=1)
    summary: dict[str, JsonValue]

    @field_validator("run_id")
    @classmethod
    def run_id_is_canonical_uuid4(cls, value: str) -> str:
        return validate_run_id(value)

    @model_validator(mode="after")
    def input_is_json_safe(self) -> Self:
        ensure_json_safe(self.model_dump(mode="python"), path="input")
        return self


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    action: Literal["approve", "reject", "cancel", "revise", "modify"]
    plan_revision: int | None = Field(default=None, ge=1)
    plan: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def required_fields_match_action(self) -> Self:
        if self.action in {"approve", "revise", "modify"} and self.plan_revision is None:
            raise ValueError("plan_revision is required for this approval action")
        if self.action in {"revise", "modify"} and self.plan is None:
            raise ValueError("plan is required for plan revision")
        if self.action not in {"revise", "modify"} and self.plan is not None:
            raise ValueError("plan is only allowed for plan revision")
        ensure_json_safe(self.model_dump(mode="python"), path="approval")
        return self


def ensure_json_safe(value: object, *, path: str = "state") -> None:
    """Reject values that cannot be safely persisted in a checkpoint."""

    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            ensure_json_safe(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} contains a non-string key")
            ensure_json_safe(item, path=f"{path}.{key}")
        return
    raise TypeError(f"{path} contains unsupported value type {type(value).__name__}")


def validate_run_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid run id")
    try:
        parsed_id = UUID(value)
    except ValueError as error:
        raise ValueError("invalid run id") from error
    if parsed_id.version != 4 or str(parsed_id) != value:
        raise ValueError("invalid run id")
    return value


def validate_workflow_state(state: WorkflowState | dict[str, object]) -> None:
    ensure_json_safe(state)
    json.dumps(state, allow_nan=False, separators=(",", ":"))


def validate_workflow_input(value: object) -> dict[str, JsonValue]:
    validated = WorkflowInput.model_validate(value)
    return validated.model_dump(mode="json")


def validate_approval_decision(value: object) -> dict[str, JsonValue]:
    validated = ApprovalDecision.model_validate(value)
    return validated.model_dump(mode="json", exclude_none=True)
