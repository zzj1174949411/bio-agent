"""Immutable, source-attributed GEO discovery records."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GeoRecord(BaseModel):
    """Strict records keep untrusted GEO text as data, not instructions."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class DataKind(StrEnum):
    RAW_COUNTS = "RAW_COUNTS"
    NORMALIZED = "NORMALIZED"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"


class Compression(StrEnum):
    NONE = "NONE"
    GZIP = "GZIP"


class GeoImportStatus(StrEnum):
    """Persistent, non-statistical lifecycle for GEO discovery and import."""

    DISCOVERING = "DISCOVERING"
    AWAITING_SELECTION = "AWAITING_SELECTION"
    DOWNLOADING = "DOWNLOADING"
    AWAITING_MAPPING = "AWAITING_MAPPING"
    VALIDATING = "VALIDATING"
    READY = "READY"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class GeoField(GeoRecord):
    name: str = Field(min_length=1)
    value: str
    origin: str = Field(min_length=1)


class GeoSample(GeoRecord):
    accession: str = Field(pattern=r"^GSM[1-9][0-9]*$")
    title: str | None = None
    organism: str | None = None
    platform: str | None = None
    characteristics: tuple[GeoField, ...] = ()
    fields: tuple[GeoField, ...] = ()


class GeoCandidate(GeoRecord):
    id: UUID
    source_id: UUID
    accession: str = Field(pattern=r"^GSE[1-9][0-9]*$")
    url: str = Field(min_length=1, max_length=4096)
    file_name: str = Field(min_length=1, max_length=1024)
    size_bytes: int | None = Field(default=None, ge=0)
    data_kind: DataKind
    evidence: tuple[str, ...] = Field(min_length=1)
    compression: Compression


class GeoSource(GeoRecord):
    id: UUID
    accession: str = Field(pattern=r"^GSE[1-9][0-9]*$")
    title: str | None = None
    organisms: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    samples: tuple[GeoSample, ...] = ()
    candidates: tuple[GeoCandidate, ...] = ()
    retrieved_at: datetime
    fields: tuple[GeoField, ...] = ()
    warnings: tuple[str, ...] = ()
    error_code: str | None = None
    reasons: tuple[str, ...] = ()

    @property
    def importable_candidates(self) -> tuple[GeoCandidate, ...]:
        return tuple(
            candidate
            for candidate in self.candidates
            if candidate.data_kind in {DataKind.RAW_COUNTS, DataKind.UNKNOWN}
        )


class SourceSelection(GeoRecord):
    """User-confirmed, deterministic projection of a GEO matrix.

    The model deliberately stores both sides of the mapping.  A column name is
    not a sample identifier until the user confirms its mapping, and the
    explicit excluded set makes multi-group subsetting auditable.
    """

    source_id: UUID
    candidate_id: UUID
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_column: str = Field(min_length=1)
    sample_columns: tuple[str, ...] = Field(min_length=1)
    sample_map: dict[str, str]
    groups: dict[str, str]
    group_factor: str = Field(default="condition", min_length=1)
    numerator: str = Field(min_length=1)
    denominator: str = Field(min_length=1)
    revision: int = Field(ge=1)
    confirmed_raw_type: Literal["RAW_COUNTS"] | None = None
    excluded_samples: tuple[str, ...] = ()
    evidence: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_mapping(self) -> "SourceSelection":
        sample_columns = tuple(self.sample_columns)
        if len(set(sample_columns)) != len(sample_columns):
            raise ValueError("sample_columns must be unique")
        if self.feature_column in sample_columns:
            raise ValueError("feature_column cannot also be a sample column")
        if set(self.sample_map) != set(sample_columns):
            raise ValueError("sample_map keys must match sample_columns")
        mapped_samples = tuple(self.sample_map[column] for column in sample_columns)
        if len(set(mapped_samples)) != len(mapped_samples):
            raise ValueError("sample_map must be one-to-one")
        if set(self.groups) != set(mapped_samples):
            raise ValueError("groups must cover every selected sample exactly")
        if self.numerator == self.denominator:
            raise ValueError("numerator and denominator must differ")
        group_levels = set(self.groups.values())
        if group_levels != {self.numerator, self.denominator}:
            raise ValueError("groups must contain exactly numerator and denominator")
        for level in (self.numerator, self.denominator):
            if sum(value == level for value in self.groups.values()) < 2:
                raise ValueError("each comparison group must contain at least two samples")
        if len(set(self.excluded_samples)) != len(self.excluded_samples):
            raise ValueError("excluded_samples must be unique")
        if set(self.excluded_samples) & set(mapped_samples):
            raise ValueError("selected samples cannot also be excluded")
        return self
