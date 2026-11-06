"""GEO discovery/import HTTP boundary; it accepts IDs, never file URLs or paths."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from bioagent.api.dependencies import DependencyContainer, get_dependencies
from bioagent.geo.client import normalize_accession
from bioagent.geo.models import SourceSelection
from bioagent.geo.service import GeoServiceError

router = APIRouter(prefix="/api/v1/geo")
Deps = Annotated[DependencyContainer, Depends(get_dependencies)]


class SourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accession: str = Field(min_length=1, max_length=32)


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: UUID
    revision: int = Field(ge=1, strict=True)


@router.post("/sources", status_code=status.HTTP_202_ACCEPTED)
def create_source(payload: SourceRequest, deps: Deps) -> dict[str, object]:
    try:
        accession = normalize_accession(payload.accession)
        conversation_id, turn_id = deps.geo_api_owner()
        return _public_source(
            deps.geo_service.create_source(
                accession, conversation_id=conversation_id, turn_id=turn_id
            )
        )
    except GeoServiceError as error:
        raise _http_error(error) from error
    except ValueError as error:
        raise _http_error(GeoServiceError("GEO_ACCESSION_INVALID")) from error


@router.get("/sources/{source_id}")
def get_source(source_id: UUID, deps: Deps) -> dict[str, object]:
    try:
        return _public_source(deps.geo_service.get_source(source_id))
    except GeoServiceError as error:
        raise _http_error(error) from error


@router.post("/sources/{source_id}/imports", status_code=status.HTTP_202_ACCEPTED)
def create_import(source_id: UUID, payload: ImportRequest, deps: Deps) -> dict[str, object]:
    try:
        imported = deps.geo_service.request_import(
            source_id, payload.candidate_id, payload.revision
        )
        return _public_import(imported)
    except GeoServiceError as error:
        raise _http_error(error) from error


@router.get("/imports/{import_id}")
def get_import(import_id: UUID, deps: Deps) -> dict[str, object]:
    try:
        return _public_import(deps.geo_service.get_import(import_id))
    except GeoServiceError as error:
        raise _http_error(error) from error


@router.post("/imports/{import_id}/selection", status_code=status.HTTP_202_ACCEPTED)
def select_mapping(import_id: UUID, payload: SourceSelection, deps: Deps) -> dict[str, object]:
    try:
        return _public_import(deps.geo_service.submit_selection(import_id, payload))
    except GeoServiceError as error:
        raise _http_error(error) from error


@router.post("/imports/{import_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
def cancel_import(import_id: UUID, deps: Deps) -> dict[str, object]:
    try:
        return _public_import(deps.geo_service.cancel(import_id))
    except GeoServiceError as error:
        raise _http_error(error) from error


def _public_source(value: dict[str, object]) -> dict[str, object]:
    return dict(value)


def _public_import(value: dict[str, object]) -> dict[str, object]:
    # Temporary paths belong to the service only and must not become an API capability.
    return {key: item for key, item in value.items() if key not in {"raw_path", "selection"}}


def _http_error(error: GeoServiceError) -> Exception:
    from fastapi import HTTPException

    codes = {
        "GEO_SOURCE_NOT_FOUND": 404,
        "GEO_IMPORT_NOT_FOUND": 404,
        "GEO_CANDIDATE_NOT_FOUND": 404,
        "SOURCE_SELECTION_CONFLICT": 409,
        "SOURCE_CHANGED": 409,
        "GEO_SOURCE_NOT_READY": 409,
        "GEO_QUEUE_FULL": 429,
    }
    return HTTPException(status_code=codes.get(error.code, 422), detail={"code": error.code})
