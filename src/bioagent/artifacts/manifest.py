import json
from collections.abc import Iterator, Mapping
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from bioagent.artifacts.paths import validate_artifact_relative_path
from bioagent.domain.plans import Comparison
from bioagent.domain.qc import QCReport
from bioagent.domain.runs import RunStatus

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class _FrozenStringMapping(Mapping[str, str]):
    __slots__ = ("_items",)

    def __init__(self, value: Mapping[str, str]) -> None:
        self._items = tuple(value.items())

    def __getitem__(self, key: str) -> str:
        for item_key, item_value in self._items:
            if item_key == key:
                return item_value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)


class _FrozenValidatedModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        copied = super().model_copy(update=update, deep=deep)
        payload = {
            field_name: getattr(copied, field_name)
            for field_name in type(self).model_fields
        }
        return type(self).model_validate(payload)


class ArtifactRecord(_FrozenValidatedModel):
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("relative_path")
    @classmethod
    def relative_path_must_be_safe(cls, value: str) -> str:
        validate_artifact_relative_path(value)
        return value


class _ManifestComparison(_FrozenValidatedModel):
    factor: str = Field(min_length=1, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    numerator: str = Field(min_length=1)
    denominator: str = Field(min_length=1)

    @model_validator(mode="after")
    def levels_must_differ(self) -> Self:
        if self.numerator == self.denominator:
            raise ValueError("numerator and denominator must differ")
        return self


class ApprovalRecord(_FrozenValidatedModel):
    decision: Literal["APPROVED", "MODIFIED", "REJECTED"]
    actor: str = Field(min_length=1)
    decided_at: datetime
    plan_revision: int = Field(ge=1)
    plan_hash: str = Field(pattern=_SHA256_PATTERN)


class AttemptRecord(_FrozenValidatedModel):
    attempt_id: UUID
    started_at: datetime
    ended_at: datetime | None = None
    status: RunStatus
    qc: QCReport | None = None

    @model_validator(mode="after")
    def end_must_not_precede_start(self) -> Self:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("attempt ended_at must not precede started_at")
        return self


class RunManifest(_FrozenValidatedModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID
    dataset_id: UUID
    attempt_id: UUID
    plan_revision: int = Field(ge=1)
    plan_hash: str = Field(pattern=_SHA256_PATTERN)
    input_hashes: Mapping[str, str]
    tool: str = Field(min_length=1)
    software_versions: Mapping[str, str]
    git_commit: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    comparison: _ManifestComparison
    alpha: float = Field(gt=0, lt=1)
    lfc_shrink: bool
    random_seed: int = Field(ge=0)
    started_at: datetime
    ended_at: datetime | None = None
    status: RunStatus
    qc: QCReport
    approvals: tuple[ApprovalRecord, ...] = Field(min_length=1)
    attempts: tuple[AttemptRecord, ...] = Field(min_length=1)
    artifacts: tuple[ArtifactRecord, ...] = Field(default_factory=tuple)

    @field_validator("input_hashes")
    @classmethod
    def input_hashes_must_cover_dataset_files(
        cls,
        value: Mapping[str, str],
    ) -> Mapping[str, str]:
        if not {"counts", "metadata"}.issubset(value):
            raise ValueError("input_hashes must include counts and metadata")
        if any(
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for digest in value.values()
        ):
            raise ValueError("input_hashes must contain SHA-256 digests")
        return _FrozenStringMapping(value)

    @field_validator("software_versions")
    @classmethod
    def software_versions_must_include_r_and_deseq2(
        cls,
        value: Mapping[str, str],
    ) -> Mapping[str, str]:
        if not {"r", "deseq2"}.issubset(value):
            raise ValueError("software_versions must include r and deseq2")
        if any(not name or not version for name, version in value.items()):
            raise ValueError("software_versions entries must be non-empty")
        return _FrozenStringMapping(value)

    @field_validator("comparison", mode="before")
    @classmethod
    def comparison_must_be_manifest_owned(cls, value: object) -> object:
        if isinstance(value, Comparison):
            return value.model_dump(mode="python")
        return value

    @field_serializer("input_hashes", "software_versions")
    def serialize_string_mapping(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)

    @model_validator(mode="after")
    def provenance_references_must_be_consistent(self) -> Self:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("manifest ended_at must not precede started_at")

        matching_attempts = [
            attempt for attempt in self.attempts if attempt.attempt_id == self.attempt_id
        ]
        if len(matching_attempts) != 1:
            raise ValueError("attempt_id must reference exactly one attempt")
        current_attempt = matching_attempts[0]
        if self.status != current_attempt.status:
            raise ValueError("manifest status must match current attempt")
        if self.qc != current_attempt.qc:
            raise ValueError("manifest qc must match current attempt")
        if self.ended_at != current_attempt.ended_at:
            raise ValueError("manifest ended_at must match current attempt")

        matching_approvals = [
            approval
            for approval in self.approvals
            if approval.decision == "APPROVED"
            and approval.plan_revision == self.plan_revision
            and approval.plan_hash == self.plan_hash
        ]
        if not matching_approvals:
            raise ValueError("manifest plan must have a matching approval")
        return self


def write_manifest_atomic(path: Path, manifest: RunManifest) -> str:
    payload = {
        field_name: getattr(manifest, field_name)
        for field_name in RunManifest.model_fields
    }
    validated_manifest = RunManifest.model_validate(payload)
    content = (
        json.dumps(
            validated_manifest.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode()
    temporary_path = path.with_name(f"{path.name}.tmp")
    try:
        temporary_path.write_bytes(content)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return sha256(content).hexdigest()
