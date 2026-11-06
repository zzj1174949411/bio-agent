"""Content-addressed, tamper-evident storage for GEO source imports."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

import pandas as pd

from bioagent.geo.models import GeoCandidate, GeoSearchProvenance, GeoSource, SourceSelection
from bioagent.geo.search_repository import (
    GeoSearchRepository,
    GeoSearchRepositoryError,
    GeoSearchStatus,
)
from bioagent.geo.transform import NormalizedDataset, selection_hash


class GeoRepositoryError(ValueError):
    """Stable source-cache or selection persistence error."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(f"{code}: {message or code}")


@dataclass(frozen=True)
class GeoSourceRecord:
    source_id: UUID
    root: Path
    raw_path: Path
    counts_path: Path
    metadata_path: Path
    source_json: Path
    raw_sha256: str
    counts_sha256: str
    metadata_sha256: str
    selection_hash: str
    revision: int
    dataset_id: str | None = None
    search_provenance: GeoSearchProvenance | None = None


class GeoRepository:
    """Store each confirmed import in a new UUID directory.

    A source directory is never reused.  This makes a URL returning new bytes
    a new provenance record and leaves prior analyses reproducible.
    """

    conversion_version = "1.0"

    def __init__(
        self, root: Path, *, search_repository: GeoSearchRepository | None = None
    ) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._state_root = self._root / ".geo-state"
        self._state_root.mkdir(exist_ok=True)
        # os.replace is atomic for readers on POSIX, but Windows can reject a
        # simultaneous read while replacing a state file.  API polling and the
        # I/O worker share this repository, so serialize those short critical
        # sections instead of exposing a spurious GEO_SOURCE_NOT_FOUND.
        self._state_lock = RLock()
        self._search_repository = search_repository

    def bind_search_repository(self, repository: GeoSearchRepository) -> None:
        """Bind the authoritative search store during dependency assembly."""
        if not isinstance(repository, GeoSearchRepository):
            raise TypeError("repository must be a GeoSearchRepository")
        with self._state_lock:
            self._search_repository = repository

    def write_state(
        self, category: str, identity: UUID | str, payload: Mapping[str, object]
    ) -> None:
        """Atomically persist service state separately from published evidence."""
        if category not in {"sources", "imports"}:
            raise ValueError("invalid GEO state category")
        parsed = _parse_uuid(identity)
        with self._state_lock:
            directory = self._state_root / category
            directory.mkdir(exist_ok=True)
            _write_json_atomic(dict(payload), directory / f"{parsed}.json")

    def read_state(self, category: str, identity: UUID | str) -> dict[str, object]:
        if category not in {"sources", "imports"}:
            raise ValueError("invalid GEO state category")
        parsed = _parse_uuid(identity)
        path = self._state_root / category / f"{parsed}.json"
        with self._state_lock:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError) as error:
                raise FileNotFoundError("GEO state not found") from error
        if not isinstance(value, dict):
            raise GeoRepositoryError("GEO_SOURCE_CACHE_TAMPERED", "invalid service state")
        return value

    def list_states(self, category: str) -> tuple[dict[str, object], ...]:
        if category not in {"sources", "imports"}:
            raise ValueError("invalid GEO state category")
        directory = self._state_root / category
        return tuple(self.read_state(category, path.stem) for path in directory.glob("*.json"))

    def publish(
        self,
        source: GeoSource,
        candidate: GeoCandidate,
        selection: SourceSelection,
        raw_path: Path,
        counts: pd.DataFrame | NormalizedDataset,
        metadata: pd.DataFrame | None = None,
        *,
        content_type: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        dataset_id: str | None = None,
        provenance: GeoSearchProvenance | None = None,
    ) -> GeoSourceRecord:
        if isinstance(counts, NormalizedDataset):
            normalized = counts
            counts_frame = normalized.counts
            metadata_frame = normalized.metadata
        else:
            if metadata is None:
                raise TypeError("metadata is required when publishing DataFrames")
            counts_frame = counts
            metadata_frame = metadata
        if not raw_path.is_file():
            raise GeoRepositoryError("SOURCE_CHANGED", "raw source file is missing")
        raw_sha256 = _sha256_file(raw_path)
        if raw_sha256 != selection.raw_sha256:
            raise GeoRepositoryError("SOURCE_CHANGED", "selection hash does not match raw bytes")
        if source.id != candidate.source_id or selection.source_id != source.id:
            raise GeoRepositoryError("SOURCE_CHANGED", "source and candidate IDs do not match")
        if selection.candidate_id != candidate.id:
            raise GeoRepositoryError("SOURCE_CHANGED", "selection and candidate IDs do not match")
        if provenance is not None:
            if not isinstance(provenance, GeoSearchProvenance):
                raise GeoRepositoryError("GEO_SEARCH_PROVENANCE_INVALID")
            provenance = GeoSearchProvenance.model_validate(provenance.model_dump(mode="python"))
            if provenance.selected_accession != source.accession:
                raise GeoRepositoryError("GEO_SEARCH_PROVENANCE_INVALID")
        self._verify_source_provenance(provenance, source.id)

        source_id = source.id
        root = self._resolve(source_id)
        if root.exists():
            source_id = uuid4()
            root = self._resolve(source_id)
        root.mkdir()
        raw_dir = root / "raw"
        normalized_dir = root / "normalized"
        raw_dir.mkdir()
        normalized_dir.mkdir()
        raw_target = raw_dir / "source.bin"
        counts_target = normalized_dir / "counts.csv"
        metadata_target = normalized_dir / "metadata.csv"
        source_json = root / "source.json"
        try:
            _copy_atomic(raw_path, raw_target)
            _write_frame_atomic(counts_frame, counts_target)
            _write_frame_atomic(metadata_frame, metadata_target)
            counts_sha256 = _sha256_file(counts_target)
            metadata_sha256 = _sha256_file(metadata_target)
            selection_digest = selection_hash(raw_sha256, selection.model_dump(mode="json"))
            payload = {
                "source_id": str(source_id),
                "dataset_id": dataset_id,
                "geo_source_id": str(source.id),
                "accession": source.accession,
                "title": source.title,
                "candidate_id": str(candidate.id),
                "url": candidate.url,
                "file_name": candidate.file_name,
                "retrieved_at": source.retrieved_at.isoformat(),
                "confirmed_at": datetime.now(UTC).isoformat(),
                "content_type": content_type,
                "etag": etag,
                "last_modified": last_modified,
                "compression": candidate.compression.value,
                "raw_sha256": raw_sha256,
                "counts_sha256": counts_sha256,
                "metadata_sha256": metadata_sha256,
                "selection_hash": selection_digest,
                "selection": selection.model_dump(mode="json"),
                "excluded_samples": list(selection.excluded_samples),
                "conversion_version": self.conversion_version,
                "search_provenance": (
                    None if provenance is None else provenance.model_dump(mode="json")
                ),
                "search_provenance_sha256": (
                    None if provenance is None else provenance.provenance_sha256
                ),
            }
            _write_json_atomic(payload, source_json)
            _write_json_atomic(payload, root / "metadata.json")
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise
        return GeoSourceRecord(
            source_id=source_id,
            root=root,
            raw_path=raw_target,
            counts_path=counts_target,
            metadata_path=metadata_target,
            source_json=source_json,
            raw_sha256=raw_sha256,
            counts_sha256=counts_sha256,
            metadata_sha256=metadata_sha256,
            selection_hash=selection_digest,
            revision=selection.revision,
            dataset_id=dataset_id,
            search_provenance=provenance,
        )

    create = publish

    def read(self, source_id: UUID | str) -> GeoSourceRecord:
        parsed = _parse_uuid(source_id)
        root = self._resolve(parsed)
        source_json = root / "source.json"
        if not source_json.is_file():
            raise FileNotFoundError("source record not found")
        try:
            payload = json.loads(source_json.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("source metadata must be an object")
            raw_path = root / "raw" / "source.bin"
            counts_path = root / "normalized" / "counts.csv"
            metadata_path = root / "normalized" / "metadata.csv"
            if payload.get("source_id") != str(parsed):
                raise ValueError("source ID mismatch")
            for key, path in (
                ("raw_sha256", raw_path),
                ("counts_sha256", counts_path),
                ("metadata_sha256", metadata_path),
            ):
                expected = payload.get(key)
                if (
                    not isinstance(expected, str)
                    or not path.is_file()
                    or _sha256_file(path) != expected
                ):
                    raise ValueError(f"{key} mismatch")
            selection_digest = payload.get("selection_hash")
            if not isinstance(selection_digest, str):
                raise ValueError("selection hash missing")
            selection_payload = payload.get("selection")
            if not isinstance(selection_payload, dict) or not isinstance(
                selection_payload.get("revision"), int
            ):
                raise ValueError("selection revision missing")
            dataset_id = payload.get("dataset_id")
            if dataset_id is not None and not isinstance(dataset_id, str):
                raise ValueError("dataset ID is invalid")
            raw_geo_source_id = payload.get("geo_source_id")
            if not isinstance(raw_geo_source_id, str):
                raise ValueError("GEO source ID is invalid")
            geo_source_id = _parse_uuid(raw_geo_source_id)
            search_provenance = _read_search_provenance(payload)
            # A self-consistent payload hash is not authority: re-read the
            # immutable selected catalog snapshot before a source can feed a
            # new run, recovery, or completed-run reuse.  A selected source
            # cannot discard its provenance and become a direct GSE source.
            self._verify_source_provenance(search_provenance, geo_source_id)
        except GeoRepositoryError:
            raise
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise GeoRepositoryError(
                "GEO_SOURCE_CACHE_TAMPERED", "cached source failed verification"
            ) from error
        return GeoSourceRecord(
            source_id=parsed,
            root=root,
            raw_path=raw_path,
            counts_path=counts_path,
            metadata_path=metadata_path,
            source_json=source_json,
            raw_sha256=payload["raw_sha256"],
            counts_sha256=payload["counts_sha256"],
            metadata_sha256=payload["metadata_sha256"],
            selection_hash=selection_digest,
            revision=selection_payload["revision"],
            dataset_id=dataset_id,
            search_provenance=search_provenance,
        )

    get = read

    def _verify_source_provenance(
        self, provenance: GeoSearchProvenance | None, source_id: UUID
    ) -> None:
        if self._search_repository is None:
            if provenance is not None:
                raise GeoRepositoryError("GEO_SEARCH_PROVENANCE_INVALID")
            return
        try:
            self._search_repository.verify_source_provenance(
                provenance,
                source_id=source_id,
                expected_status=GeoSearchStatus.SELECTED,
            )
        except GeoSearchRepositoryError as error:
            raise GeoRepositoryError("GEO_SEARCH_PROVENANCE_INVALID") from error

    def find_cached(self, accession: str, url: str, raw_sha256: str) -> GeoSourceRecord | None:
        for directory in sorted(self._root.iterdir(), key=lambda item: item.name):
            if not directory.is_dir():
                continue
            source_json = directory / "source.json"
            if not source_json.is_file():
                continue
            try:
                payload = json.loads(source_json.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise GeoRepositoryError(
                    "GEO_SOURCE_CACHE_TAMPERED", "invalid source metadata"
                ) from error
            if not isinstance(payload, dict):
                raise GeoRepositoryError("GEO_SOURCE_CACHE_TAMPERED", "invalid source metadata")
            if (
                payload.get("accession") == accession
                and payload.get("url") == url
                and payload.get("raw_sha256") == raw_sha256
            ):
                return self.read(payload.get("source_id", ""))
        return None

    cache_lookup = find_cached

    def assert_selection_current(
        self,
        source_id: UUID | str,
        *,
        revision: int,
        raw_sha256: str,
        selection: dict[str, object],
    ) -> GeoSourceRecord:
        record = self.read(source_id)
        digest_matches = selection_hash(raw_sha256, selection) == record.selection_hash
        if revision < 1 or revision != record.revision or not digest_matches:
            raise GeoRepositoryError(
                "SOURCE_SELECTION_CONFLICT", "selection revision or hash is stale"
            )
        return record

    def _resolve(self, source_id: UUID) -> Path:
        path = (self._root / str(source_id)).resolve()
        if self._root not in path.parents:
            raise GeoRepositoryError("SOURCE_PATH_INVALID")
        return path


def _parse_uuid(value: UUID | str) -> UUID:
    try:
        parsed = value if isinstance(value, UUID) else UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("invalid source ID") from error
    if parsed.version != 4:
        raise ValueError("invalid source ID")
    return parsed


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_search_provenance(payload: Mapping[str, object]) -> GeoSearchProvenance | None:
    raw = payload.get("search_provenance")
    stored_hash = payload.get("search_provenance_sha256")
    if raw is None and stored_hash is None:
        return None
    if not isinstance(raw, dict) or not isinstance(stored_hash, str):
        raise ValueError("search provenance is invalid")
    provenance = GeoSearchProvenance.model_validate(raw)
    if provenance.selected_accession != payload.get("accession"):
        raise ValueError("search provenance accession mismatch")
    if provenance.provenance_sha256 != stored_hash:
        raise ValueError("search provenance hash mismatch")
    return provenance


def _copy_atomic(source: Path, target: Path) -> None:
    temporary = target.with_suffix(target.suffix + ".part")
    shutil.copyfile(source, temporary)
    os.replace(temporary, target)


def _write_frame_atomic(frame: pd.DataFrame, target: Path) -> None:
    temporary = target.with_suffix(target.suffix + ".part")
    frame.to_csv(temporary, index=True, lineterminator="\n")
    os.replace(temporary, target)


def _write_json_atomic(payload: Mapping[str, object], target: Path) -> None:
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, target)


__all__ = ["GeoRepository", "GeoRepositoryError", "GeoSourceRecord"]
