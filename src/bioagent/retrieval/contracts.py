"""Strict contracts shared by data-catalog and future knowledge retrieval."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RetrievalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


def _clean(value: str, *, optional: bool = False) -> str | None:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("control characters are not allowed")
    normalized = value.strip()
    if optional and not normalized:
        return None
    return normalized


class DatasetSearchQuery(RetrievalRecord):
    """Business-only search input; it carries no URL or Entrez expression."""

    text: str = Field(min_length=2, max_length=256, strict=True)
    provider: Literal["geo"] = "geo"
    organism: str | None = Field(default=None, max_length=128, strict=True)
    tissue: str | None = Field(default=None, max_length=128, strict=True)
    technology: str | None = Field(default=None, max_length=128, strict=True)
    page_token: str | None = Field(default=None, max_length=128, strict=True)
    page_size: int = Field(default=10, ge=1, le=20, strict=True)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = _clean(value)
        assert isinstance(cleaned, str)
        if not 2 <= len(cleaned) <= 256:
            raise ValueError("text must contain 2 to 256 characters after trimming")
        return cleaned

    @field_validator("organism", "tissue", "technology", "page_token")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return None if value is None else _clean(value, optional=True)

    @property
    def query_hash(self) -> str:
        """Hash stable semantic fields, never a server-issued navigation token."""
        payload = self.model_dump(mode="json", exclude={"page_token"})
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        return sha256(encoded).hexdigest()


class AnalysisReadiness(StrEnum):
    NEEDS_INSPECTION = "NEEDS_INSPECTION"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class EvidenceRef(RetrievalRecord):
    provider: Literal["geo"]
    source_id: str = Field(pattern=r"^GSE[1-9][0-9]*$", strict=True)
    source_uri: str = Field(min_length=1, max_length=2048, strict=True)
    retrieved_at: datetime
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)

    @model_validator(mode="after")
    def official_geo_uri(self) -> EvidenceRef:
        expected = f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={self.source_id}"
        if self.source_uri != expected:
            raise ValueError("source_uri must be the backend-generated NCBI GEO URI")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return self

    @classmethod
    def fixture(cls, provider: Literal["geo"], source_id: str) -> EvidenceRef:
        """Small deterministic-shape helper for local fixtures, never production I/O."""
        source_uri = f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={source_id}"
        return cls(
            provider=provider,
            source_id=source_id,
            source_uri=source_uri,
            retrieved_at=datetime.now(UTC),
            content_sha256=sha256(source_id.encode("ascii")).hexdigest(),
        )


class DatasetSearchHit(RetrievalRecord):
    provider: Literal["geo"]
    source_id: str = Field(pattern=r"^GSE[1-9][0-9]*$", strict=True)
    title: str = Field(min_length=1, max_length=4096, strict=True)
    summary: str | None = Field(default=None, max_length=32 * 1024, strict=True)
    organisms: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    sample_count: int | None = Field(default=None, ge=0, strict=True)
    published_at: str | None = Field(default=None, max_length=64, strict=True)
    source_uri: str = Field(min_length=1, max_length=2048, strict=True)
    evidence: EvidenceRef
    analysis_readiness: AnalysisReadiness = AnalysisReadiness.NEEDS_INSPECTION

    @model_validator(mode="after")
    def evidence_matches_hit(self) -> DatasetSearchHit:
        if self.evidence.source_id != self.source_id or self.evidence.source_uri != self.source_uri:
            raise ValueError("hit and evidence must reference the same GEO accession")
        return self


class DatasetSearchPage(RetrievalRecord):
    items: tuple[DatasetSearchHit, ...]
    next_page_token: str | None = Field(default=None, max_length=128, strict=True)
    total: int = Field(ge=0, le=100, strict=True)


class DatasetCatalogProvider(Protocol):
    def search(self, query: DatasetSearchQuery) -> DatasetSearchPage: ...


__all__ = [
    "AnalysisReadiness",
    "DatasetCatalogProvider",
    "DatasetSearchHit",
    "DatasetSearchPage",
    "DatasetSearchQuery",
    "EvidenceRef",
]
