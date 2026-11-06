import asyncio
from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from inspect import signature
from threading import Event, Thread
from time import sleep
from uuid import uuid4

import pytest

from bioagent.geo.download import DownloadResult, GeoDownloader
from bioagent.geo.models import (
    Compression,
    DataKind,
    GeoCandidate,
    GeoSearchProvenance,
    GeoSource,
    SourceSelection,
)
from bioagent.geo.repository import GeoRepository, GeoRepositoryError
from bioagent.geo.search_repository import GeoSearchRecord, GeoSearchRepository, GeoSearchStatus
from bioagent.geo.service import (
    GeoImportService,
    GeoServiceError,
    _selection_digest,
    can_transition,
)
from bioagent.geo.transport import GeoTransportError
from bioagent.retrieval.contracts import DatasetSearchHit, DatasetSearchQuery, EvidenceRef
from bioagent.workbench.actions import GeoImportAction, GeoLookupAction
from bioagent.workbench.models import Conversation, Message, Turn, WorkbenchError
from bioagent.workbench.turns import TurnService


def test_download_cannot_skip_mapping_and_validation() -> None:
    assert can_transition("DOWNLOADING", "AWAITING_MAPPING")
    assert not can_transition("DOWNLOADING", "READY")
    assert not can_transition("READY", "RUNNING")


def test_terminal_states_cannot_be_revived() -> None:
    assert not can_transition("FAILED", "DOWNLOADING")
    assert not can_transition("CANCELLED", "AWAITING_MAPPING")
    assert not can_transition("UNKNOWN", "FAILED")


def test_selection_digest_is_canonical_across_mapping_key_order() -> None:
    source_id = uuid4()
    candidate_id = uuid4()
    common = {
        "source_id": source_id,
        "candidate_id": candidate_id,
        "raw_sha256": "a" * 64,
        "feature_column": "feature_id",
        "sample_columns": ("GSM1", "GSM2", "GSM3", "GSM4"),
        "groups": {"GSM1": "AD", "GSM2": "AD", "GSM3": "Control", "GSM4": "Control"},
        "numerator": "AD",
        "denominator": "Control",
        "revision": 1,
        "evidence": ("user confirmed",),
    }
    first = SourceSelection(
        **common,
        sample_map={"GSM1": "GSM1", "GSM2": "GSM2", "GSM3": "GSM3", "GSM4": "GSM4"},
    )
    second = SourceSelection(
        **common,
        sample_map={"GSM4": "GSM4", "GSM3": "GSM3", "GSM2": "GSM2", "GSM1": "GSM1"},
    )
    assert _selection_digest(first) == _selection_digest(second)


def test_service_accepts_durable_event_sink_for_progress(tmp_path) -> None:
    events: list[dict[str, object]] = []
    service = GeoImportService(
        GeoRepository(tmp_path / "sources"), object(), object(), object(), event_sink=events.append
    )
    service.close()


class _Discovery:
    def __init__(self) -> None:
        self.calls = 0

    def discover(self, accession: str) -> GeoSource:
        self.calls += 1
        source_id = uuid4()
        candidate = GeoCandidate(
            id=uuid4(),
            source_id=source_id,
            accession=accession,
            url="https://www.ncbi.nlm.nih.gov/example.tsv",
            file_name="counts.tsv",
            data_kind=DataKind.RAW_COUNTS,
            evidence=("fixture",),
            compression=Compression.NONE,
        )
        return GeoSource(
            id=source_id,
            accession=accession,
            candidates=(candidate,),
            retrieved_at=datetime.now(UTC),
        )


def _search_provenance(search_id, *, evidence_sha256: str = "b" * 64) -> GeoSearchProvenance:
    return GeoSearchProvenance(
        search_id=search_id,
        query_hash=DatasetSearchQuery(text="brain").query_hash,
        provider="geo",
        selected_accession="GSE123",
        selection_revision=3,
        retrieved_at="2026-09-14T00:00:00Z",
        evidence_sha256=evidence_sha256,
    )


