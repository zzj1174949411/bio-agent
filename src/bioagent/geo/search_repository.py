"""Atomic, schema-checked persistence for GEO keyword searches."""

from __future__ import annotations

import json
import os
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from bioagent.geo.models import GeoSearchProvenance
from bioagent.retrieval.contracts import DatasetSearchHit, DatasetSearchQuery


class GeoSearchRepositoryError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class GeoSearchStatus(StrEnum):
    QUEUED = "QUEUED"
    SEARCHING = "SEARCHING"
    AWAITING_SELECTION = "AWAITING_SELECTION"
    SELECTING = "SELECTING"
    SELECTED = "SELECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class GeoSearchRecord(BaseModel):
    """The complete internal snapshot; tokens/context never leave this boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal[1] = 1
    id: UUID
    status: GeoSearchStatus
    revision: int = Field(ge=1, strict=True)
    query: DatasetSearchQuery
    query_hash: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)
    items: tuple[DatasetSearchHit, ...] = ()
    total: int = Field(default=0, ge=0, le=100, strict=True)
    next_page_token: str | None = Field(default=None, max_length=128, strict=True)
    issued_tokens: dict[str, int] = Field(default_factory=dict)
    conversation_id: UUID
    turn_id: UUID
    owner_token_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$", strict=True
    )
    source_id: str | None = Field(default=None, max_length=64, strict=True)
    selected_accession: str | None = Field(
        default=None, pattern=r"^GSE[1-9][0-9]*$", strict=True
    )
    selection_revision: int | None = Field(default=None, ge=1, strict=True)
    error_code: str | None = Field(default=None, max_length=128, strict=True)

    @model_validator(mode="after")
    def verifies_internal_invariants(self) -> GeoSearchRecord:
        if self.query_hash != self.query.query_hash:
            raise ValueError("query hash mismatch")
        if len(self.items) > 100 or len({item.source_id for item in self.items}) != len(self.items):
            raise ValueError("invalid search snapshot")
        has_selection = self.selected_accession is not None or self.selection_revision is not None
        if has_selection and (
            self.selected_accession is None or self.selection_revision is None
        ):
            raise ValueError("incomplete selected search evidence")
        if self.status is GeoSearchStatus.SELECTING:
            if self.source_id is not None or not has_selection:
                raise ValueError("selecting search must bind only selected evidence")
            if self.selection_revision != self.revision:
                raise ValueError("selecting search revision mismatch")
        elif self.status is GeoSearchStatus.SELECTED and self.source_id is None:
            raise ValueError("selected search must have a source ID")
        elif self.status is GeoSearchStatus.SELECTED and has_selection:
            selected_revision = self.selection_revision
            if selected_revision is None or selected_revision + 1 != self.revision:
                raise ValueError("selected search revision mismatch")
        elif self.status is not GeoSearchStatus.SELECTED and self.source_id is not None:
            raise ValueError("only selected search may have a source ID")
        if (
            self.status not in {GeoSearchStatus.SELECTING, GeoSearchStatus.SELECTED}
            and has_selection
        ):
            raise ValueError("only selected searches may retain selected evidence")
        for token, offset in self.issued_tokens.items():
            if not token or len(token) > 128 or offset < 0 or offset >= 100:
                raise ValueError("invalid issued page token")
        return self


class GeoSearchRepository:
    """Each search owns `data/searches/<uuid>/search.json` and no shared mutable file."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def write(self, record: GeoSearchRecord) -> None:
        path = self._path(record.id)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".json.part")
            temporary.write_text(
                record.model_dump_json(by_alias=False, exclude_none=True), encoding="utf-8"
            )
            os.replace(temporary, path)

    def read(self, identity: UUID | str) -> GeoSearchRecord:
        parsed = _uuid(identity)
        path = self._path(parsed)
        with self._lock:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                record = GeoSearchRecord.model_validate(payload)
            except FileNotFoundError:
                raise
            except (OSError, TypeError, ValueError, json.JSONDecodeError, ValidationError) as error:
                raise GeoSearchRepositoryError("GEO_SEARCH_STATE_INVALID") from error
        if record.id != parsed:
            raise GeoSearchRepositoryError("GEO_SEARCH_STATE_INVALID")
        return record

    def list(self) -> tuple[GeoSearchRecord, ...]:
        with self._lock:
            paths = tuple(
                sorted(self._root.glob("*/search.json"), key=lambda item: item.parent.name)
            )
        return tuple(self.read(path.parent.name) for path in paths)

    def verify_provenance(
        self,
        provenance: GeoSearchProvenance,
        *,
        expected_status: GeoSearchStatus,
        expected_source_id: UUID | str | None = None,
    ) -> None:
        """Compare every provenance field with the durable selected snapshot."""
        try:
            record = self.read(provenance.search_id)
        except (FileNotFoundError, GeoSearchRepositoryError) as error:
            raise GeoSearchRepositoryError("GEO_SEARCH_PROVENANCE_INVALID") from error
        if record.status is not expected_status:
            raise GeoSearchRepositoryError("GEO_SEARCH_PROVENANCE_INVALID")
        if expected_source_id is not None and record.source_id != str(expected_source_id):
            raise GeoSearchRepositoryError("GEO_SEARCH_PROVENANCE_INVALID")
        if (
            record.query_hash != provenance.query_hash
            or record.selected_accession != provenance.selected_accession
            or record.selection_revision != provenance.selection_revision
        ):
            raise GeoSearchRepositoryError("GEO_SEARCH_PROVENANCE_INVALID")
        hit = next(
            (item for item in record.items if item.source_id == provenance.selected_accession),
            None,
        )
        if hit is None or (
            hit.provider != provenance.provider
            or hit.evidence.retrieved_at != provenance.retrieved_at
            or hit.evidence.content_sha256 != provenance.evidence_sha256
        ):
            raise GeoSearchRepositoryError("GEO_SEARCH_PROVENANCE_INVALID")

    def verify_source_provenance(
        self,
        provenance: GeoSearchProvenance | None,
        *,
        source_id: UUID | str,
        expected_status: GeoSearchStatus,
    ) -> None:
        """Require a bound selected source to retain its provenance evidence."""

        if provenance is not None:
            self.verify_provenance(
                provenance,
                expected_status=expected_status,
                expected_source_id=source_id,
            )
            return
        if any(
            record.status is expected_status and record.source_id == str(source_id)
            for record in self.list()
        ):
            raise GeoSearchRepositoryError("GEO_SEARCH_PROVENANCE_INVALID")

    def _path(self, identity: UUID) -> Path:
        path = (self._root / str(identity) / "search.json").resolve()
        if self._root not in path.parents:
            raise GeoSearchRepositoryError("GEO_SEARCH_STATE_INVALID")
        return path


def _uuid(value: UUID | str) -> UUID:
    try:
        parsed = value if isinstance(value, UUID) else UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise GeoSearchRepositoryError("GEO_SEARCH_NOT_FOUND") from error
    if parsed.version != 4:
        raise GeoSearchRepositoryError("GEO_SEARCH_NOT_FOUND")
    return parsed


__all__ = [
    "GeoSearchRecord",
    "GeoSearchRepository",
    "GeoSearchRepositoryError",
    "GeoSearchStatus",
]
