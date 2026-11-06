"""Persisted workbench records; no model clients or analysis execution here."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

Title = Annotated[str, Field(min_length=1, max_length=200)]
EventKind = Literal[
    "turn.started",
    "message.delta",
    "message.completed",
    "action.started",
    "action.completed",
    "action.failed",
    "input.required",
    "run.updated",
    "geo.source",
    "geo.import_suggested",
    "geo.updated",
    "geo.search.updated",
    "geo.search.selected",
    "turn.completed",
    "turn.failed",
    "turn.cancelled",
    "knowledge.updated",
]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class TimedRecord(Record):
    created_at: datetime
    updated_at: datetime


class Project(TimedRecord):
    id: UUID
    title: Title
    archived: bool = False

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value


class Conversation(Project):
    project_id: UUID
    selected_profile_id: UUID | None = None
    geo_source_id: UUID | None = None
    geo_search_id: UUID | None = None
    selected_knowledge_base_ids: tuple[UUID, ...] = Field(default=(), max_length=16)


class TurnStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_USER = "WAITING_USER"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TurnModelSnapshot(Record):
    """Only non-credential execution settings; profile management belongs to task 17."""

    provider: Literal["deepseek", "openai_compatible", "ollama"]
    model: str = Field(min_length=1)
    base_url: str = Field(min_length=1, max_length=2048)
    revision: int = Field(ge=1)
    structured_method: Literal["function_calling", "json_schema"]
    thinking: str = Field(min_length=1)


class WorkbenchError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PendingInput(Record):
    request_id: UUID
    revision: int = Field(ge=1)
    question: str = Field(min_length=1, max_length=4096)


class Turn(TimedRecord):
    id: UUID
    conversation_id: UUID
    client_request_id: UUID
    status: TurnStatus = TurnStatus.QUEUED
    model_snapshot: TurnModelSnapshot | None = None
    run_id: UUID | None = None
    error_code: str | None = None
    profile_id: UUID | None = None
    requested_profile_id: UUID | None = None
    cancel_requested: bool = False
    input_revision: int = 0
    pending_input: PendingInput | None = None
    action_count: int = Field(default=0, ge=0, le=8)
    active_seconds: float = Field(default=0.0, ge=0.0, le=120.0)
    pending_tool_call: dict[str, JsonValue] | None = None
    knowledge_base_ids: tuple[UUID, ...] = ()
    knowledge_revisions: tuple[UUID, ...] = ()
    knowledge_ask_id: UUID | None = None


class Message(TimedRecord):
    id: UUID
    conversation_id: UUID
    turn_id: UUID
    role: Literal["user", "assistant"]
    content: str
    dataset_ids: tuple[UUID, ...] = ()
    partial: bool = False
    knowledge_ask_id: UUID | None = None
    knowledge_base_ids: tuple[UUID, ...] = ()

    @field_validator("content")
    @classmethod
    def bounded_content(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 16 * 1024:
            raise ValueError("MESSAGE_TOO_LARGE")
        return value


class Event(TimedRecord):
    conversation_id: UUID
    seq: int = Field(ge=1)
    turn_id: UUID
    kind: EventKind
    payload: dict[str, JsonValue]


class Page[T](Record):
    items: tuple[T, ...]
    next_cursor: str | None = None