def _search_snapshot(
    provenance: GeoSearchProvenance, *, status: GeoSearchStatus
) -> GeoSearchRecord:
    query = DatasetSearchQuery(text="brain")
    selection_is_persisted = status in {GeoSearchStatus.SELECTING, GeoSearchStatus.SELECTED}
    return GeoSearchRecord(
        id=provenance.search_id,
        status=status,
        revision=(
            provenance.selection_revision + 1
            if status is GeoSearchStatus.SELECTED
            else provenance.selection_revision
        ),
        query=query,
        query_hash=query.query_hash,
        items=(
            DatasetSearchHit(
                provider="geo",
                source_id=provenance.selected_accession,
                title="fixture",
                source_uri="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE123",
                evidence=EvidenceRef(
                    provider="geo",
                    source_id=provenance.selected_accession,
                    source_uri="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE123",
                    retrieved_at=provenance.retrieved_at,
                    content_sha256="b" * 64,
                ),
            ),
        ),
        total=1,
        conversation_id=uuid4(),
        turn_id=uuid4(),
        source_id="source-id" if status is GeoSearchStatus.SELECTED else None,
        selected_accession=(provenance.selected_accession if selection_is_persisted else None),
        selection_revision=(provenance.selection_revision if selection_is_persisted else None),
    )


def test_create_source_rejects_direct_forged_search_provenance(tmp_path) -> None:
    search_repository = GeoSearchRepository(tmp_path / "data" / "searches")
    provenance = _search_provenance(uuid4(), evidence_sha256="c" * 64)
    search_repository.write(_search_snapshot(provenance, status=GeoSearchStatus.AWAITING_SELECTION))
    service = GeoImportService(
        GeoRepository(tmp_path / "sources"),
        _Discovery(),
        object(),
        object(),
        search_repository=search_repository,
    )

    with pytest.raises(GeoServiceError, match="^GEO_SEARCH_PROVENANCE_INVALID$"):
        service.create_source("GSE123", provenance=provenance)

    service.close()


def test_validation_rechecks_mutated_source_provenance_before_dataset_publication(
    tmp_path, monkeypatch
) -> None:
    repository = GeoRepository(tmp_path / "sources")
    search_repository = GeoSearchRepository(tmp_path / "data" / "searches")
    source_id, candidate_id, import_id = uuid4(), uuid4(), uuid4()
    authentic = _search_provenance(uuid4())
    selected = _search_snapshot(authentic, status=GeoSearchStatus.SELECTED)
    search_repository.write(selected)
    candidate = GeoCandidate(
        id=candidate_id,
        source_id=source_id,
        accession="GSE123",
        url="https://www.ncbi.nlm.nih.gov/counts.tsv",
        file_name="counts.tsv",
        data_kind=DataKind.RAW_COUNTS,
        evidence=("fixture",),
        compression=Compression.NONE,
    )
    source = GeoSource(
        id=source_id,
        accession="GSE123",
        candidates=(candidate,),
        retrieved_at=datetime.now(UTC),
    )
    selection = SourceSelection(
        source_id=source_id,
        candidate_id=candidate_id,
        raw_sha256="a" * 64,
        feature_column="feature_id",
        sample_columns=("GSM1", "GSM2", "GSM3", "GSM4"),
        sample_map={name: name for name in ("GSM1", "GSM2", "GSM3", "GSM4")},
        groups={"GSM1": "AD", "GSM2": "AD", "GSM3": "Control", "GSM4": "Control"},
        numerator="AD",
        denominator="Control",
        revision=1,
        evidence=("confirmed",),
    )
    repository.write_state(
        "sources",
        source_id,
        {
            "id": str(source_id),
            "source": source.model_dump(mode="json"),
            "search_provenance": _search_provenance(
                authentic.search_id, evidence_sha256="c" * 64
            ).model_dump(mode="json"),
        },
    )
    repository.write_state(
        "imports",
        import_id,
        {
            "id": str(import_id),
            "source_id": str(source_id),
            "candidate_id": str(candidate_id),
            "status": "VALIDATING",
            "raw_path": str(tmp_path / "raw.tsv"),
            "selection": selection.model_dump(mode="json"),
        },
    )
    (tmp_path / "raw.tsv").write_text("fixture", encoding="utf-8")

    class Datasets:
        calls = 0

        def import_geo(self, _normalized):
            self.calls += 1
            raise AssertionError("must not import a dataset from tampered provenance")

    datasets = Datasets()
    service = GeoImportService(
        repository,
        object(),
        object(),
        datasets,
        search_repository=search_repository,
    )  # type: ignore[arg-type]
    repository.write_state(
        "imports",
        import_id,
        {
            "id": str(import_id),
            "source_id": str(source_id),
            "candidate_id": str(candidate_id),
            "status": "VALIDATING",
            "raw_path": str(tmp_path / "raw.tsv"),
            "selection": selection.model_dump(mode="json"),
        },
    )
    monkeypatch.setattr("bioagent.geo.service.transform_selection", lambda *_args: object())

    service._validate_locked(import_id)

    assert datasets.calls == 0
    assert service.get_import(import_id)["status"] == "FAILED"
    assert service.get_import(import_id)["error_code"] == "GEO_SEARCH_PROVENANCE_INVALID"
    service.close()


