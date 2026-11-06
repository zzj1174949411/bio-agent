"""Project/chat HTTP API; streamed events are durable, not workflow commands."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import StreamingResponse

from bioagent.api.dependencies import DependencyContainer, get_dependencies
from bioagent.workbench.events import event_cursor, stream_events
from bioagent.workbench.models import Conversation, Message, Page, Project, Turn, WorkbenchError

router = APIRouter(prefix="/api/v1/workbench")
Deps = Annotated[DependencyContainer, Depends(get_dependencies)]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=1024)]


class CreateProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)


class CreateConversation(CreateProject):
    project_id: UUID


class UpdateProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    archived: bool | None = None


class UpdateConversation(UpdateProject):
    selected_profile_id: UUID | None = None


class SubmitTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: UUID
    text: str = Field(min_length=1, max_length=16384)
    dataset_ids: tuple[UUID, ...] = Field(default=(), max_length=20)
    profile_id: UUID | None = None


class InputResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    revision: int = Field(ge=1, strict=True)
    action: Literal["clarify"]
    value: str = Field(min_length=1, max_length=16384)


@router.post("/projects", status_code=201)
def create_project(payload: CreateProject, deps: Deps) -> Project:
    return deps.workbench.create_project(payload.title)


@router.get("/projects")
def list_projects(deps: Deps, limit: Limit = 50, cursor: Cursor = None) -> Page[Project]:
    return deps.workbench.list_projects(limit=limit, cursor=cursor)


@router.patch("/projects/{identity}")
def update_project(identity: UUID, payload: UpdateProject, deps: Deps) -> Project:
    return deps.workbench.update_project(identity, title=payload.title, archived=payload.archived)


@router.post("/conversations", status_code=201)
def create_conversation(payload: CreateConversation, deps: Deps) -> Conversation:
    return deps.workbench.create_conversation(payload.project_id, payload.title)


@router.get("/conversations")
def list_conversations(
    project_id: UUID, deps: Deps, limit: Limit = 50, cursor: Cursor = None
) -> Page[Conversation]:
    return deps.workbench.list_conversations(project_id, limit=limit, cursor=cursor)


@router.patch("/conversations/{identity}")
def update_conversation(identity: UUID, payload: UpdateConversation, deps: Deps) -> Conversation:
    if payload.selected_profile_id is not None:
        deps.model_profiles.get(payload.selected_profile_id)
    return deps.workbench.update_conversation(
        identity,
        title=payload.title,
        archived=payload.archived,
        selected_profile_id=payload.selected_profile_id,
        select_profile="selected_profile_id" in payload.model_fields_set,
    )


@router.get("/conversations/{identity}/messages")
def list_messages(
    identity: UUID, deps: Deps, limit: Limit = 50, cursor: Cursor = None
) -> Page[Message]:
    return deps.workbench.list_messages(identity, limit=limit, cursor=cursor)


@router.post("/conversations/{identity}/turns", status_code=202)
async def submit_turn(identity: UUID, payload: SubmitTurn, deps: Deps) -> Turn:
    for dataset_id in payload.dataset_ids:
        try:
            deps.dataset_repository.paths(str(dataset_id))
        except (ValueError, OSError):
            raise WorkbenchError("DATASET_NOT_FOUND") from None
    return await deps.turn_service.submit(
        identity, payload.client_request_id, payload.text, payload.profile_id, payload.dataset_ids
    )


@router.get("/turns/{identity}")
def get_turn(identity: UUID, deps: Deps) -> Turn:
    return deps.workbench.get_turn(identity)


@router.post("/turns/{identity}/cancel", status_code=202)
async def cancel_turn(identity: UUID, deps: Deps) -> Turn:
    return await deps.turn_service.cancel(identity)


@router.post("/turns/{identity}/responses", status_code=202)
async def respond(identity: UUID, payload: InputResponse, deps: Deps) -> Turn:
    return await deps.turn_service.respond(
        identity, payload.request_id, payload.revision, payload.action, payload.value
    )


@router.get("/conversations/{identity}/events")
async def events(
    identity: UUID, deps: Deps, after: str | None = None, last_event_id: str | None = Header(None)
) -> StreamingResponse:
    cursor = event_cursor(after, last_event_id)
    deps.workbench.get_conversation(identity)
    return StreamingResponse(
        stream_events(deps.workbench, identity, cursor),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
