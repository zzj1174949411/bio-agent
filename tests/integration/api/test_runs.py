import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Barrier, BrokenBarrierError, Event
from typing import Any
from uuid import uuid4

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from bioagent.artifacts.manager import ArtifactManager
from bioagent.artifacts.manifest import ApprovalRecord, AttemptRecord, RunManifest
from bioagent.config import Settings
from bioagent.datasets.repository import DatasetRepository
from bioagent.domain.plans import AnalysisPlan
from bioagent.domain.qc import QCReport, QCStatus
from bioagent.domain.runs import RunStatus
from bioagent.execution.controller import ExecutionResult, calculate_plan_hash
from bioagent.execution.job_runner import JobStatus, LocalJobRunner
from bioagent.geo.models import (
    Compression,
    DataKind,
    GeoCandidate,
    GeoSearchProvenance,
    GeoSource,
    SourceSelection,
)
from bioagent.geo.repository import GeoRepository, GeoSourceRecord
from bioagent.geo.search_repository import (
    GeoSearchRecord,
    GeoSearchRepository,
    GeoSearchStatus,
)
from bioagent.retrieval.contracts import DatasetSearchHit, DatasetSearchQuery, EvidenceRef
from bioagent.storage.runs import RunRepository


class _Planner:
    def plan(self, *, user_goal: str, summary: Any) -> AnalysisPlan:
        return AnalysisPlan(
            dataset_id=summary.dataset_id,
            comparison={
                "factor": "condition",
                "numerator": "AD",
                "denominator": "Control",
            },
        )


class _Executor:
    def execute(self, state: dict[str, object]) -> ExecutionResult:
        return ExecutionResult(
            attempt_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            execution_key="e" * 64,
            status=RunStatus.COMPLETED,
            qc=QCReport(status=QCStatus.PASS, issues=()),
            reused=False,
        )


def test_running_index_write_failure_reaches_failed_without_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    class CountingExecutor(_Executor):
        def execute(self, state):
            calls.append(state)
            return super().execute(state)

    app = _app(tmp_path, executor=CountingExecutor())
    with TestClient(app) as client:
        dataset_id = _upload(client)
        created = client.post(
            "/api/v1/runs",
            json={"dataset_id": dataset_id, "goal": "Compare AD with Control"},
        )
        run_id = created.json()["run_id"]
        repository = app.state.dependencies.run_repository
        original_write = repository.write

        def fail_running(target_run_id, state):
            if state.get("status") == "RUNNING":
                raise PermissionError("private failure diagnostic")
            return original_write(target_run_id, state)

        monkeypatch.setattr(repository, "write", fail_running)
        approved = client.post(
            f"/api/v1/runs/{run_id}/approval",
            json={"action": "approve", "plan_revision": 1},
        )
        assert approved.status_code == 202
        runner = app.state.dependencies.job_runner
        runner.wait(approved.json()["job_id"], timeout=5)
        state = client.get(f"/api/v1/runs/{run_id}").json()
        assert state["status"] == "FAILED"
        assert state["error"] == {"code": "API_JOB_FAILED"}
        assert runner.status(approved.json()["job_id"]) is JobStatus.FAILED
        assert calls == []


def _app(
    tmp_path: Path,
    *,
    ready: bool = True,
    executor: object | None = None,
    extra_overrides: dict[str, object] | None = None,
) -> Any:
    from bioagent.api.app import create_app

    overrides: dict[str, object] = {
        "planner": _Planner(),
        "executor": executor or _Executor(),
        "readiness": lambda: ready,
    }
    overrides.update(extra_overrides or {})
    return create_app(
        Settings(
            data_dir=tmp_path / "data",
            runs_dir=tmp_path / "runs",
            checkpoint_db=tmp_path / "checkpoints.sqlite",
        ),
        overrides=overrides,
    )


def _upload(client: TestClient) -> str:
    fixtures = Path("tests/fixtures")
    with (
        (fixtures / "counts_valid.csv").open("rb") as counts,
        (fixtures / "metadata_valid.csv").open("rb") as metadata,
    ):
        response = client.post(
            "/api/v1/datasets",
            files={
                "counts": ("counts.csv", counts, "text/csv"),
                "metadata": ("metadata.csv", metadata, "text/csv"),
            },
        )
    assert response.status_code == 201
    return response.json()["dataset_id"]


