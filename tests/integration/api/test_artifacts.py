from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from bioagent.artifacts.manager import ArtifactManager
from bioagent.artifacts.manifest import (
    ApprovalRecord,
    AttemptRecord,
    RunManifest,
)
from bioagent.config import Settings
from bioagent.domain.qc import QCReport, QCStatus
from bioagent.domain.runs import RunStatus
from bioagent.storage.runs import RunRepository


def _completed_app(tmp_path: Path) -> tuple[Any, str, bytes]:
    from bioagent.api.app import create_app

    runs_dir = tmp_path / "runs"
    manager = ArtifactManager(runs_dir)
    repository = RunRepository(runs_dir)
    run_id = manager.create_run()
    content = b"feature_id,padj\nGENE_1,0.01\n"
    artifact = manager.write_bytes(run_id, "attempts/result/results.csv", content)
    now = datetime.now(UTC)
    attempt_id = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    qc = QCReport(status=QCStatus.PASS, issues=())
    manifest = RunManifest(
        run_id=UUID(run_id),
        dataset_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
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
        artifacts=(artifact,),
    )
    manager.write_manifest(run_id, manifest)
    repository.write(
        run_id,
        {"run_id": run_id, "status": RunStatus.COMPLETED.value},
    )
    app = create_app(
        Settings(
            data_dir=tmp_path / "data",
            runs_dir=runs_dir,
            checkpoint_db=tmp_path / "checkpoints.sqlite",
        ),
        overrides={
            "artifact_manager": manager,
            "run_repository": repository,
            "planner": object(),
            "executor": object(),
        },
    )
    return app, run_id, content


def test_artifact_list_and_download_use_manifest_ids(tmp_path: Path) -> None:
    app, run_id, content = _completed_app(tmp_path)

    with TestClient(app) as client:
        listed = client.get(f"/api/v1/runs/{run_id}/artifacts")
        artifact_id = listed.json()["artifacts"][0]["artifact_id"]
        downloaded = client.get(f"/api/v1/runs/{run_id}/artifacts/{artifact_id}")

    assert listed.status_code == 200
    assert listed.json()["artifacts"][:1] == [
        {
            "artifact_id": artifact_id,
            "sha256": sha256(content).hexdigest(),
        }
    ]
    assert len(artifact_id) == 64
    assert artifact_id.isalnum()
    assert "/" not in artifact_id
    assert downloaded.status_code == 200
    assert downloaded.content == content


def test_artifact_path_traversal_and_unregistered_files_return_404(
    tmp_path: Path,
) -> None:
    app, run_id, _ = _completed_app(tmp_path)

    with TestClient(app) as client:
        traversal = client.get(
            f"/api/v1/runs/{run_id}/artifacts/%2E%2E%2Fmanifest.json"
        )
        unregistered = client.get(
            f"/api/v1/runs/{run_id}/artifacts/report%2Fsecret.txt"
        )

    assert traversal.status_code == 404
    assert unregistered.status_code == 404


def test_download_detects_artifact_tampering(tmp_path: Path) -> None:
    app, run_id, _ = _completed_app(tmp_path)
    artifact_path = tmp_path / "runs" / run_id / "attempts" / "result" / "results.csv"

    with TestClient(app) as client:
        listed = client.get(f"/api/v1/runs/{run_id}/artifacts")
        artifact_id = listed.json()["artifacts"][0]["artifact_id"]
        artifact_path.write_bytes(b"tampered")
        response = client.get(f"/api/v1/runs/{run_id}/artifacts/{artifact_id}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ARTIFACT_INTEGRITY_ERROR"


def test_manifest_is_downloadable_and_stale_manifest_id_is_rejected(tmp_path: Path) -> None:
    app, run_id, _ = _completed_app(tmp_path)
    path = tmp_path / "runs" / run_id / "manifest.json"
    with TestClient(app) as client:
        records = client.get(f"/api/v1/runs/{run_id}/artifacts").json()["artifacts"]
        digest = sha256(path.read_bytes()).hexdigest()
        matching = [record for record in records if record["sha256"] == digest]
        assert len(matching) == 1
        url = f"/api/v1/runs/{run_id}/artifacts/{matching[0]['artifact_id']}"
        response = client.get(url)
        assert response.content == path.read_bytes()
        assert response.json()["run_id"] == run_id
        path.write_bytes(path.read_bytes() + b"\n")
        assert client.get(url).status_code == 404
