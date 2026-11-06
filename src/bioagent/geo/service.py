"""Restart-safe GEO discovery/import coordinator with a dedicated I/O pool."""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import Event, RLock
from time import monotonic
from typing import Protocol
from uuid import UUID, uuid4

from bioagent.geo.client import GeoDiscoveryError, normalize_accession
from bioagent.geo.download import DownloadResult, GeoDownloadError
from bioagent.geo.models import (
    GeoCandidate,
    GeoImportStatus,
    GeoSearchProvenance,
    GeoSource,
    SourceSelection,
)
from bioagent.geo.repository import GeoRepository, GeoRepositoryError
from bioagent.geo.search_repository import (
    GeoSearchRepository,
    GeoSearchRepositoryError,
    GeoSearchStatus,
)
from bioagent.geo.transform import (
    GeoTransformError,
    MappingPreview,
    preview_mapping,
    transform_selection,
)
from bioagent.geo.transport import GeoTransportError
from bioagent.services.datasets import DatasetImportError, DatasetImportService

_NEXT = {
    "DISCOVERING": {"AWAITING_SELECTION"},
    "AWAITING_SELECTION": {"DOWNLOADING"},
    "DOWNLOADING": {"AWAITING_MAPPING"},
    "AWAITING_MAPPING": {"VALIDATING"},
    "VALIDATING": {"READY"},
}


def can_transition(current: str, target: str) -> bool:
    """Return only fixed import transitions; READY never executes statistics."""
    if current in {"READY", "FAILED", "CANCELLED"}:
        return False
    allowed = _NEXT.get(current)
    return allowed is not None and target in allowed | {"FAILED", "CANCELLED"}


class GeoServiceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Discovery(Protocol):
    def discover(self, accession: str) -> GeoSource: ...


class Downloader(Protocol):
    def download(
        self,
        url: str,
        destination: Path,
        *,
        cancel_event: Event | None = None,
        progress: Callable[[int], None] | None = None,
    ) -> DownloadResult: ...


@dataclass(frozen=True)
class _ImportKey:
    source_id: UUID
    candidate_id: UUID
    revision: int


