"""GEO discovery/import HTTP boundary; it accepts IDs, never file URLs or paths."""

import re
from hashlib import sha256
from secrets import token_urlsafe
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from bioagent.api.dependencies import DependencyContainer, get_dependencies
from bioagent.api.workbench_owner import workbench_owner_hash
from bioagent.geo.client import normalize_accession
from bioagent.geo.models import SourceSelection
from bioagent.geo.search_service import GeoSearchServiceError
from bioagent.geo.service import GeoServiceError
from bioagent.retrieval.contracts import DatasetSearchQuery

router = APIRouter(prefix="/api/v1/geo")
Deps = Annotated[DependencyContainer, Depends(get_dependencies)]
_SEARCH_OWNER_COOKIE = "bioagent_geo_search_owner"
_SEARCH_OWNER_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


class SourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accession: str = Field(min_length=1, max_length=32)


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: UUID
    revision: int = Field(ge=1, strict=True)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=2, max_length=256)
    provider: str = Field(default="geo", pattern="^geo$")
    organism: str | None = Field(default=None, max_length=128)
    tissue: str | None = Field(default=None, max_length=128)
    technology: str | None = Field(default=None, max_length=128)
    page_size: int = Field(default=10, ge=1, le=20)

    def query(self) -> DatasetSearchQuery:
        return DatasetSearchQuery(**self.model_dump())


class SearchPageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    page_token: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1)


class SearchSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    accession: str = Field(min_length=1, max_length=32)
    revision: int = Field(ge=1)


@router.post("/searches", status_code=status.HTTP_202_ACCEPTED)
def create_search(
    payload: SearchRequest, request: Request, response: Response, deps: Deps
) -> dict[str, object]:
    try:
        conversation_id, turn_id = deps.geo_api_owner()
        owner_token = _search_owner(request)
        if owner_token is None:
            owner_token = token_urlsafe(32)
            response.set_cookie(
                _SEARCH_OWNER_COOKIE,
                owner_token,
                httponly=True,
                samesite="strict",
            )
        created = deps.geo_search_service.create(
            payload.query(),
            conversation_id,
            turn_id,
            owner_token_sha256=_owner_hash(owner_token),
        )
        return created
    except (GeoSearchServiceError, GeoServiceError) as error:
        raise _http_error(error) from error


@router.get("/searches/{search_id}")
def get_search(
    search_id: UUID,
    request: Request,
    deps: Deps,
    conversation_id: UUID | None = None,
) -> dict[str, object]:
    try:
        _require_search_owner(search_id, conversation_id, request, deps)
        return deps.geo_search_service.get(search_id)
    except (GeoSearchServiceError, GeoServiceError) as error:
        raise _http_error(error) from error


@router.post("/searches/{search_id}/pages", status_code=status.HTTP_202_ACCEPTED)
def next_search_page(
    search_id: UUID,
    payload: SearchPageRequest,
    request: Request,
    deps: Deps,
    conversation_id: UUID | None = None,
) -> dict[str, object]:
    try:
        _require_search_owner(search_id, conversation_id, request, deps)
        return deps.geo_search_service.next_page(search_id, payload.page_token, payload.revision)
    except (GeoSearchServiceError, GeoServiceError) as error:
        raise _http_error(error) from error


@router.post("/searches/{search_id}/selection", status_code=status.HTTP_202_ACCEPTED)
def select_search_result(
    search_id: UUID,
    payload: SearchSelectionRequest,
    request: Request,
    deps: Deps,
    conversation_id: UUID | None = None,
) -> dict[str, object]:
    try:
        _require_search_owner(search_id, conversation_id, request, deps)
        return deps.geo_search_service.select(
            search_id, normalize_accession(payload.accession), payload.revision
        )
    except (GeoSearchServiceError, GeoServiceError) as error:
        raise _http_error(error) from error
    except ValueError as error:
        raise _http_error(GeoSearchServiceError("GEO_SEARCH_ACCESSION_INVALID")) from error


@router.post("/searches/{search_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
def cancel_search(
    search_id: UUID,
    request: Request,
    deps: Deps,
    conversation_id: UUID | None = None,
) -> dict[str, object]:
    try:
        _require_search_owner(search_id, conversation_id, request, deps)
        return deps.geo_search_service.cancel(search_id)
    except (GeoSearchServiceError, GeoServiceError) as error:
        raise _http_error(error) from error


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


def _require_search_owner(
    search_id: UUID,
    conversation_id: UUID | None,
    request: Request,
    deps: DependencyContainer,
) -> None:
    owner_token = _search_owner(request)
    if _SEARCH_OWNER_COOKIE in request.cookies:
        if owner_token is not None and deps.geo_search_service.owns(
            search_id, _owner_hash(owner_token)
        ):
            return
        raise GeoSearchServiceError("GEO_SEARCH_NOT_FOUND")
    owner_hash = workbench_owner_hash(request)
    if owner_hash is None or conversation_id is None:
        raise GeoSearchServiceError("GEO_SEARCH_NOT_FOUND")
    try:
        conversation = deps.workbench.get_conversation(conversation_id)
    except ValueError as error:
        raise GeoSearchServiceError("GEO_SEARCH_NOT_FOUND") from error
    if conversation.geo_search_id != search_id or not deps.workbench.owns_conversation(
        conversation_id, owner_hash
    ):
        raise GeoSearchServiceError("GEO_SEARCH_NOT_FOUND")
    conversation_search = getattr(deps.geo_search_service, "is_conversation_search", None)
    if callable(conversation_search) and conversation_search(search_id, conversation_id):
        return
    raise GeoSearchServiceError("GEO_SEARCH_NOT_FOUND")


def _owner_hash(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def _search_owner(request: Request) -> str | None:
    token = request.cookies.get(_SEARCH_OWNER_COOKIE)
    if not isinstance(token, str) or _SEARCH_OWNER_TOKEN.fullmatch(token) is None:
        return None
    return token


def _http_error(error: GeoServiceError | GeoSearchServiceError) -> Exception:
    from fastapi import HTTPException

    codes = {
        "GEO_SOURCE_NOT_FOUND": 404,
        "GEO_IMPORT_NOT_FOUND": 404,
        "GEO_CANDIDATE_NOT_FOUND": 404,
        "SOURCE_SELECTION_CONFLICT": 409,
        "SOURCE_CHANGED": 409,
        "GEO_SOURCE_NOT_READY": 409,
        "GEO_QUEUE_FULL": 429,
        "GEO_SEARCH_NOT_FOUND": 404,
        "GEO_SEARCH_ACCESSION_NOT_FOUND": 404,
        "GEO_SEARCH_REVISION_CONFLICT": 409,
        "GEO_SEARCH_NOT_SELECTABLE": 409,
        "GEO_SEARCH_QUEUE_FULL": 429,
        "GEO_SEARCH_SERVICE_CLOSED": 503,
    }
    return HTTPException(status_code=codes.get(error.code, 422), detail={"code": error.code})
