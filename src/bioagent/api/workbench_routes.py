"""Project/chat HTTP API; streamed events are durable, not workflow commands."""

from html import escape
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import FileResponse, HTMLResponse, StreamingResponse

from bioagent.api.dependencies import DependencyContainer, get_dependencies
from bioagent.api.knowledge_retrieval_routes import ask_events
from bioagent.api.workbench_owner import ensure_workbench_owner, workbench_owner_hash
from bioagent.knowledge.preview import render_page
from bioagent.knowledge.retrieval_models import AskTask
from bioagent.workbench.events import event_cursor, stream_events
from bioagent.workbench.knowledge import WorkbenchKnowledge
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
    selected_knowledge_base_ids: tuple[UUID, ...] | None = Field(default=None, max_length=16)


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
def create_conversation(
    payload: CreateConversation, request: Request, response: Response, deps: Deps
) -> Conversation:
    conversation = deps.workbench.create_conversation(payload.project_id, payload.title)
    deps.workbench.bind_conversation_owner(
        conversation.id, ensure_workbench_owner(request, response)
    )
    return conversation


@router.get("/conversations")
def list_conversations(
    project_id: UUID, deps: Deps, limit: Limit = 50, cursor: Cursor = None
) -> Page[Conversation]:
    return deps.workbench.list_conversations(project_id, limit=limit, cursor=cursor)


@router.patch("/conversations/{identity}")
def update_conversation(
    identity: UUID, payload: UpdateConversation, request: Request, response: Response, deps: Deps
) -> Conversation:
    if payload.selected_profile_id is not None:
        deps.model_profiles.get(payload.selected_profile_id)
    if "selected_knowledge_base_ids" in payload.model_fields_set:
        deps.workbench.bind_conversation_owner(identity, ensure_workbench_owner(request, response))
        for base in payload.selected_knowledge_base_ids or ():
            deps.knowledge_service.store.base(str(base))
    result = deps.workbench.update_conversation(
        identity,
        title=payload.title,
        archived=payload.archived,
        selected_profile_id=payload.selected_profile_id,
        select_profile="selected_profile_id" in payload.model_fields_set,
    )
    if "selected_knowledge_base_ids" in payload.model_fields_set:
        return deps.workbench.set_knowledge_selection(
            identity, payload.selected_knowledge_base_ids or ()
        )
    return result


def _knowledge(
    conversation_id: UUID, request: Request, deps: DependencyContainer
) -> WorkbenchKnowledge:
    owner = workbench_owner_hash(request)
    if owner is None or not deps.workbench.owns_conversation(conversation_id, owner):
        raise WorkbenchError("KNOWLEDGE_TURN_MISMATCH")
    return WorkbenchKnowledge(deps.workbench, deps.answer_service)


@router.get("/knowledge-guide", response_class=HTMLResponse)
def knowledge_guide() -> HTMLResponse:
    guide = Path(__file__).resolve().parents[3] / "docs" / "knowledge-workbench.md"
    content = (
        guide.read_text(encoding="utf-8")
        if guide.is_file()
        else "uv sync --extra rag --dev\n"
        "See docs/knowledge-ingestion.md and docs/knowledge-retrieval.md"
    )
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'><title>知识库安装与使用</title>"
        "<pre style='white-space:pre-wrap;max-width:70em;margin:2em auto'>"
        + escape(content)
        + "</pre>",
        headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"},
    )


@router.get("/conversations/{conversation_id}/turns/{turn_id}/knowledge")
def knowledge_task(conversation_id: UUID, turn_id: UUID, request: Request, deps: Deps) -> AskTask:
    return _knowledge(conversation_id, request, deps).task(conversation_id, turn_id)


@router.get("/conversations/{conversation_id}/turns/{turn_id}/knowledge/events")
async def knowledge_events(
    conversation_id: UUID,
    turn_id: UUID,
    request: Request,
    deps: Deps,
    after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    task = _knowledge(conversation_id, request, deps).task(conversation_id, turn_id)
    return await ask_events(task.id, deps, request, after)


@router.get("/conversations/{conversation_id}/turns/{turn_id}/evidence/{chunk_id}")
def evidence_preview(
    conversation_id: UUID, turn_id: UUID, chunk_id: UUID, request: Request, deps: Deps
) -> dict[str, object]:
    hit = _knowledge(conversation_id, request, deps).hit(conversation_id, turn_id, chunk_id)
    ref = hit.reference
    parsed = deps.knowledge_service.store.parsed(str(ref.document_id), str(ref.parse_revision))
    element = next(item for item in parsed["elements"] if item["id"] == ref.element_id)
    return {"element": element, "warnings": parsed["warnings"], "page": ref.page}


@router.get("/conversations/{conversation_id}/turns/{turn_id}/evidence/{chunk_id}/{resource}")
def evidence_resource(
    conversation_id: UUID,
    turn_id: UUID,
    chunk_id: UUID,
    resource: Literal["pdf", "image", "page"],
    request: Request,
    deps: Deps,
) -> Response:
    hit = _knowledge(conversation_id, request, deps).hit(conversation_id, turn_id, chunk_id)
    ref = hit.reference
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    }
    if resource == "page":
        data = render_page(deps.knowledge_service.store.original(str(ref.document_id)), ref.page)
        _knowledge(conversation_id, request, deps).hit(conversation_id, turn_id, chunk_id)
        return Response(data, media_type="image/png", headers=headers)
    if resource == "pdf":
        return FileResponse(
            deps.knowledge_service.store.original(str(ref.document_id)),
            media_type="application/pdf",
            filename="document.pdf",
            content_disposition_type="attachment",
            headers=headers,
        )
    if hit.chunk.asset_id is None:
        raise WorkbenchError("EVIDENCE_ASSET_UNAVAILABLE")
    return FileResponse(
        deps.knowledge_service.store.asset(
            str(ref.document_id), str(ref.parse_revision), str(hit.chunk.asset_id)
        ),
        media_type="image/png",
        headers=headers,
    )


@router.get("/conversations/{identity}/messages")
def list_messages(
    identity: UUID, deps: Deps, limit: Limit = 50, cursor: Cursor = None
) -> Page[Message]:
    return deps.workbench.list_messages(identity, limit=limit, cursor=cursor)


@router.post("/conversations/{identity}/turns", status_code=202)
async def submit_turn(
    identity: UUID, payload: SubmitTurn, request: Request, response: Response, deps: Deps
) -> Turn:
    deps.workbench.bind_conversation_owner(identity, ensure_workbench_owner(request, response))
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