class GeoImportService:
    """Coordinates deterministic GEO work without sharing the R job runner.

    The JSON state records are intentionally written before/after every visible
    transition.  A process restart therefore leaves pending work readable but
    never replays an unconfirmed network request.
    """

    def __init__(
        self,
        repository: GeoRepository,
        discovery: Discovery,
        downloader: Downloader,
        datasets: DatasetImportService,
        *,
        max_workers: int = 2,
        max_queued: int = 16,
        event_sink: Callable[[dict[str, object]], None] | None = None,
        ready_sink: Callable[[dict[str, object]], None] | None = None,
        search_repository: GeoSearchRepository | None = None,
    ) -> None:
        if max_workers < 1 or max_workers > 2 or max_queued < 1 or max_queued > 16:
            raise ValueError("invalid GEO I/O capacity")
        self._repository = repository
        self._discovery = discovery
        self._downloader = downloader
        self._datasets = datasets
        self._max_queued = max_queued
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="geo-io")
        self._lock = RLock()
        self._futures: dict[UUID, Future[None]] = {}
        self._cancellations: dict[UUID, Event] = {}
        self._event_sink = event_sink
        self._ready_sink = ready_sink
        self._search_repository = search_repository
        self._last_progress: dict[str, float] = {}
        self._closed = False
        self._recover_interrupted()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for cancellation in self._cancellations.values():
                cancellation.set()
            for category in ("sources", "imports"):
                for state in self._repository.list_states(category):
                    if state.get("status") not in {
                        GeoImportStatus.DISCOVERING.value,
                        GeoImportStatus.DOWNLOADING.value,
                        GeoImportStatus.VALIDATING.value,
                    }:
                        continue
                    state["status"] = GeoImportStatus.FAILED.value
                    state["error_code"] = "GEO_SERVICE_CLOSED"
                    if category == "sources":
                        self._write_source(state)
                    else:
                        self._write_import(state)
        # Wait until cooperative download cancellation has released all worker
        # callbacks before the owning WorkbenchStore is closed by the API.
        self._executor.shutdown(wait=True, cancel_futures=True)

    def bind_ready_sink(self, sink: Callable[[dict[str, object]], None]) -> None:
        self._ready_sink = sink

    def bind_event_sink(self, sink: Callable[[dict[str, object]], None]) -> None:
        self._event_sink = sink

    def create_source(
        self,
        accession: str,
        *,
        conversation_id: str | None = None,
        turn_id: str | None = None,
        provenance: GeoSearchProvenance | None = None,
    ) -> dict[str, object]:
        normalized = normalize_accession(accession)
        if provenance is not None:
            if not isinstance(provenance, GeoSearchProvenance):
                raise GeoServiceError("GEO_SEARCH_PROVENANCE_INVALID")
            provenance = GeoSearchProvenance.model_validate(provenance.model_dump(mode="python"))
            if provenance.selected_accession != normalized:
                raise GeoServiceError("GEO_SEARCH_PROVENANCE_INVALID")
            _verify_search_provenance(
                provenance,
                self._search_repository,
                expected_status=GeoSearchStatus.SELECTING,
                expected_source_id=None,
            )
        source_id = uuid4()
        state: dict[str, object] = {
            "id": str(source_id),
            "accession": normalized,
            "status": GeoImportStatus.DISCOVERING.value,
            "revision": 1,
            "source": None,
            "error_code": None,
            "context": _context(conversation_id, turn_id),
            "search_provenance": (
                None if provenance is None else provenance.model_dump(mode="json")
            ),
        }
        with self._lock:
            self._write_source(state)
            try:
                self._submit(source_id, lambda: self._discover(source_id))
            except GeoServiceError as error:
                self._fail_source(source_id, error.code)
        return self.get_source(source_id)

    def get_source(self, source_id: UUID | str) -> dict[str, object]:
        try:
            return self._repository.read_state("sources", source_id)
        except FileNotFoundError as error:
            raise GeoServiceError("GEO_SOURCE_NOT_FOUND") from error

    def request_import(
        self, source_id: UUID | str, candidate_id: UUID | str, revision: int
    ) -> dict[str, object]:
        source = self.get_source(source_id)
        if source.get("status") != GeoImportStatus.AWAITING_SELECTION.value:
            raise GeoServiceError("GEO_SOURCE_NOT_READY")
        if revision != source.get("revision") or revision < 1:
            raise GeoServiceError("SOURCE_SELECTION_CONFLICT")
        parsed_source, parsed_candidate = _uuid(source_id), _uuid(candidate_id)
        record = _source_model(source)
        candidate = next((item for item in record.candidates if item.id == parsed_candidate), None)
        if candidate is None or candidate.source_id != parsed_source:
            raise GeoServiceError("GEO_CANDIDATE_NOT_FOUND")
        if candidate.data_kind.value not in {"RAW_COUNTS", "UNKNOWN"}:
            raise GeoServiceError("GEO_COUNTS_INVALID")
        key = _ImportKey(parsed_source, parsed_candidate, revision)
        with self._lock:
            existing = self._find_import(key)
            if existing is not None:
                return existing
            import_id = uuid4()
            state: dict[str, object] = {
                "id": str(import_id),
                "source_id": str(parsed_source),
                "candidate_id": str(parsed_candidate),
                "revision": revision,
                "status": GeoImportStatus.DOWNLOADING.value,
                "dataset_id": None,
                "error_code": None,
                "preview": None,
                "selection": None,
                "selection_hash": None,
                "raw_path": None,
                "raw_sha256": None,
                "bytes_downloaded": 0,
                "context": source.get("context"),
            }
            self._write_import(state)
            self._cancellations[import_id] = Event()
            try:
                self._submit(import_id, lambda: self._download(import_id))
            except GeoServiceError as error:
                self._fail_import(import_id, error.code)
                raise
        return self.get_import(import_id)

    def get_import(self, import_id: UUID | str) -> dict[str, object]:
        try:
            return self._repository.read_state("imports", import_id)
        except FileNotFoundError as error:
            raise GeoServiceError("GEO_IMPORT_NOT_FOUND") from error

    def submit_selection(
        self, import_id: UUID | str, selection: SourceSelection
    ) -> dict[str, object]:
        identity = _uuid(import_id)
        with self._lock:
            state = self.get_import(identity)
            digest = _selection_digest(selection)
            if state.get("status") == GeoImportStatus.READY.value:
                if state.get("selection_hash") == digest:
                    return state
                raise GeoServiceError("SOURCE_SELECTION_CONFLICT")
            if state.get("status") == GeoImportStatus.VALIDATING.value:
                if state.get("selection_hash") == digest:
                    return state
                raise GeoServiceError("SOURCE_SELECTION_CONFLICT")
            if state.get("status") != GeoImportStatus.AWAITING_MAPPING.value:
                raise GeoServiceError("GEO_SAMPLE_MAPPING_REQUIRED")
            if selection.revision != state.get("revision"):
                raise GeoServiceError("SOURCE_SELECTION_CONFLICT")
            if str(selection.source_id) != state.get("source_id") or str(
                selection.candidate_id
            ) != state.get("candidate_id"):
                raise GeoServiceError("SOURCE_SELECTION_CONFLICT")
            if selection.raw_sha256 != state.get("raw_sha256"):
                raise GeoServiceError("SOURCE_CHANGED")
            state["selection"] = selection.model_dump(mode="json")
            state["selection_hash"] = digest
            self._transition(state, GeoImportStatus.VALIDATING.value)
            self._write_import(state)
            try:
                self._submit(identity, lambda: self._validate(identity))
            except GeoServiceError as error:
                self._fail_import(identity, error.code)
                raise
        return self.get_import(identity)

    def cancel(self, import_id: UUID | str) -> dict[str, object]:
        identity = _uuid(import_id)
        with self._lock:
            state = self.get_import(identity)
            if state.get("status") in {
                GeoImportStatus.READY.value,
                GeoImportStatus.FAILED.value,
                GeoImportStatus.CANCELLED.value,
            }:
                return state
            self._cancellations.setdefault(identity, Event()).set()
            self._transition(state, GeoImportStatus.CANCELLED.value)
            self._write_import(state)
            self._cleanup_temp(state)
        return self.get_import(identity)

    def _discover(self, source_id: UUID) -> None:
        try:
            state = self.get_source(source_id)
            if state.get("status") != GeoImportStatus.DISCOVERING.value:
                return
            source = self._discovery.discover(str(state["accession"]))
            source = _with_source_id(source, source_id)
            with self._lock:
                current = self.get_source(source_id)
                if self._closed or current.get("status") != GeoImportStatus.DISCOVERING.value:
                    return
                current["source"] = source.model_dump(mode="json")
                self._transition(current, GeoImportStatus.AWAITING_SELECTION.value)
                self._write_source(current)
        except (GeoDiscoveryError, GeoTransportError, ValueError) as error:
            self._fail_source(source_id, _code(error, "GEO_DISCOVERY_FAILED"))

    def _download(self, import_id: UUID) -> None:
        try:
            state = self.get_import(import_id)
            if state.get("status") != GeoImportStatus.DOWNLOADING.value:
                return
            source_state = self.get_source(_state_id(state, "source_id"))
            source = _source_model(source_state)
            candidate = _candidate(source, state["candidate_id"])
            root = (
                self._repository._root / ".geo-downloads" / str(import_id)
            )  # controlled private temp
            root.mkdir(parents=True, exist_ok=True)
            suffix = Path(candidate.file_name).suffix
            if suffix.casefold() == ".gz":
                suffix = Path(Path(candidate.file_name).stem).suffix + suffix
            destination = root / f"source{suffix}"
            result = self._downloader.download(
                candidate.url,
                destination,
                cancel_event=self._cancellations.get(import_id),
                progress=lambda total: self._progress(import_id, total),
            )
            with self._lock:
                current = self.get_import(import_id)
                if current.get("status") != GeoImportStatus.DOWNLOADING.value:
                    result.path.unlink(missing_ok=True)
                    return
                preview = preview_mapping(result.path, source, candidate)
                current.update(
                    raw_path=str(result.path),
                    raw_sha256=result.sha256,
                    bytes_downloaded=result.bytes_downloaded,
                    preview=_preview(preview),
                )
                self._transition(current, GeoImportStatus.AWAITING_MAPPING.value)
                self._write_import(current)
            return
        except (GeoDownloadError, GeoTransformError, OSError, ValueError) as error:
            if self.get_import(import_id).get("status") != GeoImportStatus.CANCELLED.value:
                self._fail_import(import_id, _code(error, "GEO_COUNTS_INVALID"))

    def _validate(self, import_id: UUID) -> None:
        # Validation/import/publication is one critical section.  This favours
        # cancellation determinism over parallel conversion: a cancellation
        # either wins before side effects begin, or waits and observes READY.
        with self._lock:
            self._validate_locked(import_id)

    def _validate_locked(self, import_id: UUID) -> None:
        try:
            state = self.get_import(import_id)
            if state.get("status") != GeoImportStatus.VALIDATING.value:
                return
            source_state = self.get_source(_state_id(state, "source_id"))
            source = _source_model(source_state)
            candidate = _candidate(source, state["candidate_id"])
            selection = SourceSelection.model_validate(state["selection"])
            raw_path = Path(str(state["raw_path"]))
            _search_provenance(
                source_state,
                source.accession,
                self._search_repository,
                source.id,
                expected_status=GeoSearchStatus.SELECTED,
            )
            normalized = transform_selection(raw_path, source, candidate, selection)
            dataset_id = self._datasets.import_geo(normalized)
            try:
                record = self._repository.publish(
                    source,
                    candidate,
                    selection,
                    raw_path,
                    normalized,
                    dataset_id=dataset_id,
                    provenance=_search_provenance(
                    source_state,
                    source.accession,
                    self._search_repository,
                    source.id,
                    expected_status=GeoSearchStatus.SELECTED,
                    ),
                )
            except Exception:
                self._datasets.discard_dataset(dataset_id)
                raise
            state = self.get_import(import_id)
            if state.get("status") == GeoImportStatus.CANCELLED.value:
                return
            state.update(dataset_id=dataset_id, published_source_id=str(record.source_id))
            self._transition(state, GeoImportStatus.READY.value)
            self._write_import(state)
            self._notify_ready(state)
        except (
            DatasetImportError,
            GeoRepositoryError,
            GeoTransformError,
            OSError,
            ValueError,
        ) as error:
            if self.get_import(import_id).get("status") != GeoImportStatus.CANCELLED.value:
                self._fail_import(import_id, _code(error, "GEO_COUNTS_INVALID"))

    def _submit(self, identity: UUID, operation) -> None:  # type: ignore[no-untyped-def]
        if self._closed:
            raise GeoServiceError("GEO_SERVICE_CLOSED")
        active = sum(not future.done() for future in self._futures.values())
        if active >= self._max_queued + 2:
            raise GeoServiceError("GEO_QUEUE_FULL")
        future = self._executor.submit(operation)
        self._futures[identity] = future

    def _transition(self, state: dict[str, object], target: str) -> None:
        current = str(state.get("status"))
        if not can_transition(current, target):
            raise GeoServiceError("GEO_INVALID_TRANSITION")
        state["status"] = target

    def _write_source(self, state: dict[str, object]) -> None:
        self._repository.write_state("sources", str(state["id"]), state)
        self._emit(state, "source")

    def _write_import(self, state: dict[str, object]) -> None:
        self._repository.write_state("imports", str(state["id"]), state)
        self._emit(state, "import")

    def _emit(self, state: dict[str, object], resource: str) -> None:
        if self._event_sink is None:
            return
        context = state.get("context")
        if not isinstance(context, dict):
            return
        conversation_id = context.get("conversation_id")
        turn_id = context.get("turn_id")
        if not isinstance(conversation_id, str) or not isinstance(turn_id, str):
            return
        identity = str(state["id"])
        now = monotonic()
        if state.get("status") == GeoImportStatus.DOWNLOADING.value:
            previous = self._last_progress.get(identity)
            if previous is not None and now - previous < 1:
                return
            self._last_progress[identity] = now
        self._event_sink(
            {
                "conversation_id": conversation_id,
                "turn_id": turn_id,
                "kind": "geo.updated",
                "resource": resource,
                "id": identity,
                "status": state.get("status"),
                "dataset_id": state.get("dataset_id"),
                "error_code": state.get("error_code"),
                "bytes_downloaded": state.get("bytes_downloaded", 0),
            }
        )

    def _progress(self, import_id: UUID, total: int) -> None:
        if total < 0:
            return
        with self._lock:
            state = self.get_import(import_id)
            if state.get("status") != GeoImportStatus.DOWNLOADING.value:
                return
            now = monotonic()
            previous = self._last_progress.get(str(import_id))
            if previous is not None and now - previous < 1:
                return
            state["bytes_downloaded"] = total
            self._write_import(state)

    def _notify_ready(self, state: dict[str, object]) -> None:
        if self._ready_sink is None:
            return
        try:
            self._ready_sink(dict(state))
        except Exception:
            # READY evidence is already durable; an optional UI/workflow wake-up
            # cannot invalidate a published source or trigger an automatic retry.
            return

    def _cleanup_temp(self, state: dict[str, object]) -> None:
        raw_path = state.get("raw_path")
        identity = state.get("id")
        if not isinstance(raw_path, str) or not isinstance(identity, str):
            return
        temp_root = (self._repository._root / ".geo-downloads" / identity).resolve()
        candidate = Path(raw_path)
        try:
            candidate.resolve().relative_to(temp_root)
        except ValueError:
            return
        candidate.unlink(missing_ok=True)

    def _fail_source(self, source_id: UUID, code: str) -> None:
        with self._lock:
            state = self.get_source(source_id)
            if state.get("status") == GeoImportStatus.DISCOVERING.value:
                self._transition(state, GeoImportStatus.FAILED.value)
                state["error_code"] = code
                self._write_source(state)

    def _fail_import(self, import_id: UUID, code: str) -> None:
        with self._lock:
            state = self.get_import(import_id)
            if state.get("status") not in {
                GeoImportStatus.READY.value,
                GeoImportStatus.CANCELLED.value,
                GeoImportStatus.FAILED.value,
            }:
                self._transition(state, GeoImportStatus.FAILED.value)
                state["error_code"] = code
                self._write_import(state)

    def _find_import(self, key: _ImportKey) -> dict[str, object] | None:
        for value in self._repository.list_states("imports"):
            try:
                status = value.get("status")
            except AttributeError:
                continue
            if status in {GeoImportStatus.FAILED.value, GeoImportStatus.CANCELLED.value}:
                continue
            if (value.get("source_id"), value.get("candidate_id"), value.get("revision")) == (
                str(key.source_id),
                str(key.candidate_id),
                key.revision,
            ):
                return value
        return None

    def _recover_interrupted(self) -> None:
        """A restarted process never resumes unowned network or validation work."""
        for category in ("sources", "imports"):
            for state in self._repository.list_states(category):
                if state.get("status") not in {
                    GeoImportStatus.DISCOVERING.value,
                    GeoImportStatus.DOWNLOADING.value,
                    GeoImportStatus.VALIDATING.value,
                }:
                    continue
                state["status"] = GeoImportStatus.FAILED.value
                state["error_code"] = "GEO_PROCESS_RESTARTED"
                if category == "sources":
                    self._write_source(state)
                else:
                    self._write_import(state)


