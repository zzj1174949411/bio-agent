"""Model settings API; every response is built from an explicit public projection."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from bioagent.api.dependencies import DependencyContainer, get_dependencies
from bioagent.models.adapters import ProbeResult

router = APIRouter()
Dependencies = Annotated[DependencyContainer, Depends(get_dependencies)]


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=80)
    provider: Literal["deepseek", "openai_compatible", "ollama"]
    model: str = Field(min_length=1, max_length=256)
    base_url: str = Field(min_length=1, max_length=2048)
    structured_method: Literal["function_calling", "json_schema"] = "function_calling"
    thinking: Literal["default", "disabled"] = "default"


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    label: str | None = Field(default=None, min_length=1, max_length=80)
    provider: Literal["deepseek", "openai_compatible", "ollama"] | None = None
    model: str | None = Field(default=None, min_length=1, max_length=256)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    structured_method: Literal["function_calling", "json_schema"] | None = None
    thinking: Literal["default", "disabled"] | None = None


class CredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: SecretStr = Field(min_length=1, max_length=8192)


@router.get("/api/v1/workbench/bootstrap")
def bootstrap(request: Request, response: Response) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store"
    return {"csrf_token": request.app.state.csrf_token}


@router.get("/api/v1/model-profiles")
def list_profiles(
    deps: Dependencies,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1024),
) -> dict[str, object]:
    page = deps.model_profiles.list(limit=limit, cursor=cursor)
    return {
        "items": [deps.model_profiles.public(profile) for profile in page.items],
        "next_cursor": page.next_cursor,
    }


@router.post("/api/v1/model-profiles", status_code=201)
def create_profile(payload: ProfileCreate, deps: Dependencies) -> dict[str, object]:
    return deps.model_profiles.public(deps.model_profiles.create(**payload.model_dump()))


@router.patch("/api/v1/model-profiles/{identity}")
def update_profile(identity: UUID, payload: ProfileUpdate, deps: Dependencies) -> dict[str, object]:
    changes = payload.model_dump(exclude={"expected_revision"}, exclude_unset=True)
    return deps.model_profiles.public(
        deps.model_profiles.update(identity, expected_revision=payload.expected_revision, **changes)
    )


@router.delete("/api/v1/model-profiles/{identity}", status_code=204)
def delete_profile(
    identity: UUID, deps: Dependencies, expected_revision: int = Query(ge=1)
) -> Response:
    deps.model_profiles.delete(identity, expected_revision=expected_revision)
    return Response(status_code=204)


@router.put("/api/v1/model-profiles/{identity}/credential")
def set_credential(
    identity: UUID, payload: CredentialInput, deps: Dependencies
) -> dict[str, object]:
    return deps.model_profiles.public(deps.model_profiles.set_credential(identity, payload.key))


@router.delete("/api/v1/model-profiles/{identity}/credential")
def delete_credential(identity: UUID, deps: Dependencies) -> dict[str, object]:
    return deps.model_profiles.public(deps.model_profiles.delete_credential(identity))


@router.post("/api/v1/model-profiles/{identity}/test")
async def test_profile(identity: UUID, deps: Dependencies) -> ProbeResult:
    return await deps.model_adapter.probe(identity)