def test_discovery_state_and_event_are_persistent_without_restart_replay(tmp_path) -> None:
    discovery = _Discovery()
    events: list[dict[str, object]] = []
    service = GeoImportService(
        GeoRepository(tmp_path / "sources"), discovery, object(), object(), event_sink=events.append
    )
    source = service.create_source("GSE123", conversation_id=str(uuid4()), turn_id=str(uuid4()))
    for _ in range(50):
        source = service.get_source(str(source["id"]))
        if source["status"] == "AWAITING_SELECTION":
            break
        sleep(0.01)
    service.close()
    assert source["status"] == "AWAITING_SELECTION"
    assert discovery.calls == 1
    assert [event["status"] for event in events] == ["DISCOVERING", "AWAITING_SELECTION"]

    restarted = GeoImportService(
        GeoRepository(tmp_path / "sources"), discovery, object(), object(), event_sink=events.append
    )
    assert restarted.get_source(str(source["id"]))["status"] == "AWAITING_SELECTION"
    assert discovery.calls == 1
    restarted.close()


def test_discovery_transport_failure_is_persisted_as_terminal_error(tmp_path) -> None:
    class FailingDiscovery:
        def discover(self, _accession: str):
            raise GeoTransportError("DOWNLOAD_DNS_FAILED")

    service = GeoImportService(
        GeoRepository(tmp_path / "sources"), FailingDiscovery(), object(), object()
    )
    source = service.create_source("GSE123")
    for _ in range(50):
        source = service.get_source(source["id"])
        if source["status"] == "FAILED":
            break
        sleep(0.01)
    assert source["status"] == "FAILED"
    assert source["error_code"] == "DOWNLOAD_DNS_FAILED"
    service.close()


def test_queue_full_marks_new_source_failed_instead_of_leaving_it_discovering(tmp_path) -> None:
    service = GeoImportService(
        GeoRepository(tmp_path / "sources"), object(), object(), object(), max_queued=1
    )
    service._futures = {uuid4(): Future(), uuid4(): Future(), uuid4(): Future()}  # type: ignore[attr-defined]
    source = service.create_source("GSE123")
    assert source["status"] == "FAILED"
    assert source["error_code"] == "GEO_QUEUE_FULL"
    service.close()


def test_same_selection_is_idempotent_while_validating_or_ready(tmp_path) -> None:
    repository = GeoRepository(tmp_path / "sources")
    service = GeoImportService(repository, object(), object(), object())
    source_id = uuid4()
    candidate_id = uuid4()
    selection = SourceSelection(
        source_id=source_id,
        candidate_id=candidate_id,
        raw_sha256="a" * 64,
        feature_column="feature_id",
        sample_columns=("GSM1", "GSM2", "GSM3", "GSM4"),
        sample_map={name: name for name in ("GSM1", "GSM2", "GSM3", "GSM4")},
        groups={"GSM1": "AD", "GSM2": "AD", "GSM3": "Control", "GSM4": "Control"},
        numerator="AD",
        denominator="Control",
        revision=1,
        evidence=("confirmed",),
    )
    import_id = uuid4()
    state = {
        "id": str(import_id),
        "source_id": str(source_id),
        "candidate_id": str(candidate_id),
        "revision": 1,
        "status": "VALIDATING",
        "raw_sha256": "a" * 64,
        "selection": selection.model_dump(mode="json"),
        "selection_hash": _selection_digest(selection),
    }
    repository.write_state("imports", import_id, state)
    assert service.submit_selection(import_id, selection)["status"] == "VALIDATING"
    ready = {**state, "status": "READY", "dataset_id": str(uuid4())}
    repository.write_state("imports", import_id, ready)
    assert service.submit_selection(import_id, selection)["status"] == "READY"
    changed = selection.model_copy(update={"revision": 2})
    try:
        service.submit_selection(import_id, changed)
    except GeoServiceError as error:
        assert error.code == "SOURCE_SELECTION_CONFLICT"
    else:
        raise AssertionError("changed selection must not reuse READY import")
    service.close()


def test_downloader_exposes_incremental_progress_callback() -> None:
    assert "progress" in signature(GeoDownloader.download).parameters