def _write_run(
    repository: RunRepository,
    *,
    status: RunStatus,
    dataset_id: str | None = None,
    qc: QCReport | None = None,
    plan_revision: int | None = None,
    attempt_id: str | None = None,
    private_fields: bool = False,
) -> str:
    run_id = str(uuid4())
    state: dict[str, Any] = {
        "run_id": run_id,
        "dataset_id": dataset_id or str(uuid4()),
        "status": status.value,
    }
    if qc is not None:
        state["qc"] = qc.model_dump(mode="json")
    if plan_revision is not None:
        state["plan_revision"] = plan_revision
    if attempt_id is not None:
        state["attempt_id"] = attempt_id
    if private_fields:
        state["user_goal"] = "private goal"
        state["plan"] = {"comparison": {"factor": "condition"}}
    repository.write(run_id, state)
    return run_id


def _completed_manifest(
    *,
    run_id: str,
    dataset_id: str,
    attempt_id: str,
    now: datetime,
    qc: QCReport,
) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        dataset_id=dataset_id,
        attempt_id=attempt_id,
        plan_revision=1,
        plan_hash="a" * 64,
        input_hashes={"counts": "b" * 64, "metadata": "c" * 64},
        tool="deseq2",
        software_versions={"r": "4.5.2", "deseq2": "1.50.2"},
        git_commit="d" * 40,
        comparison={
            "factor": "condition",
            "numerator": "AD",
            "denominator": "Control",
        },
        alpha=0.05,
        lfc_shrink=True,
        random_seed=42,
        started_at=now,
        ended_at=now,
        status=RunStatus.COMPLETED,
        qc=qc,
        approvals=(
            ApprovalRecord(
                decision="APPROVED",
                actor="user",
                decided_at=now,
                plan_revision=1,
                plan_hash="a" * 64,
            ),
        ),
        attempts=(
            AttemptRecord(
                attempt_id=attempt_id,
                started_at=now,
                ended_at=now,
                status=RunStatus.COMPLETED,
                qc=qc,
            ),
        ),
    )


def _publish_selected_geo_source(
    *,
    repository: GeoRepository,
    search_repository: GeoSearchRepository,
    dataset_repository: Any,
    dataset_id: str,
    root: Path,
) -> tuple[GeoSourceRecord, GeoSearchProvenance]:
    counts_path, metadata_path = dataset_repository.paths(dataset_id)
    counts = pd.read_csv(counts_path, index_col=0)
    metadata = pd.read_csv(metadata_path, index_col=0)
    source_id = uuid4()
    candidate = GeoCandidate(
        id=uuid4(),
        source_id=source_id,
        accession="GSE12345",
        url="https://fixture.invalid/GSE12345_counts.csv",
        file_name="GSE12345_counts.csv",
        data_kind=DataKind.RAW_COUNTS,
        evidence=("local fixture",),
        compression=Compression.NONE,
    )
    source = GeoSource(
        id=source_id,
        accession="GSE12345",
        title="Local selected GEO source",
        candidates=(candidate,),
        retrieved_at=datetime.now(UTC),
    )
    raw_path = root / "GSE12345_counts.csv"
    raw_path.write_bytes(counts_path.read_bytes())
    sample_columns = tuple(str(column) for column in counts.columns)
    groups = {sample_id: str(metadata.loc[sample_id, "condition"]) for sample_id in sample_columns}
    selection = SourceSelection(
        source_id=source_id,
        candidate_id=candidate.id,
        raw_sha256=sha256(raw_path.read_bytes()).hexdigest(),
        feature_column="feature_id",
        sample_columns=sample_columns,
        sample_map={sample_id: sample_id for sample_id in sample_columns},
        groups=groups,
        numerator="AD",
        denominator="Control",
        revision=1,
        evidence=("local fixture selection",),
    )
    query = DatasetSearchQuery(text="brain RNA-seq")
    provenance = GeoSearchProvenance(
        search_id=uuid4(),
        query_hash=query.query_hash,
        selected_accession=source.accession,
        selection_revision=1,
        retrieved_at=source.retrieved_at,
        evidence_sha256="a" * 64,
    )
    search_repository.write(
        GeoSearchRecord(
            id=provenance.search_id,
            status=GeoSearchStatus.SELECTED,
            revision=2,
            query=query,
            query_hash=query.query_hash,
            items=(
                DatasetSearchHit(
                    provider="geo",
                    source_id=source.accession,
                    title="Local selected GEO source",
                    source_uri="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345",
                    evidence=EvidenceRef(
                        provider="geo",
                        source_id=source.accession,
                        source_uri="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345",
                        retrieved_at=provenance.retrieved_at,
                        content_sha256=provenance.evidence_sha256,
                    ),
                ),
            ),
            total=1,
            conversation_id=uuid4(),
            turn_id=uuid4(),
            source_id=str(source_id),
            selected_accession=source.accession,
            selection_revision=provenance.selection_revision,
        )
    )
    return (
        repository.publish(
            source,
            candidate,
            selection,
            raw_path,
            counts,
            metadata,
            dataset_id=dataset_id,
            provenance=provenance,
        ),
        provenance,
    )


