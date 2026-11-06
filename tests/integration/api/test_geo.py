from datetime import UTC, datetime
from time import sleep
from uuid import uuid4

from fastapi.testclient import TestClient

from bioagent.api.app import create_app
from bioagent.config import Settings
from bioagent.geo.models import Compression, DataKind, GeoCandidate, GeoSource
from bioagent.geo.repository import GeoRepository
from bioagent.geo.service import GeoImportService, GeoServiceError


def test_unknown_geo_api_route_is_json_404(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        checkpoint_db=tmp_path / "checkpoints.sqlite",
        workbench_db=tmp_path / "workbench.sqlite",
        rscript="Rscript",
        local_allowed_hosts=("testserver",),
    )
    with TestClient(create_app(settings, overrides={"readiness": lambda: True})) as client:
        response = client.get("/api/v1/geo/not-a-real-route")
    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "NOT_FOUND"}}


class _GeoService:
    def __init__(self) -> None:
        self.source_id = str(uuid4())
        self.calls = 0

    def bind_ready_sink(self, _sink) -> None:
        return None

    def bind_event_sink(self, _sink) -> None:
        return None

    def close(self) -> None:
        return None

    def create_source(self, accession: str, **_context: object) -> dict[str, object]:
        self.calls += 1
        return {
            "id": self.source_id,
            "accession": accession.upper(),
            "status": "DISCOVERING",
            "revision": 1,
            "source": None,
            "error_code": None,
        }

    def get_source(self, source_id: str) -> dict[str, object]:
        assert str(source_id) == self.source_id
        return self.create_source("GSE123")


def test_geo_source_is_readable_after_202_and_writes_require_csrf(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        checkpoint_db=tmp_path / "checkpoints.sqlite",
        workbench_db=tmp_path / "workbench.sqlite",
        rscript="Rscript",
        local_allowed_hosts=("testserver",),
    )
    service = _GeoService()
    with TestClient(
        create_app(settings, overrides={"readiness": lambda: True, "geo_service": service})
    ) as client:
        rejected = client.post("/api/v1/geo/sources", json={"accession": "GSE123"})
        assert rejected.status_code == 403
        csrf_token = client.get("/api/v1/workbench/bootstrap").json()["csrf_token"]
        created = client.post(
            "/api/v1/geo/sources",
            json={"accession": "GSE123"},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert created.status_code == 202
        readable = client.get(f"/api/v1/geo/sources/{service.source_id}")
    assert readable.status_code == 200
    assert readable.json()["status"] == "DISCOVERING"


class _SelectionFailureGeo(_GeoService):
    def submit_selection(self, _import_id, _selection) -> dict[str, object]:
        raise GeoServiceError("SOURCE_SELECTION_CONFLICT")


def test_stale_selection_maps_to_json_409(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        checkpoint_db=tmp_path / "c.sqlite",
        workbench_db=tmp_path / "w.sqlite",
        rscript="Rscript",
        local_allowed_hosts=("testserver",),
    )
    service = _SelectionFailureGeo()
    source_id, candidate_id, import_id = uuid4(), uuid4(), uuid4()
    payload = _selection_payload(source_id, candidate_id)
    with TestClient(create_app(settings, overrides={"geo_service": service})) as client:
        token = client.get("/api/v1/workbench/bootstrap").json()["csrf_token"]
        response = client.post(
            f"/api/v1/geo/imports/{import_id}/selection",
            json=payload,
            headers={"X-CSRF-Token": token},
        )
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "SOURCE_SELECTION_CONFLICT"}}


