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


class GeoLookupAction(_Action):
    """A model may name one accession, never a URL or download destination."""

    kind: Literal["geo_lookup"]
    accession: str = Field(pattern=r"^GSE[1-9][0-9]*$", max_length=32)


class DatasetSearchAction(_Action):
    """Search GEO using business filters only; discovery remains user-selected."""

    kind: Literal["dataset_search"]
    text: str = Field(min_length=2, max_length=256, strict=True)
    organism: str | None = Field(default=None, max_length=128, strict=True)
    tissue: str | None = Field(default=None, max_length=128, strict=True)
    technology: str | None = Field(default=None, max_length=128, strict=True)


class GeoImportAction(_Action):
    """Suggest an already-discovered candidate; the browser confirms the download."""

    kind: Literal["geo_import"]
    source_id: UUID
    candidate_id: UUID
    revision: int = Field(ge=1, strict=True)


class McpCallAction(_Action):
    """A namespaced MCP call; arguments remain untrusted JSON data."""

    kind: Literal["mcp_call"]
    tool_name: str = Field(min_length=1, max_length=512)
    arguments: dict[str, object] = Field(default_factory=dict)


class LoadSkillAction(_Action):
    """Load one explicitly enabled Skill snapshot into the current turn."""

    kind: Literal["load_skill"]
    skill_id: UUID


AssistantAction = Annotated[
    AnswerAction
    | ClarifyAction
    | PlanAnalysisAction
    | GeoLookupAction
    | DatasetSearchAction
    | GeoImportAction
    | McpCallAction
    | LoadSkillAction,
    Field(discriminator="kind"),
]
_ACTION_ADAPTER: TypeAdapter[AssistantAction] = TypeAdapter(AssistantAction)


def parse_action(
    value: object,
) -> (
    AnswerAction
    | ClarifyAction
    | PlanAnalysisAction
    | GeoLookupAction
    | DatasetSearchAction
    | GeoImportAction
    | McpCallAction
    | LoadSkillAction
):
    return _ACTION_ADAPTER.validate_python(value)
