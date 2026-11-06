"""Local literature ingestion API: UUIDs and uploaded bytes, never server paths."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import FileResponse, Response

from bioagent.api.dependencies import DependencyContainer, get_dependencies
from bioagent.knowledge.limits import MAX_FILES_PER_REQUEST, MAX_PDF_BYTES, UploadLimits
from bioagent.knowledge.models import (
    BasePage,
    BaseRecord,
    DocumentPage,
    DocumentRecord,
    ErrorResponse,
    ImportPage,
    JobRecord,
    ParsedResponse,
    ReadinessRecord,
)
from bioagent.knowledge.store import KnowledgeError

router = APIRouter(
    prefix="/api/v1/knowledge",
    tags=["Local knowledge ingestion"],
    responses={
        403: {"description": "LOCAL_HOST_REJECTED / LOCAL_ORIGIN_REJECTED / CSRF_TOKEN_REQUIRED"},
        404: {
            "description": "BASE_NOT_FOUND / DOCUMENT_NOT_FOUND / JOB_NOT_FOUND / ASSET_NOT_FOUND"
        },
        409: {"description": "JOB_CONFLICT / REVISION_NOT_PUBLISHED"},
        413: {"description": "PDF_TOO_LARGE / REQUEST_TOO_LARGE"},
        422: {"description": "REQUEST_INVALID / PDF_INVALID / PDF_BATCH_LIMIT / INVALID_ID"},
        503: {"description": "RESOURCE_INTEGRITY_FAILED / PARSE_OUTPUT_INVALID"},
    },
)
for error_response in router.responses.values():
    error_response["model"] = ErrorResponse
Deps = Annotated[DependencyContainer, Depends(get_dependencies)]


class BaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)


@router.get("/limits", response_model=UploadLimits)
def upload_limits() -> UploadLimits:
    return UploadLimits()


@router.get("/readiness", response_model=ReadinessRecord, response_model_exclude_none=True)
def knowledge_readiness(deps: Deps) -> dict[str, Any]:
    return deps.knowledge_service.readiness()


@router.post("/bases", status_code=201, response_model=BaseRecord)
def create_base(payload: BaseRequest, deps: Deps) -> dict[str, Any]:
    return deps.knowledge_service.store.create_base(payload.name)


@router.get("/bases", response_model=BasePage)
def list_bases(deps: Deps) -> dict[str, Any]:
    return {"items": deps.knowledge_service.store.bases()}


@router.get("/bases/{base_id}", response_model=BaseRecord)
def get_base(base_id: UUID, deps: Deps) -> dict[str, Any]:
    return deps.knowledge_service.store.base(str(base_id))


@router.patch("/bases/{base_id}", response_model=BaseRecord)
def rename_base(base_id: UUID, payload: BaseRequest, deps: Deps) -> dict[str, Any]:
    return deps.knowledge_service.store.rename_base(str(base_id), payload.name)


@router.delete("/bases/{base_id}", status_code=204)
def delete_base(base_id: UUID, deps: Deps) -> Response:
    deps.knowledge_service.store.delete_base(str(base_id))
    return Response(status_code=204)


@router.post("/bases/{base_id}/documents", status_code=202, response_model=ImportPage)
async def upload_documents(
    base_id: UUID,
    deps: Deps,
    files: Annotated[list[UploadFile], File()],
) -> dict[str, Any]:
    if not 1 <= len(files) <= MAX_FILES_PER_REQUEST:
        raise KnowledgeError("PDF_BATCH_LIMIT")
    staged = []
    for file in files:
        try:
            content = await file.read(MAX_PDF_BYTES + 1)
        finally:
            await file.close()
        if file.content_type not in {"application/pdf", "application/octet-stream"} or (
            not file.filename
            or not file.filename.lower().endswith(".pdf")
            or not content.startswith(b"%PDF-")
        ):
            raise KnowledgeError("PDF_INVALID")
        if len(content) > MAX_PDF_BYTES:
            raise KnowledgeError("PDF_TOO_LARGE")
        staged.append((file.filename, content))
    store = deps.knowledge_service.store
    return {"items": [store.import_pdf(str(base_id), name, content) for name, content in staged]}


@router.get("/bases/{base_id}/documents", response_model=DocumentPage)
def list_documents(base_id: UUID, deps: Deps) -> dict[str, Any]:
    return {"items": deps.knowledge_service.store.documents(str(base_id))}


@router.get("/documents/{document_id}", response_model=DocumentRecord)
def get_document(document_id: UUID, deps: Deps) -> dict[str, Any]:
    return deps.knowledge_service.store.document(str(document_id))


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: UUID, deps: Deps) -> Response:
    deps.knowledge_service.store.delete_document(str(document_id))
    return Response(status_code=204)


@router.post("/documents/{document_id}/retry", status_code=202, response_model=JobRecord)
def retry_document(document_id: UUID, deps: Deps) -> dict[str, Any]:
    return deps.knowledge_service.store.retry(str(document_id))


@router.get("/jobs/{job_id}", response_model=JobRecord)
def get_job(job_id: UUID, deps: Deps) -> dict[str, Any]:
    return deps.knowledge_service.store.job(str(job_id))


@router.post("/jobs/{job_id}/cancel", response_model=JobRecord)
def cancel_job(job_id: UUID, deps: Deps) -> dict[str, Any]:
    return deps.knowledge_service.store.cancel(str(job_id))


@router.get("/documents/{document_id}/pdf")
def original_pdf(document_id: UUID, deps: Deps) -> FileResponse:
    return FileResponse(
        deps.knowledge_service.store.original(str(document_id)),
        media_type="application/pdf",
        filename="document.pdf",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )


@router.get("/documents/{document_id}/revisions/{revision_id}", response_model=ParsedResponse)
def parsed_document(document_id: UUID, revision_id: UUID, deps: Deps) -> dict[str, Any]:
    return deps.knowledge_service.store.parsed(str(document_id), str(revision_id))


@router.get("/documents/{document_id}/revisions/{revision_id}/assets/{asset_id}")
def document_asset(
    document_id: UUID,
    revision_id: UUID,
    asset_id: UUID,
    deps: Deps,
) -> FileResponse:
    return FileResponse(
        deps.knowledge_service.store.asset(str(document_id), str(revision_id), str(asset_id)),
        media_type="image/png",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )
