"""Public model configuration and credential-free snapshots."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator

from bioagent.workbench.models import TurnModelSnapshot

# One snapshot contract for persisted turns and profiles; no profile CRUD in workbench.
ModelSnapshot = TurnModelSnapshot


class ModelError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ModelProfile(ModelSnapshot):
    id: UUID
    label: str = Field(min_length=1, max_length=80)
    credential_ref: str | None = Field(default=None, repr=False)
    read_only: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("label", "model")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("PROFILE_INVALID")
        return value

    @field_validator("base_url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        if any(char.isspace() or ord(char) < 32 for char in value):
            raise ValueError("PROFILE_INVALID")
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
        ):
            raise ValueError("PROFILE_INVALID")
        _ = url.port  # Also reject malformed or out-of-range ports.
        return value.rstrip("/")

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        payload = self.model_dump()
        payload.update(update or {})
        return type(self).model_validate(payload)

    def snapshot(self) -> ModelSnapshot:
        return ModelSnapshot.model_validate(
            {name: getattr(self, name) for name in ModelSnapshot.model_fields}
        )

    def public_dict(self, *, credential_configured: bool) -> dict[str, object]:
        return {
            "id": str(self.id),
            "label": self.label,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "structured_method": self.structured_method,
            "thinking": self.thinking,
            "revision": self.revision,
            "read_only": self.read_only,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "credential_configured": credential_configured,
        }