def test_restart_marks_interrupted_import_failed_without_replaying_network(tmp_path) -> None:
    repository = GeoRepository(tmp_path / "sources")
    import_id = uuid4()
    repository.write_state(
        "imports",
        import_id,
        {"id": str(import_id), "status": "DOWNLOADING", "source_id": str(uuid4())},
    )
    discovery = _Discovery()
    service = GeoImportService(repository, discovery, object(), object())
    state = service.get_import(import_id)
    assert state["status"] == "FAILED"
    assert state["error_code"] == "GEO_PROCESS_RESTARTED"
    assert discovery.calls == 0
    service.close()


def test_cancel_is_idempotent_and_never_revives_a_download(tmp_path) -> None:
    repository = GeoRepository(tmp_path / "sources")
    import_id = uuid4()
    repository.write_state(
        "imports",
        import_id,
        {"id": str(import_id), "status": "DOWNLOADING", "source_id": str(uuid4())},
    )
    service = GeoImportService(repository, object(), object(), object())
    # Startup recovery is terminal; a cancellation race cannot revive it.
    first = service.cancel(import_id)
    second = service.cancel(import_id)
    assert first["status"] == second["status"] == "FAILED"
    assert first["error_code"] == "GEO_PROCESS_RESTARTED"
    service.close()


def test_refusing_a_source_never_constructs_an_import_or_download(tmp_path) -> None:
    repository = GeoRepository(tmp_path / "sources")
    service = GeoImportService(repository, object(), object(), object())
    source_id = uuid4()
    repository.write_state(
        "sources",
        source_id,
        {"id": str(source_id), "status": "AWAITING_SELECTION", "revision": 1, "source": None},
    )
    assert repository.list_states("imports") == ()
    service.close()


def test_geo_import_action_rejects_another_conversations_selected_source() -> None:
    now = datetime.now(UTC)
    turn = Turn(
        id=uuid4(),
        conversation_id=uuid4(),
        client_request_id=uuid4(),
        created_at=now,
        updated_at=now,
    )
    selected = uuid4()
    action = GeoImportAction(kind="geo_import", source_id=uuid4(), candidate_id=uuid4(), revision=1)

    class Store:
        def get_conversation(self, _identity):
            return Conversation(
                id=turn.conversation_id,
                project_id=uuid4(),
                title="chat",
                geo_source_id=selected,
                created_at=now,
                updated_at=now,
            )

    service = TurnService(Store(), lambda *_: None)  # type: ignore[arg-type]
    try:
        asyncio.run(service._run_geo_import_suggestion(turn, action))
    except WorkbenchError as error:
        assert error.code == "GEO_SOURCE_NOT_SELECTED"
    else:
        raise AssertionError("cross-session source must be rejected")


def test_ready_handoff_creates_approval_run_without_statistical_attempt() -> None:
    now = datetime.now(UTC)
    turn = Turn(
        id=uuid4(),
        conversation_id=uuid4(),
        client_request_id=uuid4(),
        created_at=now,
        updated_at=now,
    )

    class Store:
        def __init__(self) -> None:
            self.run_id = None
            self.events = []

        def get_turn(self, _identity):
            return turn

        def list_messages(self, _identity, limit=20):
            message = Message(
                id=uuid4(),
                conversation_id=turn.conversation_id,
                turn_id=turn.id,
                role="user",
                content="compare AD",
                created_at=now,
                updated_at=now,
            )
            return type("Page", (), {"items": (message,)})()

        def set_run_id(self, _turn_id, run_id):
            self.run_id = run_id

        def append_event(self, *_args):
            self.events.append(_args)

    class Analysis:
        attempts = 0

        def create_run(self, **kwargs):
            assert kwargs["dataset_id"] == "dataset-1"
            return str(uuid4())

    store, analysis = Store(), Analysis()
    service = TurnService(store, lambda *_: None, analysis=analysis)  # type: ignore[arg-type]
    service.resume_geo_ready(
        {
            "dataset_id": "dataset-1",
            "published_source_id": str(uuid4()),
            "context": {"turn_id": str(turn.id), "conversation_id": str(turn.conversation_id)},
        }
    )
    assert store.run_id is not None
    assert analysis.attempts == 0
    assert store.events[-1][2] == "run.updated"


