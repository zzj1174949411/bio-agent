"""Wiki UUID API under existing local owner, Host, Origin and CSRF middleware."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import FileResponse, Response

from bioagent.api.dependencies import DependencyContainer, get_dependencies
from bioagent.knowledge.preview import render_page
from bioagent.knowledge.store import KnowledgeError
from bioagent.knowledge.wiki_models import (
    BuildRequest,
    Citation,
    PageList,
    Preflight,
    WikiJob,
    WikiPage,
)

router = APIRouter(prefix="/api/v1/knowledge/bases/{base_id}/wiki", tags=["Literature Wiki"])
Deps = Annotated[DependencyContainer, Depends(get_dependencies)]


@router.post("/preflight", response_model=Preflight)
def preflight(base_id: UUID, payload: BuildRequest, deps: Deps) -> Preflight:
    return deps.wiki_service.preflight(str(base_id), payload)


@router.post("/build", status_code=202, response_model=WikiJob)
async def build(base_id: UUID, payload: BuildRequest, deps: Deps) -> WikiJob:
    return await deps.wiki_service.submit(str(base_id), payload)


@router.get("/status", response_model=WikiJob | None)
def status(base_id: UUID, deps: Deps) -> WikiJob | None:
    return deps.wiki_service.catalog.latest(str(base_id))


@router.get("/jobs/{job_id}", response_model=WikiJob)
def job(base_id: UUID, job_id: UUID, deps: Deps) -> WikiJob:
    return deps.wiki_service.get(str(base_id), str(job_id))


@router.post("/jobs/{job_id}/cancel", response_model=WikiJob)
async def cancel(base_id: UUID, job_id: UUID, deps: Deps) -> WikiJob:
    return await deps.wiki_service.cancel(str(base_id), str(job_id))


@router.post("/jobs/{job_id}/retry", status_code=202, response_model=WikiJob)
async def retry(base_id: UUID, job_id: UUID, payload: BuildRequest, deps: Deps) -> WikiJob:
    return await deps.wiki_service.retry(str(base_id), str(job_id), payload)


@router.get("/pages", response_model=PageList)
def pages(base_id: UUID, deps: Deps) -> PageList:
    return deps.wiki_service.pages(str(base_id))


@router.get("/pages/{page_id}", response_model=WikiPage)
def page(base_id: UUID, page_id: UUID, deps: Deps) -> WikiPage:
    return deps.wiki_service.page(str(base_id), str(page_id))


@router.get("/pages/{page_id}/export")
def export(base_id: UUID, page_id: UUID, deps: Deps) -> Response:
    return Response(
        deps.wiki_service.export(str(base_id), str(page_id)),
        media_type="text/markdown",
        headers={
            "Content-Disposition": 'attachment; filename="wiki-page.md"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


def _citation(base: UUID, page_id: UUID, chunk: UUID, deps: DependencyContainer) -> Citation:
    page = deps.wiki_service.page(str(base), str(page_id))
    found = next((c for s in page.statements for c in s.citations if c.chunk_id == chunk), None)
    if found is None:
        raise KnowledgeError("WIKI_CITATION_INVALID")
    deps.wiki_service._validate_citation(found)
    return found


@router.get("/pages/{page_id}/evidence/{chunk_id}")
def evidence(base_id: UUID, page_id: UUID, chunk_id: UUID, deps: Deps) -> dict[str, Any]:
    ref = _citation(base_id, page_id, chunk_id, deps).reference
    parsed = deps.knowledge_service.store.parsed(str(ref.document_id), str(ref.parse_revision))
    chunk = deps.retrieval_engine.validate(ref)
    return {
        "element": next(e for e in parsed["elements"] if e["id"] == ref.element_id),
        "warnings": parsed["warnings"],
        "page": ref.page,
        "navigation_anchor_only": bool(chunk.sources),
        "source_spans": [s.model_dump(mode="json") for s in chunk.sources],
        "elements": [
            e for e in parsed["elements"] if e["id"] in {s.element_id for s in chunk.sources}
        ],
    }


@router.get("/pages/{page_id}/evidence/{chunk_id}/{resource}")
def resource(
    base_id: UUID, page_id: UUID, chunk_id: UUID, resource: Literal["pdf", "page"], deps: Deps
) -> Response:
    ref = _citation(base_id, page_id, chunk_id, deps).reference
    store = deps.knowledge_service.store
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    }
    if resource == "page":
        data = render_page(store.original(str(ref.document_id)), ref.page)
        _citation(base_id, page_id, chunk_id, deps)
        return Response(data, media_type="image/png", headers=headers)
    return FileResponse(
        store.original(str(ref.document_id)),
        media_type="application/pdf",
        filename="document.pdf",
        content_disposition_type="attachment",
        headers=headers,
    )
