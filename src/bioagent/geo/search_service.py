"""Restart-safe asynchronous GEO catalog search lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from hmac import compare_digest
from pathlib import Path
from threading import Event, RLock
from typing import Protocol
from uuid import UUID, uuid4

from bioagent.geo.models import GeoSearchProvenance
from bioagent.geo.search import GeoSearchError
from bioagent.geo.search_repository import (
    GeoSearchRecord,
    GeoSearchRepository,
    GeoSearchRepositoryError,
    GeoSearchStatus,
)
from bioagent.geo.service import GeoServiceError
from bioagent.retrieval.contracts import (
    DatasetCatalogProvider,
    DatasetSearchHit,
    DatasetSearchQuery,
)


class GeoSearchServiceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SourceFactory(Protocol):
    def __call__(
        self,
        accession: str,
        conversation_id: str,
        turn_id: str,
        provenance: GeoSearchProvenance,
    ) -> object: ...


class GeoSearchService:
    """Owns bounded provider work; candidate selection cannot download a file."""

    def __init__(
        self,
        root: Path | str,
        provider: DatasetCatalogProvider,
        source_factory: SourceFactory,
        *,
        max_workers: int = 2,
        max_queued: int = 16,
        event_sink: Callable[[dict[str, object]], None] | None = None,
        repository: GeoSearchRepository | None = None,
    ) -> None:
        if max_workers < 1 or max_workers > 2 or max_queued < 1 or max_queued > 16:
            raise ValueError("invalid GEO search capacity")
        self._repository = repository or GeoSearchRepository(Path(root) / "searches")
        self._provider = provider
        self._source_factory = source_factory
        self._max_workers = max_workers
        self._max_queued = max_queued
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="geo-search"
        )
        self._lock = RLock()
        self._futures: dict[UUID, Future[None]] = {}
        self._cancelled: dict[UUID, Event] = {}
        self._event_sink = event_sink
        self._closed = False
        self._recover_interrupted()

    def bind_event_sink(self, sink: Callable[[dict[str, object]], None]) -> None:
        self._event_sink = sink

    def create(
        self,
        query: DatasetSearchQuery,
        conversation_id: str,
        turn_id: str,
        *,
        owner_token_sha256: str | None = None,
    ) -> dict[str, object]:
        try:
            conversation = UUID(conversation_id)
            turn = UUID(turn_id)
        except (TypeError, ValueError) as error:
            raise GeoSearchServiceError("GEO_SEARCH_CONTEXT_INVALID") from error
        with self._lock:
            self._assert_open()
            self._assert_capacity()
            identity = uuid4()
            record = GeoSearchRecord(
                id=identity,
                status=GeoSearchStatus.QUEUED,
                revision=1,
                query=query.model_copy(update={"page_token": None}),
                query_hash=query.query_hash,
                conversation_id=conversation,
                turn_id=turn,
                owner_token_sha256=owner_token_sha256,
            )
            self._write(record)
            self._cancelled[identity] = Event()
            self._submit(identity, first_page=True)
            return _public(record)

    def get(self, search_id: UUID | str) -> dict[str, object]:
        return _public(self._read(search_id))

    def owns(self, search_id: UUID | str, owner_token_sha256: str) -> bool:
        """Verify a browser owner hash without exposing token or context in API output."""
        try:
            record = self._read(search_id)
        except (GeoSearchServiceError, TypeError, ValueError):
            return False
        expected = record.owner_token_sha256
        return isinstance(expected, str) and compare_digest(expected, owner_token_sha256)

    def is_conversation_search(self, search_id: UUID | str, conversation_id: UUID | str) -> bool:
        """Allow the local workbench to recover a search created by an Agent turn.

        Direct API searches always have a browser-owner token.  Agent searches
        are instead bound to a persisted conversation and have no raw owner
        credential to expose or replay, so only those records use this path.
        """
        try:
            record = self._read(search_id)
            return record.owner_token_sha256 is None and record.conversation_id == UUID(
                str(conversation_id)
            )
        except (GeoSearchServiceError, TypeError, ValueError):
            return False

    def next_page(self, search_id: UUID | str, page_token: str, revision: int) -> dict[str, object]:
        with self._lock:
            record = self._current(search_id, revision)
            if record.status is not GeoSearchStatus.AWAITING_SELECTION:
                raise GeoSearchServiceError("GEO_SEARCH_NOT_SELECTABLE")
            offset = record.issued_tokens.get(page_token)
            if offset is None:
                raise GeoSearchServiceError("GEO_SEARCH_PAGE_TOKEN_INVALID")
            if record.next_page_token != page_token:
                raise GeoSearchServiceError("GEO_SEARCH_PAGE_TOKEN_INVALID")
            self._assert_capacity()
            next_record = record.model_copy(
                update={
                    "status": GeoSearchStatus.SEARCHING,
                    "revision": record.revision + 1,
                    "next_page_token": None,
                    "query": record.query.model_copy(update={"page_token": str(offset)}),
                }
            )
            self._write(next_record)
            self._submit(next_record.id, first_page=False)
            return _public(next_record)

    def select(self, search_id: UUID | str, accession: str, revision: int) -> dict[str, object]:
        with self._lock:
            record = self._current(search_id, revision)
            if record.status is not GeoSearchStatus.AWAITING_SELECTION:
                raise GeoSearchServiceError("GEO_SEARCH_NOT_SELECTABLE")
            hit = next((item for item in record.items if item.source_id == accession), None)
            if hit is None:
                raise GeoSearchServiceError("GEO_SEARCH_ACCESSION_NOT_FOUND")
            provenance = GeoSearchProvenance(
                search_id=record.id,
                query_hash=record.query_hash,
                provider=hit.provider,
                selected_accession=hit.source_id,
                selection_revision=record.revision,
                retrieved_at=hit.evidence.retrieved_at,
                evidence_sha256=hit.evidence.content_sha256,
            )
            selecting = record.model_copy(
                update={
                    "status": GeoSearchStatus.SELECTING,
                    "selected_accession": accession,
                    "selection_revision": record.revision,
                    "next_page_token": None,
                }
            )
            self._write(selecting)
            # This injected boundary is the only permitted side effect.  In
            # particular, no downloader exists in this service.
            try:
                created = self._source_factory(
                    accession,
                    str(record.conversation_id),
                    str(record.turn_id),
                    provenance,
                )
                source_id = _source_id(created)
            except (GeoServiceError, GeoSearchServiceError) as error:
                self._write(record)
                raise GeoSearchServiceError(
                    getattr(error, "code", "GEO_SEARCH_SOURCE_FAILED")
                ) from error
            except Exception as error:
                self._write(record)
                raise GeoSearchServiceError("GEO_SEARCH_SOURCE_FAILED") from error
            selected = selecting.model_copy(
                update={
                    "status": GeoSearchStatus.SELECTED,
                    "revision": record.revision + 1,
                    "source_id": source_id,
                    "next_page_token": None,
                }
            )
            self._write(selected)
            return _public(selected)

    def cancel(self, search_id: UUID | str) -> dict[str, object]:
        with self._lock:
            record = self._read(search_id)
            if record.status in {
                GeoSearchStatus.SELECTED,
                GeoSearchStatus.CANCELLED,
                GeoSearchStatus.FAILED,
            }:
                return _public(record)
            self._cancelled.setdefault(record.id, Event()).set()
            cancelled = record.model_copy(
                update={
                    "status": GeoSearchStatus.CANCELLED,
                    "revision": record.revision + 1,
                    "next_page_token": None,
                }
            )
            self._write(cancelled)
            return _public(cancelled)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for cancellation in self._cancelled.values():
                cancellation.set()
            for record in self._repository.list():
                if record.status in {GeoSearchStatus.QUEUED, GeoSearchStatus.SEARCHING}:
                    self._write(
                        record.model_copy(
                            update={
                                "status": GeoSearchStatus.FAILED,
                                "revision": record.revision + 1,
                                "error_code": "GEO_SEARCH_PROCESS_RESTARTED",
                                "next_page_token": None,
                            }
                        )
                    )
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _submit(self, identity: UUID, *, first_page: bool) -> None:
        if self._closed:
            raise GeoSearchServiceError("GEO_SEARCH_SERVICE_CLOSED")
        self._assert_capacity()
        self._futures[identity] = self._executor.submit(self._run, identity, first_page)

    def _assert_capacity(self) -> None:
        active = sum(not future.done() for future in self._futures.values())
        if active >= self._max_workers + self._max_queued:
            raise GeoSearchServiceError("GEO_SEARCH_QUEUE_FULL")

    def _run(self, identity: UUID, first_page: bool) -> None:
        with self._lock:
            try:
                record = self._read(identity)
            except GeoSearchServiceError:
                return
            if (
                self._cancelled.get(identity, Event()).is_set()
                or record.status is GeoSearchStatus.CANCELLED
            ):
                return
            if first_page and record.status is GeoSearchStatus.QUEUED:
                record = record.model_copy(
                    update={"status": GeoSearchStatus.SEARCHING, "revision": record.revision + 1}
                )
                self._write(record)
            if record.status is not GeoSearchStatus.SEARCHING:
                return
        try:
            page = self._provider.search(record.query)
        except GeoSearchError as error:
            self._fail(identity, error.code)
            return
        except Exception:
            self._fail(identity, "GEO_SEARCH_UNAVAILABLE")
            return
        with self._lock:
            current = self._read(identity)
            if (
                self._cancelled.get(identity, Event()).is_set()
                or current.status is not GeoSearchStatus.SEARCHING
            ):
                return
            combined = _deduplicate((*current.items, *page.items))
            if len(combined) > 100:
                self._fail(identity, "GEO_SEARCH_OVER_LIMIT")
                return
            issued = dict(current.issued_tokens)
            opaque: str | None = None
            if page.next_page_token is not None:
                try:
                    offset = int(page.next_page_token)
                except ValueError:
                    self._fail(identity, "GEO_SEARCH_MALFORMED")
                    return
                opaque = str(uuid4())
                issued[opaque] = offset
            complete = current.model_copy(
                update={
                    "status": GeoSearchStatus.AWAITING_SELECTION,
                    "revision": current.revision + 1,
                    "items": combined,
                    "total": max(current.total, page.total),
                    "issued_tokens": issued,
                    "next_page_token": opaque,
                    "query": current.query.model_copy(update={"page_token": None}),
                }
            )
            self._write(complete)

    def _fail(self, identity: UUID, code: str) -> None:
        with self._lock:
            try:
                record = self._read(identity)
            except GeoSearchServiceError:
                return
            if record.status in {
                GeoSearchStatus.CANCELLED,
                GeoSearchStatus.SELECTED,
                GeoSearchStatus.FAILED,
            }:
                return
            self._write(
                record.model_copy(
                    update={
                        "status": GeoSearchStatus.FAILED,
                        "revision": record.revision + 1,
                        "error_code": code,
                        "next_page_token": None,
                    }
                )
            )

    def _recover_interrupted(self) -> None:
        for record in self._repository.list():
            if record.status in {
                GeoSearchStatus.QUEUED,
                GeoSearchStatus.SEARCHING,
                GeoSearchStatus.SELECTING,
            }:
                self._write(
                    record.model_copy(
                        update={
                            "status": GeoSearchStatus.FAILED,
                            "revision": record.revision + 1,
                            "error_code": "GEO_SEARCH_PROCESS_RESTARTED",
                            "next_page_token": None,
                            "selected_accession": None,
                            "selection_revision": None,
                        }
                    )
                )

    def _current(self, identity: UUID | str, revision: int) -> GeoSearchRecord:
        record = self._read(identity)
        if (
            not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision != record.revision
        ):
            raise GeoSearchServiceError("GEO_SEARCH_REVISION_CONFLICT")
        return record

    def _read(self, identity: UUID | str) -> GeoSearchRecord:
        try:
            return self._repository.read(identity)
        except FileNotFoundError as error:
            raise GeoSearchServiceError("GEO_SEARCH_NOT_FOUND") from error
        except GeoSearchRepositoryError as error:
            raise GeoSearchServiceError(error.code) from error

    def _write(self, record: GeoSearchRecord) -> None:
        self._repository.write(record)
        if self._event_sink is not None:
            self._event_sink(
                {
                    "conversation_id": str(record.conversation_id),
                    "turn_id": str(record.turn_id),
                    "kind": "geo.updated",
                    "id": str(record.id),
                    "status": record.status.value,
                    "revision": record.revision,
                    "result_count": len(record.items),
                }
            )

    def _assert_open(self) -> None:
        if self._closed:
            raise GeoSearchServiceError("GEO_SEARCH_SERVICE_CLOSED")


def _deduplicate(items: tuple[DatasetSearchHit, ...]) -> tuple[DatasetSearchHit, ...]:
    retained: list[DatasetSearchHit] = []
    seen: set[str] = set()
    for item in items:
        if item.source_id not in seen:
            retained.append(item)
            seen.add(item.source_id)
    return tuple(retained)


def _source_id(created: object) -> str:
    if isinstance(created, str) and created:
        return created
    if isinstance(created, dict):
        value = created.get("id")
        if isinstance(value, str) and value:
            return value
    raise GeoSearchServiceError("GEO_SEARCH_SOURCE_FAILED")


def _public(record: GeoSearchRecord) -> dict[str, object]:
    return {
        "id": str(record.id),
        "status": record.status.value,
        "revision": record.revision,
        "query_hash": record.query_hash,
        "query": record.query.model_dump(mode="json"),
        "items": [item.model_dump(mode="json") for item in record.items],
        "result_count": len(record.items),
        "total": record.total,
        "next_page_token": record.next_page_token,
        "source_id": record.source_id,
        "error_code": record.error_code,
    }


__all__ = ["GeoSearchService", "GeoSearchServiceError"]