def test_cancel_race_waits_for_validation_publication_then_returns_ready(tmp_path) -> None:
    repository = GeoRepository(tmp_path / "sources")
    import_id = uuid4()
    service = GeoImportService(repository, object(), object(), object())
    repository.write_state("imports", import_id, {"id": str(import_id), "status": "VALIDATING"})
    entered, release, cancelled = Event(), Event(), Event()

    def publish(_identity) -> None:
        entered.set()
        assert release.wait(2)
        repository.write_state("imports", import_id, {"id": str(import_id), "status": "READY"})

    service._validate_locked = publish  # type: ignore[method-assign]
    validation = Thread(target=service._validate, args=(import_id,))
    validation.start()
    assert entered.wait(2)
    result: dict[str, object] = {}

    def cancel() -> None:
        result.update(service.cancel(import_id))
        cancelled.set()

    cancelling = Thread(target=cancel)
    cancelling.start()
    assert not cancelled.wait(0.05)
    release.set()
    validation.join(2)
    cancelling.join(2)
    assert result["status"] == "READY"
    service.close()


def test_repeat_import_request_reuses_import_and_starts_downloader_once(tmp_path) -> None:
    class BlockingDownloader:
        def __init__(self) -> None:
            self.calls = 0
            self.started, self.release = Event(), Event()

        def download(self, _url, destination, *, cancel_event=None, progress=None):
            self.calls += 1
            self.started.set()
            assert self.release.wait(2)
            content = b"feature_id\nGeneA\n"
            destination.write_bytes(content)
            if progress is not None:
                progress(len(content))
            return DownloadResult(
                destination, sha256(content).hexdigest(), len(content), None, None, None
            )

    repository = GeoRepository(tmp_path / "sources")
    discovery, downloader = _Discovery(), BlockingDownloader()
    service = GeoImportService(repository, discovery, downloader, object())
    source = service.create_source("GSE123")
    for _ in range(50):
        source = service.get_source(str(source["id"]))
        if source["status"] == "AWAITING_SELECTION":
            break
        sleep(0.01)
    candidate_id = source["source"]["candidates"][0]["id"]
    first = service.request_import(source["id"], candidate_id, 1)
    assert downloader.started.wait(2)
    second = service.request_import(source["id"], candidate_id, 1)
    assert first["id"] == second["id"]
    assert downloader.calls == 1
    downloader.release.set()
    service.close()


def test_publish_failure_discards_new_dataset_before_failing_import(tmp_path, monkeypatch) -> None:
    repository = GeoRepository(tmp_path / "sources")
    source_id, candidate_id, import_id = uuid4(), uuid4(), uuid4()
    candidate = GeoCandidate(
        id=candidate_id,
        source_id=source_id,
        accession="GSE123",
        url="https://www.ncbi.nlm.nih.gov/counts.tsv",
        file_name="counts.tsv",
        data_kind=DataKind.RAW_COUNTS,
        evidence=("fixture",),
        compression=Compression.NONE,
    )
    source = GeoSource(
        id=source_id,
        accession="GSE123",
        candidates=(candidate,),
        retrieved_at=datetime.now(UTC),
    )
    selection = SourceSelection(
        source_id=source_id,
        candidate_id=candidate_id,
        raw_sha256="a" * 64,
        feature_column="feature_id",
        sample_columns=("GSM1", "GSM2", "GSM3", "GSM4"),
        sample_map={name: name for name in ("GSM1", "GSM2", "GSM3", "GSM4")},
        groups={"GSM1": "AD", "GSM2": "AD", "GSM3": "Control", "GSM4": "Control"},
        numerator="AD",
        denominator="Control",
        revision=1,
        evidence=("confirmed",),
    )
    raw_path = tmp_path / "raw.tsv"
    raw_path.write_text("fixture", encoding="utf-8")
    class Datasets:
        discarded: list[str] = []

        def import_geo(self, _normalized):
            return "11111111-1111-4111-8111-111111111111"

        def discard_dataset(self, dataset_id):
            self.discarded.append(dataset_id)

    datasets = Datasets()
    service = GeoImportService(repository, object(), object(), datasets)  # type: ignore[arg-type]
    repository.write_state(
        "sources", source_id, {"id": str(source_id), "source": source.model_dump(mode="json")}
    )
    repository.write_state(
        "imports",
        import_id,
        {
            "id": str(import_id),
            "source_id": str(source_id),
            "candidate_id": str(candidate_id),
            "status": "VALIDATING",
            "raw_path": str(raw_path),
            "selection": selection.model_dump(mode="json"),
        },
    )

    monkeypatch.setattr("bioagent.geo.service.transform_selection", lambda *_args: object())
    monkeypatch.setattr(
        repository,
        "publish",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(GeoRepositoryError("PUBLISH_FAILED")),
    )
    service._validate_locked(import_id)
    assert datasets.discarded == ["11111111-1111-4111-8111-111111111111"]
    assert service.get_import(import_id)["status"] == "FAILED"
    service.close()