def _uuid(value: UUID | str) -> UUID:
    try:
        result = value if isinstance(value, UUID) else UUID(value)
    except (TypeError, ValueError, AttributeError) as error:
        raise GeoServiceError("GEO_IMPORT_NOT_FOUND") from error
    if result.version != 4:
        raise GeoServiceError("GEO_IMPORT_NOT_FOUND")
    return result


def _source_model(state: dict[str, object]) -> GeoSource:
    source = state.get("source")
    if not isinstance(source, dict):
        raise GeoServiceError("GEO_SOURCE_NOT_READY")
    return GeoSource.model_validate(source)


def _search_provenance(
    state: dict[str, object],
    accession: str,
    search_repository: GeoSearchRepository | None,
    source_id: UUID,
    *,
    expected_status: GeoSearchStatus,
) -> GeoSearchProvenance | None:
    value = state.get("search_provenance")
    if value is None:
        _verify_search_provenance(
            None,
            search_repository,
            expected_status=expected_status,
            expected_source_id=source_id,
        )
        return None
    if not isinstance(value, dict):
        raise GeoServiceError("GEO_SEARCH_PROVENANCE_INVALID")
    try:
        provenance = GeoSearchProvenance.model_validate(value)
    except ValueError as error:
        raise GeoServiceError("GEO_SEARCH_PROVENANCE_INVALID") from error
    if provenance.selected_accession != accession:
        raise GeoServiceError("GEO_SEARCH_PROVENANCE_INVALID")
    _verify_search_provenance(
        provenance,
        search_repository,
        expected_status=expected_status,
        expected_source_id=source_id,
    )
    return provenance