def test_large_geo_mapping_body_reaches_route_limit(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        checkpoint_db=tmp_path / "c.sqlite",
        workbench_db=tmp_path / "w.sqlite",
        rscript="Rscript",
        local_allowed_hosts=("testserver",),
    )
    service = _SelectionFailureGeo()
    source_id, candidate_id, import_id = uuid4(), uuid4(), uuid4()
    columns = [f"GSM{i}" for i in range(1, 2001)]
    payload = {
        "source_id": str(source_id),
        "candidate_id": str(candidate_id),
        "raw_sha256": "a" * 64,
        "feature_column": "feature_id",
        "sample_columns": columns,
        "sample_map": {column: column for column in columns},
        "groups": {
            column: ("AD" if position < 1000 else "Control")
            for position, column in enumerate(columns)
        },
        "numerator": "AD",
        "denominator": "Control",
        "revision": 1,
        "evidence": ["confirmed"],
    }
    with TestClient(create_app(settings, overrides={"geo_service": service})) as client:
        token = client.get("/api/v1/workbench/bootstrap").json()["csrf_token"]
        response = client.post(
            f"/api/v1/geo/imports/{import_id}/selection",
            json=payload,
            headers={"X-CSRF-Token": token},
        )
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "SOURCE_SELECTION_CONFLICT"}}


class _FailureGeo(_GeoService):
    def create_source(self, *_args, **_kwargs) -> dict[str, object]:
        raise GeoServiceError("GEO_ACCESSION_INVALID")


def test_geo_failure_code_is_json_422(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        checkpoint_db=tmp_path / "c.sqlite",
        workbench_db=tmp_path / "w.sqlite",
        rscript="Rscript",
        local_allowed_hosts=("testserver",),
    )
    with TestClient(create_app(settings, overrides={"geo_service": _FailureGeo()})) as client:
        token = client.get("/api/v1/workbench/bootstrap").json()["csrf_token"]
        response = client.post(
            "/api/v1/geo/sources", json={"accession": "GSE123"}, headers={"X-CSRF-Token": token}
        )
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "GEO_ACCESSION_INVALID"}}


def test_direct_geo_api_persists_owned_workbench_events(tmp_path) -> None:
    class Discovery:
        def discover(self, accession: str) -> GeoSource:
            source_id = uuid4()
            candidate = GeoCandidate(
                id=uuid4(),
                source_id=source_id,
                accession=accession,
                url="https://www.ncbi.nlm.nih.gov/counts.tsv",
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

    settings = Settings(
        data_dir=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        checkpoint_db=tmp_path / "c.sqlite",
        workbench_db=tmp_path / "w.sqlite",
        rscript="Rscript",
        local_allowed_hosts=("testserver",),
    )
    geo = GeoImportService(
        GeoRepository(settings.data_dir / "sources"), Discovery(), object(), object()
    )
    with TestClient(create_app(settings, overrides={"geo_service": geo})) as client:
        token = client.get("/api/v1/workbench/bootstrap").json()["csrf_token"]
        created = client.post(
            "/api/v1/geo/sources", json={"accession": "GSE123"}, headers={"X-CSRF-Token": token}
        )
        source = created.json()
        # Discovery runs on the dedicated I/O executor.  Give a loaded Windows
        # test host a bounded three-second window rather than treating a 0.5 s
        # scheduling delay as a service failure.
        for _ in range(300):
            observed = client.get(f"/api/v1/geo/sources/{source['id']}")
            assert observed.status_code == 200, observed.text
            source = observed.json()
            if source["status"] == "AWAITING_SELECTION":
                break
            sleep(0.01)
        context = source["context"]
        events = client.app.state.dependencies.workbench.list_events(
            context["conversation_id"], limit=100
        )
    assert source["status"] == "AWAITING_SELECTION"
    assert [event.seq for event in events] == sorted(event.seq for event in events)
    assert any(event.kind == "geo.updated" for event in events)


def _selection_payload(source_id, candidate_id) -> dict[str, object]:
    return {
        "source_id": str(source_id),
        "candidate_id": str(candidate_id),
        "raw_sha256": "a" * 64,
        "feature_column": "feature_id",
        "sample_columns": ["GSM1", "GSM2", "GSM3", "GSM4"],
        "sample_map": {name: name for name in ("GSM1", "GSM2", "GSM3", "GSM4")},
        "groups": {"GSM1": "AD", "GSM2": "AD", "GSM3": "Control", "GSM4": "Control"},
        "numerator": "AD",
        "denominator": "Control",
        "revision": 1,
        "evidence": ["confirmed"],
    }