def test_close_terminalizes_inflight_state_before_dependency_shutdown(tmp_path) -> None:
    repository = GeoRepository(tmp_path / "sources")
    service = GeoImportService(repository, object(), object(), object())
    import_id = uuid4()
    repository.write_state(
        "imports",
        import_id,
        {"id": str(import_id), "status": "DOWNLOADING", "bytes_downloaded": 10},
    )
    service.close()
    state = repository.read_state("imports", import_id)
    assert state["status"] == "FAILED"
    assert state["error_code"] == "GEO_SERVICE_CLOSED"


def test_malformed_download_state_fails_with_stable_error(tmp_path) -> None:
    repository = GeoRepository(tmp_path / "sources")
    import_id = uuid4()
    service = GeoImportService(repository, object(), object(), object())
    repository.write_state(
        "imports",
        import_id,
        {
            "id": str(import_id),
            "source_id": str(uuid4()),
            "candidate_id": str(uuid4()),
            "status": "DOWNLOADING",
        },
    )
    service._download(import_id)
    state = service.get_import(import_id)
    assert state["status"] == "FAILED"
    assert state["error_code"] == "GEO_SOURCE_NOT_FOUND"
    service.close()


def test_cancel_wins_download_completion_without_reviving_import(tmp_path, monkeypatch) -> None:
    repository = GeoRepository(tmp_path / "sources")
    source_id, candidate_id, import_id = uuid4(), uuid4(), uuid4()
    candidate = GeoCandidate(
        id=candidate_id,
        source_id=source_id,
        accession="GSE123",
        url="https://www.ncbi.nlm.nih.gov/counts.tsv",
        file_name="counts.tsv",
        data_kind=DataKind.RAW_COUNTS,
        evidence=("fixture",),
        compression=Compression.NONE,
    )
    source = GeoSource(
        id=source_id,
        accession="GSE123",
        candidates=(candidate,),
        retrieved_at=datetime.now(UTC),
    )
    repository.write_state(
        "sources", source_id, {"id": str(source_id), "source": source.model_dump(mode="json")}
    )
    repository.write_state(
        "imports",
        import_id,
        {
            "id": str(import_id),
            "source_id": str(source_id),
            "candidate_id": str(candidate_id),
            "status": "AWAITING_MAPPING",
            "bytes_downloaded": 0,
        },
    )
    started, release = Event(), Event()

    class Downloader:
        def download(self, _url, destination, *, cancel_event=None, progress=None):
            started.set()
            assert release.wait(2)
            destination.write_bytes(b"temporary")
            return DownloadResult(destination, "a" * 64, 9, None, None, None)

    monkeypatch.setattr("bioagent.geo.service.preview_mapping", lambda *_args: object())
    monkeypatch.setattr("bioagent.geo.service._preview", lambda _value: {})
    service = GeoImportService(repository, object(), Downloader(), object())  # type: ignore[arg-type]
    repository.write_state(
        "imports",
        import_id,
        {**repository.read_state("imports", import_id), "status": "DOWNLOADING"},
    )
    worker = Thread(target=service._download, args=(import_id,))
    worker.start()
    assert started.wait(2)
    assert service.cancel(import_id)["status"] == "CANCELLED"
    release.set()
    worker.join(2)
    assert service.get_import(import_id)["status"] == "CANCELLED"
    assert not list((tmp_path / "sources" / ".geo-downloads" / str(import_id)).glob("*"))
    service.close()


def test_close_does_not_allow_completed_discovery_to_revive_failure(tmp_path) -> None:
    started, release = Event(), Event()

    class BlockingDiscovery(_Discovery):
        def discover(self, accession: str) -> GeoSource:
            started.set()
            assert release.wait(2)
            return super().discover(accession)

    repository = GeoRepository(tmp_path / "sources")
    service = GeoImportService(repository, BlockingDiscovery(), object(), object())
    source = service.create_source("GSE123")
    assert started.wait(2)
    closer = Thread(target=service.close)
    closer.start()
    sleep(0.02)
    release.set()
    closer.join(2)
    assert service.get_source(source["id"])["status"] == "FAILED"
    assert service.get_source(source["id"])["error_code"] == "GEO_SERVICE_CLOSED"


