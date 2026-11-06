"""Strict, non-executable actions emitted by the conversation model."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnswerAction(_Action):
    kind: Literal["answer"]
    text: str = Field(min_length=1, max_length=16 * 1024)


class ClarifyAction(_Action):
    kind: Literal["clarify"]
    question: str = Field(min_length=1, max_length=4096)


class PlanAnalysisAction(_Action):
    kind: Literal["plan_analysis"]
    dataset_id: UUID
    goal: str = Field(min_length=1, max_length=4000)


AssistantAction = Annotated[
    AnswerAction | ClarifyAction | PlanAnalysisAction,
    Field(discriminator="kind"),
]
_ACTION_ADAPTER: TypeAdapter[AssistantAction] = TypeAdapter(AssistantAction)


def parse_action(value: object) -> AnswerAction | ClarifyAction | PlanAnalysisAction:
    return _ACTION_ADAPTER.validate_python(value)
