"""Local search, index management, evidence and cancellable ask endpoints."""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import StreamingResponse

from bioagent.api.dependencies import DependencyContainer, get_dependencies
from bioagent.knowledge.answers import TERMINAL
from bioagent.knowledge.retrieval_models import (
    AskEvent,
    AskRequest,
    AskTask,
    Chunk,
    IndexJob,
    IndexState,
    LocalEvidence,
    RetrievalErrorResponse,
    RetrievalReadiness,
    SearchRequest,
    SearchResponse,
)

router = APIRouter(
    prefix="/api/v1/knowledge",
    tags=["Local knowledge retrieval"],
    responses={
        403: {"description": "LOCAL_HOST_REJECTED / LOCAL_ORIGIN_REJECTED / CSRF_TOKEN_REQUIRED"},
        404: {
            "description": "BASE_NOT_FOUND / DOCUMENT_NOT_FOUND / INDEX_NOT_FOUND / ASK_NOT_FOUND"
        },
        409: {"description": "INDEX_CONFLICT / INDEX_MODEL_MISMATCH / EVIDENCE_STALE"},
        422: {"description": "REQUEST_INVALID / EVIDENCE_INVALID"},
        429: {"description": "ASK_QUEUE_FULL"},
        503: {
            "description": "RAG_DEPENDENCY_MISSING / RAG_MODELS_MISSING / RAG_MODELS_INVALID / "
            "INDEX_INTEGRITY_FAILED / MODEL_UNAVAILABLE"
        },
    },
)
for response in router.responses.values():
    response["model"] = RetrievalErrorResponse
Deps = Annotated[DependencyContainer, Depends(get_dependencies)]


@router.get("/retrieval/readiness", response_model=RetrievalReadiness)
def retrieval_readiness(deps: Deps) -> RetrievalReadiness:
    return deps.retrieval_engine.readiness()


@router.post("/documents/{document_id}/index", status_code=202, response_model=IndexJob)
def index_document(document_id: UUID, deps: Deps) -> IndexJob:
    return deps.retrieval_engine.enqueue(str(document_id))


@router.get("/documents/{document_id}/index", response_model=IndexState)
def index_state(document_id: UUID, deps: Deps) -> IndexState:
    return deps.retrieval_engine.catalog.state(str(document_id))


@router.get("/index-jobs/{job_id}", response_model=IndexJob)
def index_job(job_id: UUID, deps: Deps) -> IndexJob:
    return deps.retrieval_engine.catalog.job(str(job_id))


@router.post("/index-jobs/{job_id}/cancel", response_model=IndexJob)
def cancel_index(job_id: UUID, deps: Deps) -> IndexJob:
    return deps.retrieval_engine.catalog.cancel(str(job_id))


@router.post("/search", response_model=SearchResponse)
def search(payload: SearchRequest, deps: Deps) -> SearchResponse:
    if payload.mode != "rag":
        bases = [str(key) for key in payload.knowledge_base_ids]
        hybrid = deps.answer_service.hybrid
        return hybrid.retrieve(
            payload.query,
            bases,
            payload.mode,
            deps.retrieval_engine.snapshot(bases),
            hybrid.snapshot(bases),
            24000,
            top_k=payload.top_k,
        ).page
    return deps.retrieval_engine.search(
        payload.query, [str(key) for key in payload.knowledge_base_ids], payload.top_k
    )


@router.post("/evidence/validate", response_model=Chunk)
def validate_evidence(payload: LocalEvidence, deps: Deps) -> Chunk:
    return deps.retrieval_engine.validate(payload)


@router.post("/ask", status_code=202, response_model=AskTask)
async def ask(payload: AskRequest, deps: Deps) -> AskTask:
    return await deps.answer_service.submit(payload)


@router.get("/asks/{ask_id}", response_model=AskTask)
def ask_state(ask_id: UUID, deps: Deps) -> AskTask:
    return deps.answer_service.get(str(ask_id))


@router.post("/asks/{ask_id}/cancel", response_model=AskTask)
async def cancel_ask(ask_id: UUID, deps: Deps) -> AskTask:
    return await deps.answer_service.cancel(str(ask_id))


@router.get(
    "/asks/{ask_id}/events",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {"schema": AskEvent.model_json_schema()}},
            "description": "AskEvent JSON with monotonic sequence; after resumes",
        }
    },
)
async def ask_events(
    ask_id: UUID, deps: Deps, request: Request, after: Annotated[int, Query(ge=0)] = 0
) -> StreamingResponse:
    identity = str(ask_id)
    await asyncio.to_thread(deps.answer_service.get, identity)

    async def stream() -> AsyncIterator[str]:
        cursor = after
        while not await request.is_disconnected():
            events = await asyncio.to_thread(deps.answer_service.events, identity, cursor)
            for event in events:
                cursor = event.sequence
                yield f"id: {cursor}\nevent: {event.kind}\ndata: {event.model_dump_json()}\n\n"
            task = await asyncio.to_thread(deps.answer_service.get, identity)
            if task.status in TERMINAL:
                return
            yield ": keepalive\n\n"
            await asyncio.sleep(0.2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