def test_run_requires_approval_before_execution(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        dataset_id = _upload(client)
        response = client.post(
            "/api/v1/runs",
            json={"dataset_id": dataset_id, "goal": "compare AD with Control"},
        )

        assert response.status_code == 201
        run = response.json()
        assert run["status"] == "AWAITING_APPROVAL"

        fetched = client.get(f"/api/v1/runs/{run['run_id']}")
        plan = client.get(f"/api/v1/runs/{run['run_id']}/plan")
        artifacts = client.get(f"/api/v1/runs/{run['run_id']}/artifacts")

    assert fetched.status_code == 200
    assert fetched.json()["run_id"] == run["run_id"]
    assert plan.status_code == 200
    assert plan.json()["plan_revision"] == 1
    assert plan.json()["plan"]["comparison"]["numerator"] == "AD"
    assert artifacts.status_code == 409
    assert artifacts.json()["detail"]["code"] == "RUN_NOT_COMPLETED"


def test_approval_returns_202_and_background_job_completes(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        dataset_id = _upload(client)
        created = client.post(
            "/api/v1/runs",
            json={"dataset_id": dataset_id, "goal": "AD vs Control"},
        ).json()

        response = client.post(
            f"/api/v1/runs/{created['run_id']}/approval",
            json={"action": "approve", "plan_revision": 1},
        )

        assert response.status_code == 202
        assert response.json()["status"] == "QUEUED"
        job_id = response.json()["job_id"]
        # Completion includes real SQLite checkpoints and filesystem writes.
        # This is a functional check, not a two-second CI performance budget.
        app.state.dependencies.job_runner.wait(job_id, timeout=30)
        completed = client.get(f"/api/v1/runs/{created['run_id']}")

    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"


def test_cancel_awaiting_run_never_executes(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        dataset_id = _upload(client)
        created = client.post(
            "/api/v1/runs",
            json={"dataset_id": dataset_id, "goal": "AD vs Control"},
        ).json()

        response = client.post(f"/api/v1/runs/{created['run_id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_health_and_ready_report_distinct_states(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, ready=False)) as client:
        health = client.get("/health")
        ready = client.get("/ready")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 503
    assert ready.json()["detail"]["code"] == "DEPENDENCIES_NOT_READY"


def test_openapi_contains_every_mvp_route(tmp_path: Path) -> None:
    paths = _app(tmp_path).openapi()["paths"]

    assert {
        "/api/v1/datasets",
        "/api/v1/datasets/{dataset_id}/validation",
        "/api/v1/runs",
        "/api/v1/runs/{run_id}",
        "/api/v1/runs/{run_id}/plan",
        "/api/v1/runs/{run_id}/approval",
        "/api/v1/runs/{run_id}/cancel",
        "/api/v1/runs/{run_id}/artifacts",
        "/api/v1/runs/{run_id}/artifacts/{artifact_id}",
        "/health",
        "/ready",
    }.issubset(paths)


def test_project_run_history_lists_all_states_and_filters_by_status(
    tmp_path: Path,
) -> None:
    repository = RunRepository(tmp_path / "runs")
    app = _app(tmp_path, extra_overrides={"run_repository": repository})

    with TestClient(app) as client:
        run_ids = {
            status: _write_run(repository, status=status)
            for status in RunStatus
            if status != RunStatus.COMPLETED
        }
        all_runs = client.get("/api/v1/runs")
        running = client.get("/api/v1/runs", params={"status": "RUNNING"})

    assert all_runs.status_code == 200
    assert {item["run_id"] for item in all_runs.json()["runs"]} == set(run_ids.values())
    assert all_runs.json()["issues"] == []
    assert [item["run_id"] for item in running.json()["runs"]] == [run_ids[RunStatus.RUNNING]]
    assert running.json()["issues"] == []


def test_project_run_history_rejects_invalid_status_filter(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/v1/runs", params={"status": "UNKNOWN"})

    assert response.status_code == 422


def test_project_run_history_verifies_completed_manifest(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    repository = RunRepository(runs_dir)
    manager = ArtifactManager(runs_dir)
    app = _app(
        tmp_path,
        extra_overrides={
            "run_repository": repository,
            "artifact_manager": manager,
        },
    )
    run_id = manager.create_run()
    dataset_id = str(uuid4())
    attempt_id = str(uuid4())
    now = datetime.now(UTC)
    qc = QCReport(status=QCStatus.PASS, issues=())
    manager.write_manifest(
        run_id,
        _completed_manifest(
            run_id=run_id,
            dataset_id=dataset_id,
            attempt_id=attempt_id,
            now=now,
            qc=qc,
        ),
    )
    repository.write(
        run_id,
        {
            "run_id": run_id,
            "dataset_id": dataset_id,
            "status": RunStatus.COMPLETED.value,
            "qc": qc.model_dump(mode="json"),
            "plan_revision": 1,
            "attempt_id": attempt_id,
        },
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/runs")

    assert response.status_code == 200
    assert response.json()["issues"] == []
    assert response.json()["runs"] == [
        {
            "run_id": run_id,
            "dataset_id": dataset_id,
            "status": "COMPLETED",
            "qc_status": "PASS",
            "plan_revision": 1,
            "attempt_id": attempt_id,
            "index_updated_at": response.json()["runs"][0]["index_updated_at"],
            "completed_at": now.isoformat().replace("+00:00", "Z"),
            "evidence_status": "VERIFIED",
        }
    ]


def test_project_run_history_marks_missing_completed_manifest_invalid(
    tmp_path: Path,
) -> None:
    repository = RunRepository(tmp_path / "runs")
    app = _app(tmp_path, extra_overrides={"run_repository": repository})
    run_id = _write_run(
        repository,
        status=RunStatus.COMPLETED,
        qc=QCReport(status=QCStatus.PASS, issues=()),
        plan_revision=1,
        attempt_id=str(uuid4()),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/runs")
        filtered = client.get("/api/v1/runs", params={"status": "RUNNING"})

    assert response.status_code == 200
    assert response.json()["runs"][0]["run_id"] == run_id
    assert response.json()["runs"][0]["evidence_status"] == "INVALID"
    assert response.json()["runs"][0]["completed_at"] is None
    assert response.json()["issues"] == [{"run_id": run_id, "code": "RUN_MANIFEST_INVALID"}]
    assert filtered.json() == {
        "runs": [],
        "issues": [{"run_id": run_id, "code": "RUN_MANIFEST_INVALID"}],
    }


def test_project_run_history_rejects_completed_manifest_identity_mismatch(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    repository = RunRepository(runs_dir)
    manager = ArtifactManager(runs_dir)
    app = _app(
        tmp_path,
        extra_overrides={
            "run_repository": repository,
            "artifact_manager": manager,
        },
    )
    run_id = manager.create_run()
    index_dataset_id = str(uuid4())
    attempt_id = str(uuid4())
    now = datetime.now(UTC)
    qc = QCReport(status=QCStatus.PASS, issues=())
    manager.write_manifest(
        run_id,
        _completed_manifest(
            run_id=run_id,
            dataset_id=str(uuid4()),
            attempt_id=attempt_id,
            now=now,
            qc=qc,
        ),
    )
    repository.write(
        run_id,
        {
            "run_id": run_id,
            "dataset_id": index_dataset_id,
            "status": RunStatus.COMPLETED.value,
            "qc": qc.model_dump(mode="json"),
            "plan_revision": 1,
            "attempt_id": attempt_id,
        },
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/runs")

    assert response.status_code == 200
    assert response.json()["runs"][0]["evidence_status"] == "INVALID"
    assert response.json()["issues"] == [{"run_id": run_id, "code": "RUN_MANIFEST_INVALID"}]


def test_project_run_history_isolates_corrupt_index_and_redacts_private_state(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    repository = RunRepository(runs_dir)
    app = _app(tmp_path, extra_overrides={"run_repository": repository})
    valid_id = _write_run(
        repository,
        status=RunStatus.FAILED,
        private_fields=True,
    )
    corrupt_id = str(uuid4())
    corrupt_dir = runs_dir / corrupt_id
    corrupt_dir.mkdir(parents=True)
    (corrupt_dir / "run.json").write_text(
        "not-json C:\\private\\runs\\secret",
        encoding="utf-8",
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/runs")

    assert response.status_code == 200
    payload = response.json()
    assert [item["run_id"] for item in payload["runs"]] == [valid_id]
    assert payload["issues"] == [{"run_id": corrupt_id, "code": "RUN_INDEX_INVALID"}]
    assert set(payload["runs"][0]) == {
        "run_id",
        "dataset_id",
        "status",
        "qc_status",
        "plan_revision",
        "attempt_id",
        "index_updated_at",
        "completed_at",
        "evidence_status",
    }
    assert "private" not in response.text.lower()
    assert "secret" not in response.text.lower()


class _BlockingExecutor:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def execute(self, state: dict[str, object]) -> ExecutionResult:
        self.started.set()
        self.release.wait(timeout=5)
        return _Executor().execute(state)


def test_background_worker_persists_running_state(tmp_path: Path) -> None:
    executor = _BlockingExecutor()
    app = _app(tmp_path, executor=executor)
    with TestClient(app) as client:
        dataset_id = _upload(client)
        created = client.post(
            "/api/v1/runs",
            json={"dataset_id": dataset_id, "goal": "AD vs Control"},
        ).json()
        approved = client.post(
            f"/api/v1/runs/{created['run_id']}/approval",
            json={"action": "approve", "plan_revision": 1},
        )
        assert approved.status_code == 202
        assert executor.started.wait(timeout=2)

        running = client.get(f"/api/v1/runs/{created['run_id']}")
        executor.release.set()
        app.state.dependencies.job_runner.wait(approved.json()["job_id"], timeout=2)

    assert running.status_code == 200
    assert running.json()["status"] == "RUNNING"


def test_startup_recovers_orphaned_running_api_state(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    repository = RunRepository(runs_dir)
    run_id = str(uuid4())
    repository.write(run_id, {"run_id": run_id, "status": "RUNNING"})
    app = _app(
        tmp_path,
        extra_overrides={"run_repository": repository},
    )

    with TestClient(app) as client:
        recovered = client.get(f"/api/v1/runs/{run_id}")

    assert recovered.status_code == 200
    assert recovered.json()["status"] == "FAILED"
    assert recovered.json()["error"] == {"code": "API_PROCESS_RESTARTED"}


def test_real_dependency_container_runs_published_selected_geo_source(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        dataset_id = _upload(client)
        dependencies = app.state.dependencies
        assert isinstance(dependencies.geo_repository, GeoRepository)
        assert isinstance(dependencies.geo_search_repository, GeoSearchRepository)
        source, _ = _publish_selected_geo_source(
            repository=dependencies.geo_repository,
            search_repository=dependencies.geo_search_repository,
            dataset_repository=dependencies.dataset_repository,
            dataset_id=dataset_id,
            root=tmp_path,
        )

        run_id = dependencies.analysis_service.create_run(
            dataset_id=dataset_id,
            goal="Create a run from the selected local GEO source",
            agent_context={
                "conversation_id": str(uuid4()),
                "turn_id": str(uuid4()),
                "source_id": str(source.source_id),
            },
        )

        assert dependencies.run_repository.read(run_id)["status"] == "AWAITING_APPROVAL"
        assert (
            dependencies.artifact_manager.resolve(run_id, "source/source.json").read_bytes()
            == source.source_json.read_bytes()
        )


def test_dependency_container_rejects_invalid_geo_repository_override(tmp_path: Path) -> None:
    app = _app(tmp_path, extra_overrides={"geo_repository": object()})

    with (
        pytest.raises(TypeError, match="geo_repository override must be a GeoRepository"),
        TestClient(app),
    ):
        pass


def test_dependency_container_binds_search_repository_to_geo_repository_override(
    tmp_path: Path,
) -> None:
    geo_repository = GeoRepository(tmp_path / "data" / "sources")
    app = _app(tmp_path, extra_overrides={"geo_repository": geo_repository})

    with TestClient(app) as client:
        dataset_id = _upload(client)
        dependencies = app.state.dependencies
        source, _ = _publish_selected_geo_source(
            repository=dependencies.geo_repository,
            search_repository=dependencies.geo_search_repository,
            dataset_repository=dependencies.dataset_repository,
            dataset_id=dataset_id,
            root=tmp_path,
        )

        assert dependencies.geo_repository.read(source.source_id).source_id == source.source_id


def test_startup_recovery_fails_closed_for_tampered_selected_geo_source(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    datasets = DatasetRepository(data_dir)
    dataset_id = datasets.create(
        (Path("tests/fixtures") / "counts_valid.csv").read_bytes(),
        (Path("tests/fixtures") / "metadata_valid.csv").read_bytes(),
        ".csv",
        ".csv",
    )
    search_repository = GeoSearchRepository(data_dir / "searches")
    geo_repository = GeoRepository(data_dir / "sources", search_repository=search_repository)
    source, provenance = _publish_selected_geo_source(
        repository=geo_repository,
        search_repository=search_repository,
        dataset_repository=datasets,
        dataset_id=dataset_id,
        root=tmp_path,
    )
    runs_dir = tmp_path / "runs"
    artifacts = ArtifactManager(runs_dir)
    repository = RunRepository(runs_dir)
    run_id = artifacts.create_run()
    source_artifacts = tuple(
        artifacts.write_bytes(run_id, artifact_id, source_path.read_bytes())
        for artifact_id, source_path in (
            ("source/raw/source.bin", source.raw_path),
            ("source/source.json", source.source_json),
            ("source/normalized/counts.csv", source.counts_path),
            ("source/normalized/metadata.csv", source.metadata_path),
        )
    )
    result = artifacts.write_bytes(run_id, "attempts/recovered/result.txt", b"done")
    report = artifacts.write_bytes(run_id, "report/report.html", b"<html>done</html>")
    plan = AnalysisPlan(
        dataset_id=dataset_id,
        comparison={"factor": "condition", "numerator": "AD", "denominator": "Control"},
    )
    plan_hash = calculate_plan_hash(plan)
    now = datetime.now(UTC)
    attempt_id = uuid4()
    dataset_hashes = datasets.hashes(dataset_id)
    manifest = RunManifest(
        run_id=run_id,
        dataset_id=dataset_id,
        attempt_id=attempt_id,
        plan_revision=1,
        plan_hash=plan_hash,
        input_hashes={
            "counts": dataset_hashes.counts_sha256,
            "metadata": dataset_hashes.metadata_sha256,
        },
        tool="deseq2",
        software_versions={"r": "4.5.2", "deseq2": "1.50.2"},
        git_commit="d" * 40,
        comparison=plan.comparison,
        alpha=plan.options.alpha,
        lfc_shrink=plan.options.lfc_shrink,
        random_seed=plan.options.random_seed,
        started_at=now,
        ended_at=now,
        status=RunStatus.COMPLETED,
        qc=QCReport(status=QCStatus.PASS, issues=()),
        approvals=(
            ApprovalRecord(
                decision="APPROVED",
                actor="user",
                decided_at=now,
                plan_revision=1,
                plan_hash=plan_hash,
            ),
        ),
        attempts=(
            AttemptRecord(
                attempt_id=attempt_id,
                started_at=now,
                ended_at=now,
                status=RunStatus.COMPLETED,
                qc=QCReport(status=QCStatus.PASS, issues=()),
            ),
        ),
        artifacts=(*source_artifacts, result, report),
        source_id=source.source_id,
        source_artifacts=source_artifacts,
        search_provenance=provenance,
    )
    artifacts.write_manifest(run_id, manifest)
    repository.write(
        run_id,
        {
            "run_id": run_id,
            "dataset_id": dataset_id,
            "status": "RUNNING",
            "plan_revision": 1,
            "plan": plan.model_dump(mode="json"),
        },
    )
    source_payload = json.loads(source.source_json.read_text(encoding="utf-8"))
    tampered = GeoSearchProvenance.model_validate(
        {**source_payload["search_provenance"], "query_hash": "f" * 64}
    )
    source_payload["search_provenance"] = tampered.model_dump(mode="json")
    source_payload["search_provenance_sha256"] = tampered.provenance_sha256
    source.source_json.write_text(json.dumps(source_payload), encoding="utf-8")
    copied_source_json = artifacts.resolve(run_id, "source/source.json")
    copied_source_json.write_text(json.dumps(source_payload), encoding="utf-8")
    copied_source_hash = sha256(copied_source_json.read_bytes()).hexdigest()
    updated_source_artifacts = tuple(
        artifact.model_copy(update={"sha256": copied_source_hash})
        if artifact.relative_path == "source/source.json"
        else artifact
        for artifact in manifest.source_artifacts
    )
    updated_artifacts = tuple(
        artifact.model_copy(update={"sha256": copied_source_hash})
        if artifact.relative_path == "source/source.json"
        else artifact
        for artifact in manifest.artifacts
    )
    artifacts.write_manifest(
        run_id,
        manifest.model_copy(
            update={
                "search_provenance": tampered,
                "source_artifacts": updated_source_artifacts,
                "artifacts": updated_artifacts,
            }
        ),
    )

    with TestClient(_app(tmp_path)) as client:
        recovered = client.get(f"/api/v1/runs/{run_id}")

    assert recovered.status_code == 200
    assert recovered.json()["status"] == "FAILED"
    assert recovered.json()["error"] == {"code": "API_PROCESS_RESTARTED"}


@pytest.mark.parametrize(
    "failure", [None, "no_report", "tampered_report", "dataset", "revision", "plan", "missing_plan"]
)
def test_startup_prefers_verified_completed_manifest_over_stale_run_index(
    tmp_path: Path,
    failure: str | None,
) -> None:
    runs_dir = tmp_path / "runs"
    manager = ArtifactManager(runs_dir)
    repository = RunRepository(runs_dir)
    run_id = manager.create_run()
    artifact = manager.write_bytes(run_id, "attempts/recovered/result.txt", b"done")
    report = manager.write_bytes(run_id, "report/report.html", b"<html>done</html>")
    plan = AnalysisPlan(
        dataset_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        comparison={"factor": "condition", "numerator": "AD", "denominator": "Control"},
    )
    plan_hash = calculate_plan_hash(plan)
    now = datetime.now(UTC)
    attempt_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    qc = QCReport(status=QCStatus.PASS, issues=())
    manager.write_manifest(
        run_id,
        RunManifest(
            run_id=run_id,
            dataset_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            attempt_id=attempt_id,
            plan_revision=1,
            plan_hash=plan_hash,
            input_hashes={"counts": "b" * 64, "metadata": "c" * 64},
            tool="deseq2",
            software_versions={"r": "4.5.2", "deseq2": "1.50.2"},
            git_commit="d" * 40,
            comparison={
                "factor": "condition",
                "numerator": "AD",
                "denominator": "Control",
            },
            alpha=0.05,
            lfc_shrink=True,
            random_seed=42,
            started_at=now,
            ended_at=now,
            status=RunStatus.COMPLETED,
            qc=qc,
            approvals=(
                ApprovalRecord(
                    decision="APPROVED",
                    actor="user",
                    decided_at=now,
                    plan_revision=1,
                    plan_hash=plan_hash,
                ),
            ),
            attempts=(
                AttemptRecord(
                    attempt_id=attempt_id,
                    started_at=now,
                    ended_at=now,
                    status=RunStatus.COMPLETED,
                    qc=qc,
                ),
            ),
            artifacts=(artifact,) if failure == "no_report" else (artifact, report),
        ),
    )
    state = {
        "run_id": run_id,
        "status": "RUNNING",
        "dataset_id": plan.dataset_id,
        "plan_revision": 1,
        "plan": plan.model_dump(mode="json"),
    }
    if failure == "tampered_report":
        manager.resolve(run_id, "report/report.html").write_bytes(b"changed")
    if failure == "dataset":
        state["dataset_id"] = str(uuid4())
    if failure == "revision":
        state["plan_revision"] = 2
    if failure == "plan":
        state["plan"]["options"]["alpha"] = 0.1
    if failure == "missing_plan":
        state.pop("plan")
    repository.write(run_id, state)
    app = _app(
        tmp_path,
        extra_overrides={
            "run_repository": repository,
            "artifact_manager": manager,
        },
    )

    with TestClient(app) as client:
        recovered = client.get(f"/api/v1/runs/{run_id}")
        artifacts = client.get(f"/api/v1/runs/{run_id}/artifacts")

    assert recovered.status_code == 200
    if failure:
        assert recovered.json()["status"] == "FAILED"
        assert recovered.json()["error"] == {"code": "API_PROCESS_RESTARTED"}
        assert artifacts.status_code == 409
        return
    assert recovered.json()["status"] == "COMPLETED"
    assert recovered.json()["attempt_id"] == attempt_id
    assert artifacts.status_code == 200


class _BarrierRunRepository(RunRepository):
    def __init__(self, runs_dir: Path) -> None:
        super().__init__(runs_dir)
        self.barrier = Barrier(2)
        self.synchronize_approval_reads = False

    def read(self, run_id: str) -> dict[str, Any]:
        state = super().read(run_id)
        if self.synchronize_approval_reads and state.get("status") == "AWAITING_APPROVAL":
            with suppress(BrokenBarrierError):
                self.barrier.wait(timeout=0.1)
        return state


def test_concurrent_approval_has_single_atomic_winner(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    repository = _BarrierRunRepository(runs_dir)
    executor = _BlockingExecutor()
    app = _app(
        tmp_path,
        executor=executor,
        extra_overrides={"run_repository": repository},
    )
    with TestClient(app) as client:
        dataset_id = _upload(client)
        created = client.post(
            "/api/v1/runs",
            json={"dataset_id": dataset_id, "goal": "AD vs Control"},
        ).json()
        repository.synchronize_approval_reads = True

        def approve() -> int:
            return client.post(
                f"/api/v1/runs/{created['run_id']}/approval",
                json={"action": "approve", "plan_revision": 1},
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(approve)
            second = pool.submit(approve)
            statuses = sorted([first.result(), second.result()])
        repository.synchronize_approval_reads = False
        executor.release.set()

    assert statuses == [202, 409]


class _PausedSubmitRunner(LocalJobRunner):
    def __init__(self) -> None:
        super().__init__()
        self.submitting = Event()
        self.release_submit = Event()

    def submit(self, execution_key: str, task: Any) -> str:
        self.submitting.set()
        self.release_submit.wait(timeout=5)
        return super().submit(execution_key, task)


def test_immediate_cancel_waits_for_job_registration(tmp_path: Path) -> None:
    runner = _PausedSubmitRunner()
    executor = _BlockingExecutor()
    app = _app(
        tmp_path,
        executor=executor,
        extra_overrides={"job_runner": runner},
    )
    with TestClient(app) as client:
        dataset_id = _upload(client)
        created = client.post(
            "/api/v1/runs",
            json={"dataset_id": dataset_id, "goal": "AD vs Control"},
        ).json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            approval = pool.submit(
                client.post,
                f"/api/v1/runs/{created['run_id']}/approval",
                json={"action": "approve", "plan_revision": 1},
            )
            assert runner.submitting.wait(timeout=2)
            cancellation = pool.submit(
                client.post,
                f"/api/v1/runs/{created['run_id']}/cancel",
            )
            runner.release_submit.set()
            approved = approval.result(timeout=2)
            cancelled = cancellation.result(timeout=2)
        executor.release.set()

    runner.close()
    assert approved.status_code == 202
    assert cancelled.status_code in {200, 202}
    assert cancelled.json().get("detail", {}).get("code") != "JOB_NOT_FOUND"
    assert runner.status(approved.json()["job_id"]) in {
        JobStatus.CANCELLED,
        JobStatus.COMPLETED,
    }