def _verify_search_provenance(
    provenance: GeoSearchProvenance | None,
    search_repository: GeoSearchRepository | None,
    *,
    expected_status: GeoSearchStatus,
    expected_source_id: UUID | None,
) -> None:
    if search_repository is None:
        if provenance is not None:
            raise GeoServiceError("GEO_SEARCH_PROVENANCE_INVALID")
        return
    try:
        if expected_source_id is None:
            if provenance is None:
                raise GeoSearchRepositoryError("GEO_SEARCH_PROVENANCE_INVALID")
            search_repository.verify_provenance(provenance, expected_status=expected_status)
        else:
            search_repository.verify_source_provenance(
                provenance,
                source_id=expected_source_id,
                expected_status=expected_status,
            )
    except GeoSearchRepositoryError as error:
        raise GeoServiceError("GEO_SEARCH_PROVENANCE_INVALID") from error


def _state_id(state: dict[str, object], key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str):
        raise GeoServiceError("GEO_SOURCE_NOT_FOUND")
    return value


def _candidate(source: GeoSource, value: object) -> GeoCandidate:
    try:
        identity = UUID(str(value))
    except ValueError as error:
        raise GeoServiceError("GEO_CANDIDATE_NOT_FOUND") from error
    candidate = next((item for item in source.candidates if item.id == identity), None)
    if candidate is None or candidate.source_id != source.id:
        raise GeoServiceError("GEO_CANDIDATE_NOT_FOUND")
    return candidate


