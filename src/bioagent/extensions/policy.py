"""Local, deterministic policy and JSON-Schema validation for extension tools."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from enum import StrEnum
from hashlib import sha256
from typing import Any

from jsonschema import Draft202012Validator, ValidationError  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field


class ExtensionError(ValueError):
    """Stable public error code; callers must not expose underlying exception text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ToolPolicy(StrEnum):
    DENY = "DENY"
    CONFIRM = "CONFIRM"
    ALLOW_READ = "ALLOW_READ"


class ToolDescriptor(BaseModel):
    """A namespaced MCP tool and the capability revision it is authorised under."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    qualified_name: str = Field(min_length=1, max_length=512)
    server_id: str = Field(min_length=1, max_length=100)
    tool_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] = Field(default_factory=dict)
    schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy: ToolPolicy = ToolPolicy.CONFIRM
    connection_revision: int = Field(ge=1)
    capability_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ExtensionError("SCHEMA_INVALID") from exc


def _reject_remote_refs(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "$ref" and isinstance(child, str) and not child.startswith("#"):
                raise ExtensionError("SCHEMA_REMOTE_REF")
            _reject_remote_refs(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_remote_refs(child)


def normalize_schema(schema: Mapping[str, object] | None) -> dict[str, object]:
    if schema is None:
        return {}
    if not isinstance(schema, Mapping):
        raise ExtensionError("SCHEMA_INVALID")
    normalized = json.loads(canonical_json(dict(schema)))
    if not isinstance(normalized, dict):
        raise ExtensionError("SCHEMA_INVALID")
    if len(canonical_json(normalized).encode("utf-8")) > 256 * 1024:
        raise ExtensionError("SCHEMA_TOO_LARGE")
    _reject_remote_refs(normalized)
    try:
        Draft202012Validator.check_schema(normalized)
    except Exception as exc:
        raise ExtensionError("SCHEMA_INVALID") from exc
    return normalized


def schema_hash(schema: Mapping[str, object] | None) -> str:
    normalized = normalize_schema(schema)
    return sha256(canonical_json(normalized).encode("utf-8")).hexdigest()


def arguments_hash(arguments: Mapping[str, object]) -> str:
    try:
        return sha256(canonical_json(dict(arguments)).encode("utf-8")).hexdigest()
    except ExtensionError as exc:
        raise ExtensionError("ARGUMENTS_INVALID") from exc


def capability_revision(schema_digest: str, connection_revision: int, policy: ToolPolicy) -> str:
    payload = {
        "schema_hash": schema_digest,
        "connection_revision": connection_revision,
        "policy": policy.value,
    }
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def initial_policy(annotations: Mapping[str, object] | None = None) -> ToolPolicy:
    """MCP annotations are display metadata only; every newly discovered tool confirms."""

    return ToolPolicy.CONFIRM


def qualified_name(server_id: object, tool_name: object) -> str:
    if not isinstance(server_id, str) or not isinstance(tool_name, str):
        raise ExtensionError("TOOL_NAME_INVALID")
    if (
        not server_id.strip()
        or not tool_name.strip()
        or _CONTROL.search(server_id)
        or _CONTROL.search(tool_name)
    ):
        raise ExtensionError("TOOL_NAME_INVALID")
    result = f"mcp.{server_id}.{tool_name}"
    if result == "analysis.approve" or len(result) > 512:
        raise ExtensionError("TOOL_NAME_COLLISION")
    return result


def validate_instance(
    schema: Mapping[str, object] | None, value: object, *, output: bool = False
) -> None:
    normalized = normalize_schema(schema)
    try:
        Draft202012Validator(normalized).validate(value)
    except ValidationError as exc:
        raise ExtensionError("TOOL_OUTPUT_INVALID" if output else "TOOL_ARGUMENTS_INVALID") from exc
