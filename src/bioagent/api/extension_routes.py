"""User-controlled Skill and MCP configuration API.

Responses intentionally contain metadata and hashes only; secrets are accepted into
the keyring and are never persisted in this API's database or event stream.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from bioagent.api.dependencies import DependencyContainer, _mcp_secret_reference, get_dependencies
from bioagent.extensions.mcp_client import McpClientError, validate_http_endpoint
from bioagent.extensions.models import HttpConfig, McpServerConfig, StdioConfig
from bioagent.extensions.policy import ExtensionError, ToolPolicy
from bioagent.extensions.skills import SkillCatalog, SkillValidationError

router = APIRouter(prefix="/api/v1/extensions")
Deps = Annotated[DependencyContainer, Depends(get_dependencies)]


class SkillRootPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root: str = Field(min_length=1, max_length=4096)


class SkillPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    expected_hash: str | None = Field(default=None, min_length=64, max_length=64)


class StdioPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    executable: str = Field(min_length=1, max_length=4096)
    argv: tuple[str, ...] = ()
    cwd: str = Field(min_length=1, max_length=4096)
    env_refs: dict[str, str] = Field(default_factory=dict)


class HttpPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(min_length=1, max_length=4096)
    header_refs: dict[str, str] = Field(default_factory=dict)


class McpServerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=120)
    transport: Literal["stdio", "http"]
    enabled: bool = True
    stdio: StdioPayload | None = None
    http: HttpPayload | None = None


class McpServerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    label: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    transport: Literal["stdio", "http"] | None = None
    stdio: StdioPayload | None = None
    http: HttpPayload | None = None


class McpCredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str = Field(min_length=1, max_length=256)
    value: SecretStr = Field(min_length=1, max_length=8192)


class ToolPolicyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: ToolPolicy
    expected_capability_revision: str | None = Field(default=None, min_length=64, max_length=64)


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: str = Field(min_length=1, max_length=100)
    decision: Literal["approve", "deny"]
    capability_revision: str = Field(min_length=64, max_length=64)
    arguments_hash: str = Field(min_length=64, max_length=64)


def _public_server(config: McpServerConfig) -> dict[str, object]:
    return config.model_dump(mode="json")


def _public_approval(record: dict[str, object]) -> dict[str, object]:
    return {
        key: record[key]
        for key in (
            "approval_id",
            "call_id",
            "conversation_id",
            "turn_id",
            "qualified_name",
            "server_revision",
            "capability_revision",
            "arguments_hash",
            "expires_at",
            "decision",
            "used_at",
            "revoked_at",
        )
        if key in record
    }


@router.get("/skill-roots")
def get_skill_root(deps: Deps) -> dict[str, object]:
    default = str(Path(deps.settings.skill_root).resolve())
    root = str(Path(deps.extension_store.get_skill_root(default)).resolve())
    return {"root": root, "configured": True}


@router.patch("/skill-roots")
def set_skill_root(payload: SkillRootPatch, deps: Deps) -> dict[str, object]:
    path = Path(payload.root)
    if not path.is_absolute():
        raise ExtensionError("SKILL_ROOT_INVALID")
    root = str(path.resolve())
    deps.extension_store.set_skill_root(root)
    return {"root": root, "configured": True}


@router.get("/skills")
def list_skills(deps: Deps) -> dict[str, object]:
    return {
        "items": [record.model_dump(mode="json") for record in deps.extension_store.list_skills()]
    }


@router.post("/skills/rescan")
def rescan_skills(deps: Deps) -> dict[str, object]:
    root = Path(deps.extension_store.get_skill_root(str(Path(deps.settings.skill_root).resolve())))
    scan = SkillCatalog(root, root_id="default").scan()
    records = deps.extension_store.sync(scan.records)
    return {
        "items": [record.model_dump(mode="json") for record in records],
        "errors": [error.model_dump(mode="json") for error in scan.errors],
    }


@router.get("/skills/{identity}")
def get_skill(identity: UUID, deps: Deps) -> dict[str, object]:
    record = deps.extension_store.get_skill(identity)
    result: dict[str, object] = {"record": record.model_dump(mode="json")}
    if record.enabled:
        root = Path(
            deps.extension_store.get_skill_root(str(Path(deps.settings.skill_root).resolve()))
        )
        try:
            snapshot = SkillCatalog(root, root_id=record.root_id).snapshot(
                record, locally_authorized_tools=set()
            )
        except (SkillValidationError, OSError) as exc:
            code = str(exc) if str(exc).startswith("SKILL_") else "SKILL_INVALID"
            raise ExtensionError(code) from exc
        result["snapshot"] = snapshot.model_dump(mode="json")
    return result


@router.patch("/skills/{identity}")
def update_skill(identity: UUID, payload: SkillPatch, deps: Deps) -> dict[str, object]:
    record = deps.extension_store.get_skill(identity)
    if not payload.enabled:
        return {"record": deps.extension_store.disable(identity).model_dump(mode="json")}
    if payload.expected_hash is None:
        raise ExtensionError("SKILL_HASH_REQUIRED")
    root = Path(deps.extension_store.get_skill_root(str(Path(deps.settings.skill_root).resolve())))
    try:
        snapshot = SkillCatalog(root, root_id=record.root_id).snapshot(
            record, locally_authorized_tools=set()
        )
    except (SkillValidationError, OSError) as exc:
        code = str(exc) if str(exc).startswith("SKILL_") else "SKILL_INVALID"
        raise ExtensionError(code) from exc
    return {
        "record": deps.extension_store.enable(
            identity, expected_hash=payload.expected_hash, snapshot=snapshot
        ).model_dump(mode="json")
    }


@router.get("/mcp/servers")
def list_servers(deps: Deps) -> dict[str, object]:
    return {"items": [_public_server(config) for config in deps.extension_store.list_servers()]}


@router.post("/mcp/servers", status_code=201)
def create_server(payload: McpServerCreate, deps: Deps) -> dict[str, object]:
    config = _config_from_create(payload)
    return _public_server(deps.extension_store.save_server(config))


@router.patch("/mcp/servers/{identity}")
def update_server(identity: UUID, payload: McpServerPatch, deps: Deps) -> dict[str, object]:
    current = deps.extension_store.get_server(identity)
    changes = payload.model_dump(exclude={"expected_revision"}, exclude_unset=True)
    transport = changes.get("transport", current.transport)
    stdio = (
        _stdio(changes["stdio"])
        if "stdio" in changes and changes["stdio"] is not None
        else current.stdio
    )
    http = (
        _http(changes["http"])
        if "http" in changes and changes["http"] is not None
        else current.http
    )
    config = McpServerConfig(
        id=identity,
        label=changes.get("label", current.label),
        enabled=changes.get("enabled", current.enabled),
        revision=current.revision + 1,
        transport=transport,
        stdio=stdio,
        http=http,
    )
    return _public_server(
        deps.extension_store.update_server(config, expected_revision=payload.expected_revision)
    )


@router.delete("/mcp/servers/{identity}", status_code=204)
async def delete_server(identity: UUID, deps: Deps) -> Response:
    with suppress(McpClientError):
        await deps.mcp_client.disconnect(str(identity))
    deps.extension_store.disable_server(identity)
    return Response(status_code=204)


@router.put("/mcp/servers/{identity}/credential")
def set_credential(identity: UUID, payload: McpCredentialInput, deps: Deps) -> dict[str, object]:
    deps.extension_store.get_server(identity)
    ref = _mcp_secret_reference(payload.ref)
    try:
        deps.secret_store.set(ref, payload.value)
    except Exception as exc:
        raise ExtensionError("SECRET_STORE_UNAVAILABLE") from exc
    return {"configured": True, "ref": ref}


@router.delete("/mcp/servers/{identity}/credential")
def delete_credential(
    identity: UUID, deps: Deps, ref: str = Query("default", min_length=1, max_length=256)
) -> dict[str, object]:
    ref = _mcp_secret_reference(ref)
    try:
        deps.secret_store.delete(ref)
    except Exception as exc:
        raise ExtensionError("SECRET_STORE_UNAVAILABLE") from exc
    return {"configured": False}


@router.post("/mcp/servers/{identity}/connect")
async def connect_server(identity: UUID, deps: Deps) -> dict[str, object]:
    config = deps.extension_store.get_server(identity)
    if not config.enabled:
        raise ExtensionError("MCP_SERVER_DISABLED")
    try:
        connection = await deps.mcp_client.connect(config)
        await deps.gateway.refresh_server_tools(config)
    except McpClientError as exc:
        raise ExtensionError(exc.code) from exc
    return connection.model_dump(mode="json")


@router.post("/mcp/servers/{identity}/disconnect")
async def disconnect_server(identity: UUID, deps: Deps) -> dict[str, object]:
    try:
        await deps.mcp_client.disconnect(str(identity))
    except McpClientError as exc:
        if exc.code != "MCP_NOT_CONNECTED":
            raise ExtensionError(exc.code) from exc
    return {"server_id": str(identity), "connected": False}


@router.get("/tools")
def list_tools(deps: Deps) -> dict[str, object]:
    return {"items": [tool.model_dump(mode="json") for tool in deps.gateway.list_tools()]}


@router.get("/tools/available")
def list_available_tools(deps: Deps) -> dict[str, object]:
    """Expose the current model-visible capability snapshot without DENY tools."""

    return {
        "items": [tool.model_dump(mode="json") for tool in deps.gateway.available_tools()]
    }


@router.patch("/tools/{qualified_tool_name:path}")
def update_tool_policy(
    qualified_tool_name: str, payload: ToolPolicyPatch, deps: Deps
) -> dict[str, object]:
    return deps.gateway.set_policy(
        qualified_tool_name,
        payload.policy,
        expected_capability_revision=payload.expected_capability_revision,
    ).model_dump(mode="json")


@router.post("/calls/{call_id}/decision")
def decide_call(call_id: str, payload: DecisionInput, deps: Deps) -> dict[str, object]:
    record = deps.gateway.decide_approval(
        call_id=call_id,
        approval_id=payload.approval_id,
        decision=payload.decision,
        capability_revision_value=payload.capability_revision,
        arguments_hash_value=payload.arguments_hash,
    )
    return _public_approval(record)


def _stdio(value: StdioPayload | Mapping[str, object] | None) -> StdioConfig | None:
    if value is None:
        return None
    payload = value if isinstance(value, StdioPayload) else StdioPayload.model_validate(value)
    return StdioConfig(**payload.model_dump())


def _http(value: HttpPayload | Mapping[str, object] | None) -> HttpConfig | None:
    if value is None:
        return None
    if not isinstance(value, HttpPayload):
        value = HttpPayload.model_validate(value)
    endpoint = validate_http_endpoint(value.endpoint)
    return HttpConfig(endpoint=endpoint, header_refs=value.header_refs)


def _config_from_create(payload: McpServerCreate) -> McpServerConfig:
    return McpServerConfig(
        id=uuid4(),
        label=payload.label,
        transport=payload.transport,
        enabled=payload.enabled,
        revision=1,
        stdio=_stdio(payload.stdio),
        http=_http(payload.http),
    )