def _with_source_id(source: GeoSource, source_id: UUID) -> GeoSource:
    candidates = tuple(
        item.model_copy(update={"source_id": source_id}) for item in source.candidates
    )
    return source.model_copy(update={"id": source_id, "candidates": candidates})


def _preview(value: MappingPreview) -> dict[str, object]:
    return {
        "source_id": value.source_id,
        "candidate_id": value.candidate_id,
        "raw_sha256": value.raw_sha256,
        "headers": list(value.headers),
        "feature_columns": list(value.feature_columns),
        "sample_columns": list(value.sample_columns),
        "suggested_sample_map": value.suggested_sample_map,
        "unmapped_source_samples": list(value.unmapped_source_samples),
    }


def _selection_digest(selection: SourceSelection) -> str:
    payload = selection.model_dump(mode="json")
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _context(conversation_id: str | None, turn_id: str | None) -> dict[str, str] | None:
    if conversation_id is None and turn_id is None:
        return None
    if not isinstance(conversation_id, str) or not isinstance(turn_id, str):
        raise GeoServiceError("GEO_CONTEXT_INVALID")
    try:
        UUID(conversation_id)
        UUID(turn_id)
    except ValueError as error:
        raise GeoServiceError("GEO_CONTEXT_INVALID") from error
    return {"conversation_id": conversation_id, "turn_id": turn_id}


def _code(error: BaseException, fallback: str) -> str:
    value = getattr(error, "code", None)
    return value if isinstance(value, str) else fallback


__all__ = ["GeoImportService", "GeoServiceError", "can_transition"]
