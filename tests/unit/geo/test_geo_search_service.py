from time import sleep
from uuid import uuid4

import pytest

from bioagent.geo.models import GeoSearchProvenance
from bioagent.geo.search_repository import (
    GeoSearchRecord,
    GeoSearchRepository,
    GeoSearchStatus,
)
from bioagent.geo.search_service import GeoSearchService, GeoSearchServiceError
from bioagent.retrieval.contracts import (
    DatasetSearchHit,
    DatasetSearchPage,
    DatasetSearchQuery,
    EvidenceRef,
)


class Catalog:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: DatasetSearchQuery) -> DatasetSearchPage:
        self.calls += 1
        return DatasetSearchPage(
            items=(
                DatasetSearchHit(
                    provider="geo",
                    source_id="GSE12345",
                    title="fixture",
                    source_uri="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345",
                    evidence=EvidenceRef.fixture("geo", "GSE12345"),
                ),
            ),
            total=1,
        )


def _wait(service: GeoSearchService, identity: str) -> dict[str, object]:
    for _ in range(100):
        state = service.get(identity)
        if state["status"] not in {"QUEUED", "SEARCHING"}:
            return state
        sleep(0.01)
    raise AssertionError("search did not finish")


def test_search_persists_restart_marks_active_failed_and_selection_only_creates_source(
    tmp_path,
) -> None:
    created: list[tuple[str, str, str, GeoSearchProvenance]] = []
    catalog = Catalog()
    def create_source(
        accession: str,
        conversation_id: str,
        turn_id: str,
        provenance: GeoSearchProvenance,
    ) -> str:
        created.append((accession, conversation_id, turn_id, provenance))
        return "source-id"

    service = GeoSearchService(tmp_path / "data", catalog, create_source)
    conversation_id, turn_id = str(uuid4()), str(uuid4())
    started = service.create(DatasetSearchQuery(text="brain"), conversation_id, turn_id)
    state = _wait(service, str(started["id"]))
    assert state["status"] == "AWAITING_SELECTION"
    selected = service.select(str(state["id"]), "GSE12345", int(state["revision"]))
    assert selected["status"] == "SELECTED"
    assert selected["source_id"] == "source-id"
    assert [(accession, conversation, turn) for accession, conversation, turn, _ in created] == [
        ("GSE12345", conversation_id, turn_id)
    ]
    provenance = created[0][3]
    assert str(provenance.search_id) == state["id"]
    assert provenance.query_hash == state["query_hash"]
    assert provenance.selected_accession == "GSE12345"
    assert provenance.selection_revision == state["revision"]
    assert provenance.evidence_sha256 == state["items"][0]["evidence"]["content_sha256"]
    with pytest.raises(GeoSearchServiceError, match="^GEO_SEARCH_REVISION_CONFLICT$"):
        service.select(str(state["id"]), "GSE12345", 1)
    service.close()

    restarted = GeoSearchService(tmp_path / "data", catalog, lambda *_: "unused")
    assert restarted.get(str(state["id"]))["status"] == "SELECTED"
    restarted.close()


def test_page_tokens_are_hash_bound_and_cancelled_search_does_not_select(tmp_path) -> None:
    service = GeoSearchService(tmp_path / "data", Catalog(), lambda *_: "source-id")
    started = service.create(DatasetSearchQuery(text="brain"), str(uuid4()), str(uuid4()))
    state = _wait(service, str(started["id"]))
    with pytest.raises(GeoSearchServiceError, match="^GEO_SEARCH_PAGE_TOKEN_INVALID$"):
        service.next_page(str(state["id"]), "made-up", int(state["revision"]))
    cancelled = service.cancel(str(state["id"]))
    assert cancelled["status"] == "CANCELLED"
    with pytest.raises(GeoSearchServiceError, match="^GEO_SEARCH_NOT_SELECTABLE$"):
        service.select(str(state["id"]), "GSE12345", int(cancelled["revision"]))
    service.close()