def test_multi_gse_lookup_requires_user_choice_without_discovery() -> None:
    now = datetime.now(UTC)
    turn = Turn(
        id=uuid4(),
        conversation_id=uuid4(),
        client_request_id=uuid4(),
        created_at=now,
        updated_at=now,
    )

    class Geo:
        calls = 0

        def create_source(self, *_args, **_kwargs):
            self.calls += 1
            return {}

    class Store:
        def __init__(self) -> None:
            self.questions = []

        def list_messages(self, *_args, **_kwargs):
            message = Message(
                id=uuid4(),
                conversation_id=turn.conversation_id,
                turn_id=turn.id,
                role="user",
                content="Please analyse GSE123 and  gse456",
                created_at=now,
                updated_at=now,
            )
            return type("Page", (), {"items": (message,)})()

        def require_input(self, _turn_id, question):
            self.questions.append(question)

    store, geo = Store(), Geo()
    service = TurnService(store, lambda *_: None, geo=geo)  # type: ignore[arg-type]
    action = GeoLookupAction(kind="geo_lookup", accession="GSE123")
    asyncio.run(service._run_geo_lookup(turn, action))
    assert geo.calls == 0
    assert store.questions and "GSE123" in store.questions[0] and "GSE456" in store.questions[0]


def test_multi_gse_lookup_accepts_the_follow_up_choice() -> None:
    now = datetime.now(UTC)
    conversation_id, turn_id = uuid4(), uuid4()
    turn = Turn(
        id=turn_id,
        conversation_id=conversation_id,
        client_request_id=uuid4(),
        created_at=now,
        updated_at=now,
    )
    messages = (
        Message(
            id=uuid4(),
            conversation_id=conversation_id,
            turn_id=turn_id,
            role="user",
            content="Compare GSE123 and GSE456",
            created_at=now,
            updated_at=now,
        ),
        Message(
            id=uuid4(),
            conversation_id=conversation_id,
            turn_id=turn_id,
            role="user",
            content="I choose GSE123",
            created_at=now,
            updated_at=now + timedelta(microseconds=1),
        ),
    )

    class Geo:
        def __init__(self) -> None:
            self.calls = 0

        def create_source(self, accession, **_context):
            self.calls += 1
            return {"id": str(uuid4()), "accession": accession}

    class Store:
        def __init__(self) -> None:
            self.questions: list[str] = []

        def list_messages(self, *_args, **_kwargs):
            return type("Page", (), {"items": messages})()

        def set_geo_source(self, _conversation_id, _source_id):
            return None

        def append_event(self, *_args):
            return None

        def require_input(self, _turn_id, question):
            self.questions.append(question)

    geo, store = Geo(), Store()
    service = TurnService(store, lambda *_: None, geo=geo)  # type: ignore[arg-type]
    asyncio.run(
        service._run_geo_lookup(
            turn, GeoLookupAction(kind="geo_lookup", accession="GSE123")
        )
    )
    assert geo.calls == 1
    assert store.questions == ["请在 GEO 来源卡中确认可下载的 counts 候选文件。"]


def test_geo_lookup_without_user_accession_never_discovers() -> None:
    now = datetime.now(UTC)
    turn = Turn(
        id=uuid4(), conversation_id=uuid4(), client_request_id=uuid4(),
        created_at=now, updated_at=now,
    )

    class Geo:
        calls = 0

        def create_source(self, *_args, **_kwargs):
            self.calls += 1
            return {}

    class Store:
        def __init__(self) -> None:
            self.questions: list[str] = []

        def list_messages(self, *_args, **_kwargs):
            message = Message(
                id=uuid4(), conversation_id=turn.conversation_id, turn_id=turn.id,
                role="user", content="Please inspect the public study",
                created_at=now, updated_at=now,
            )
            return type("Page", (), {"items": (message,)})()

        def require_input(self, _turn_id, question):
            self.questions.append(question)

    store, geo = Store(), Geo()
    service = TurnService(store, lambda *_: None, geo=geo)  # type: ignore[arg-type]
    asyncio.run(
        service._run_geo_lookup(turn, GeoLookupAction(kind="geo_lookup", accession="GSE123"))
    )
    assert geo.calls == 0
    assert store.questions


