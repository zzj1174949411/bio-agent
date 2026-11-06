"""Validated, immutable data contracts for local Skills."""

from collections.abc import Iterable, Mapping
from pathlib import Path, PureWindowsPath
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_HASH_PATTERN = r"^[0-9a-f]{64}$"


class SkillReferenceSnapshot(BaseModel):
    """Literal content from one resolved local reference file."""

    model_config = ConfigDict(frozen=True)

    relative_path: str = Field(min_length=1, max_length=512)
    content: str
    sha256: str = Field(pattern=_HASH_PATTERN)


class SkillSnapshot(BaseModel):
    """The immutable instruction payload bound to an enabled Skill hash."""

    model_config = ConfigDict(frozen=True)

    skill_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    content: str
    entry_hash: str = Field(pattern=_HASH_PATTERN)
    references: tuple[SkillReferenceSnapshot, ...]
    sha256: str = Field(pattern=_HASH_PATTERN)
    granted_tools: frozenset[str]


class SkillRecord(BaseModel):
    """Directory metadata, without instruction text, safe for model selection."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    root_id: str = Field(min_length=1, max_length=200)
    relative_path: str = Field(min_length=1, max_length=512)
    sha256: str = Field(pattern=_HASH_PATTERN)
    enabled: bool = False
    requested_tools: frozenset[str] | None = None

    @field_validator("name", "description", "root_id", "relative_path")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("SKILL_INVALID")
        return value

    @field_validator("requested_tools", mode="before")
    @classmethod
    def validate_tools(cls, value: object) -> frozenset[str] | None:
        if value is None:
            return None
        if isinstance(value, str) or not isinstance(value, Iterable):
            raise ValueError("SKILL_INVALID")
        tools = frozenset(value)
        if not all(isinstance(tool, str) and tool.strip() for tool in tools):
            raise ValueError("SKILL_INVALID")
        return tools


class SkillScanError(BaseModel):
    """A display-safe validation error for one candidate Skill."""

    model_config = ConfigDict(frozen=True)

    relative_path: str = Field(min_length=1, max_length=512)
    code: str = Field(min_length=1, max_length=100)


class SkillScan(BaseModel):
    """A scan result retains safe records while reporting rejected candidates."""

    model_config = ConfigDict(frozen=True)

    records: tuple[SkillRecord, ...] = ()
    errors: tuple[SkillScanError, ...] = ()


class StdioConfig(BaseModel):
    """User-supplied stdio launch description; values are never shell-expanded."""

    model_config = ConfigDict(frozen=True)

    executable: str = Field(min_length=1, max_length=4096)
    argv: tuple[str, ...] = ()
    cwd: str = Field(min_length=1, max_length=4096)
    env_refs: Mapping[str, str] = Field(default_factory=dict)

    @field_validator("executable", "cwd")
    @classmethod
    def absolute_path(cls, value: str) -> str:
        if "\x00" in value or not (Path(value).is_absolute() or PureWindowsPath(value).drive):
            raise ValueError("MCP_STDIO_INVALID")
        return value

    @field_validator("argv")
    @classmethod
    def safe_argv(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any("\x00" in arg for arg in value):
            raise ValueError("MCP_STDIO_INVALID")
        return value

    @field_validator("env_refs")
    @classmethod
    def safe_env_refs(cls, value: Mapping[str, str]) -> dict[str, str]:
        result = dict(value)
        if any(
            not key or "=" in key or "\x00" in key or not isinstance(ref, str) or not ref.strip()
            for key, ref in result.items()
        ):
            raise ValueError("MCP_STDIO_INVALID")
        return result


class HttpConfig(BaseModel):
    """Streamable HTTP endpoint and references to independently stored headers."""

    model_config = ConfigDict(frozen=True)

    endpoint: str = Field(min_length=1, max_length=4096)
    header_refs: Mapping[str, str] = Field(default_factory=dict)

    @field_validator("header_refs")
    @classmethod
    def safe_header_refs(cls, value: Mapping[str, str]) -> dict[str, str]:
        result = dict(value)
        if any(
            not key or "\x00" in key or not isinstance(ref, str) or not ref.strip()
            for key, ref in result.items()
        ):
            raise ValueError("MCP_HTTP_INVALID")
        return result


class McpServerConfig(BaseModel):
    """Versioned MCP connection configuration, without secret material."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    label: str = Field(min_length=1, max_length=120)
    transport: str = Field(pattern=r"^(stdio|http)$")
    enabled: bool = True
    revision: int = Field(default=1, ge=1)
    stdio: StdioConfig | None = None
    http: HttpConfig | None = None

    @field_validator("label")
    @classmethod
    def nonblank_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("MCP_CONFIG_INVALID")
        return value

    @model_validator(mode="after")
    def matching_transport(self) -> "McpServerConfig":
        if (self.transport == "stdio") != (self.stdio is not None) or (
            self.transport == "http"
        ) != (self.http is not None):
            raise ValueError("MCP_CONFIG_INVALID")
        return self


class McpConnection(BaseModel):
    """Safe connection facts exposed to callers; no endpoint credentials."""

    model_config = ConfigDict(frozen=True)

    server_id: UUID
    revision: int
    configured: bool = True
    protocol_version: str | None = None


class McpTool(BaseModel):
    """Sanitized tool metadata returned by discovery."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    input_schema: dict[str, object] = Field(default_factory=dict)
    output_schema: dict[str, object] | None = None
    annotations: dict[str, object] = Field(default_factory=dict)


class McpCallResult(BaseModel):
    """Bounded, structured representation of one MCP call result."""

    model_config = ConfigDict(frozen=True)

    content: tuple[object, ...] = ()
    structured_content: object | None = None
    is_error: bool = False