def test_agent_search_recovery_is_bound_to_its_conversation(tmp_path) -> None:
    service = GeoSearchService(tmp_path / "data", Catalog(), lambda *_: "source-id")
    conversation_id, turn_id = str(uuid4()), str(uuid4())
    agent_search = service.create(DatasetSearchQuery(text="brain"), conversation_id, turn_id)
    direct_search = service.create(
        DatasetSearchQuery(text="liver"),
        str(uuid4()),
        str(uuid4()),
        owner_token_sha256="a" * 64,
    )

    assert service.is_conversation_search(str(agent_search["id"]), conversation_id)
    assert not service.is_conversation_search(str(agent_search["id"]), str(uuid4()))
    assert not service.is_conversation_search(str(direct_search["id"]), conversation_id)
    service.close()


def test_restart_marks_only_in_progress_search_failed_and_source_failure_keeps_snapshot(
    tmp_path,
) -> None:
    query = DatasetSearchQuery(text="brain")
    identity, conversation_id, turn_id = uuid4(), uuid4(), uuid4()
    repository = GeoSearchRepository(tmp_path / "data" / "searches")
    repository.write(
        GeoSearchRecord(
            id=identity,
            status="SEARCHING",
            revision=4,
            query=query,
            query_hash=query.query_hash,
            conversation_id=conversation_id,
            turn_id=turn_id,
        )
    )
    restarted = GeoSearchService(tmp_path / "data", Catalog(), lambda *_: "unused")
    recovered = restarted.get(str(identity))
    assert recovered["status"] == "FAILED"
    assert recovered["error_code"] == "GEO_SEARCH_PROCESS_RESTARTED"
    restarted.close()

    def fail_source(*_args: object) -> str:
        raise RuntimeError

    service = GeoSearchService(tmp_path / "separate", Catalog(), fail_source)
    state = _wait(service, str(service.create(query, str(uuid4()), str(uuid4()))["id"]))
    with pytest.raises(GeoSearchServiceError, match="^GEO_SEARCH_SOURCE_FAILED$"):
        service.select(str(state["id"]), "GSE12345", int(state["revision"]))
    assert service.get(str(state["id"]))["status"] == "AWAITING_SELECTION"
    service.close()


def test_restart_clears_interrupted_selection_evidence_and_remains_readable(
    tmp_path,
) -> None:
    query = DatasetSearchQuery(text="brain")
    identity = uuid4()
    repository = GeoSearchRepository(tmp_path / "data" / "searches")
    hit = Catalog().search(query).items[0]
    repository.write(
        GeoSearchRecord(
            id=identity,
            status=GeoSearchStatus.SELECTING,
            revision=4,
            query=query,
            query_hash=query.query_hash,
            items=(hit,),
            total=1,
            conversation_id=uuid4(),
            turn_id=uuid4(),
            selected_accession=hit.source_id,
            selection_revision=4,
        )
    )

    restarted = GeoSearchService(tmp_path / "data", Catalog(), lambda *_: "unused")
    recovered = restarted.get(str(identity))
    assert recovered["status"] == "FAILED"
    assert recovered["error_code"] == "GEO_SEARCH_PROCESS_RESTARTED"
    assert "selected_accession" not in recovered
    assert "selection_revision" not in recovered
    restarted.close()

    restarted_again = GeoSearchService(tmp_path / "data", Catalog(), lambda *_: "unused")
    assert restarted_again.get(str(identity))["status"] == "FAILED"
    restarted_again.close()


def test_search_record_status_is_a_stable_enum() -> None:
    query = DatasetSearchQuery(text="brain")
    record = GeoSearchRecord(
        id=uuid4(),
        status="QUEUED",
        revision=1,
        query=query,
        query_hash=query.query_hash,
        conversation_id=uuid4(),
        turn_id=uuid4(),
    )

    assert record.status is GeoSearchStatus.QUEUED