def test_geo_lookup_must_match_current_user_accession() -> None:
    now = datetime.now(UTC)
    turn = Turn(
        id=uuid4(), conversation_id=uuid4(), client_request_id=uuid4(),
        created_at=now, updated_at=now,
    )

    class Geo:
        calls = 0

        def create_source(self, *_args, **_kwargs):
            self.calls += 1
            return {}

    class Store:
        def __init__(self) -> None:
            self.questions: list[str] = []

        def list_messages(self, *_args, **_kwargs):
            message = Message(
                id=uuid4(), conversation_id=turn.conversation_id, turn_id=turn.id,
                role="user", content="Please inspect GSE123", created_at=now, updated_at=now,
            )
            return type("Page", (), {"items": (message,)})()

        def require_input(self, _turn_id, question):
            self.questions.append(question)

    store, geo = Store(), Geo()
    service = TurnService(store, lambda *_: None, geo=geo)  # type: ignore[arg-type]
    asyncio.run(
        service._run_geo_lookup(turn, GeoLookupAction(kind="geo_lookup", accession="GSE456"))
    )
    assert geo.calls == 0
    assert store.questions


def test_prior_turn_gse_does_not_block_current_single_lookup() -> None:
    now = datetime.now(UTC)
    conversation_id = uuid4()
    prior_turn_id, current_turn_id = uuid4(), uuid4()
    turn = Turn(
        id=current_turn_id,
        conversation_id=conversation_id,
        client_request_id=uuid4(),
        created_at=now,
        updated_at=now,
    )

    class Geo:
        def __init__(self) -> None:
            self.calls = 0

        def create_source(self, accession, **_context):
            self.calls += 1
            assert accession == "GSE456"
            return {"id": str(uuid4())}

    class Store:
        def __init__(self) -> None:
            self.questions = []

        def list_messages(self, *_args, **_kwargs):
            messages = (
                Message(
                    id=uuid4(),
                    conversation_id=conversation_id,
                    turn_id=prior_turn_id,
                    role="user",
                    content="Earlier, I mentioned GSE123",
                    created_at=now,
                    updated_at=now,
                ),
                Message(
                    id=uuid4(),
                    conversation_id=conversation_id,
                    turn_id=current_turn_id,
                    role="user",
                    content="Now analyse gse456",
                    created_at=now,
                    updated_at=now,
                ),
            )
            return type("Page", (), {"items": messages})()

        def set_geo_source(self, *_args):
            return None

        def append_event(self, *_args):
            return None

        def require_input(self, _turn_id, question):
            self.questions.append(question)

    store, geo = Store(), Geo()
    service = TurnService(store, lambda *_: None, geo=geo)  # type: ignore[arg-type]
    asyncio.run(
        service._run_geo_lookup(turn, GeoLookupAction(kind="geo_lookup", accession="GSE456"))
    )
    assert geo.calls == 1
    assert store.questions == ["请在 GEO 来源卡中确认可下载的 counts 候选文件。"]


def test_prior_turn_gse_does_not_block_current_single_gse_lookup() -> None:
    now = datetime.now(UTC)
    conversation_id, prior_turn_id, turn_id, source_id = uuid4(), uuid4(), uuid4(), uuid4()
    turn = Turn(
        id=turn_id,
        conversation_id=conversation_id,
        client_request_id=uuid4(),
        created_at=now,
        updated_at=now,
    )

    class Geo:
        calls = 0

        def create_source(self, *_args, **_kwargs):
            self.calls += 1
            return {"id": str(source_id)}

    class Store:
        def __init__(self) -> None:
            self.questions: list[str] = []

        def list_messages(self, *_args, **_kwargs):
            prior = Message(
                id=uuid4(),
                conversation_id=conversation_id,
                turn_id=prior_turn_id,
                role="user",
                content="Analyse GSE123",
                created_at=now,
                updated_at=now,
            )
            current = prior.model_copy(
                update={"id": uuid4(), "turn_id": turn_id, "content": "Analyse GSE456"}
            )
            return type("Page", (), {"items": (prior, current)})()

        def set_geo_source(self, *_args):
            return None

        def append_event(self, *_args):
            return None

        def require_input(self, _turn_id, question):
            self.questions.append(question)

    store, geo = Store(), Geo()
    service = TurnService(store, lambda *_: None, geo=geo)  # type: ignore[arg-type]
    action = GeoLookupAction(kind="geo_lookup", accession="GSE456")
    asyncio.run(service._run_geo_lookup(turn, action))
    assert geo.calls == 1
    assert store.questions == ["请在 GEO 来源卡中确认可下载的 counts 候选文件。"]
