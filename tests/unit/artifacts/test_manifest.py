import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from bioagent.artifacts.manager import ArtifactManager
from bioagent.artifacts.manifest import (
    ApprovalRecord,
    ArtifactRecord,
    AttemptRecord,
    RunManifest,
)
from bioagent.domain.plans import Comparison
from bioagent.domain.qc import QCIssue, QCReport, QCStatus
from bioagent.domain.runs import RunStatus
from bioagent.geo.models import GeoSearchProvenance

_SHA256 = "a" * 64
_PLAN_HASH = "b" * 64
_STARTED_AT = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
_UNSAFE_WINDOWS_ARTIFACT_PATHS = (
    "results/CON",
    "results/con.txt",
    "results/NUL.tar.gz",
    "results/COM1.csv",
    "results/LPT9",
    "results/COM¹.txt",
    "results/LPT³.log",
    "results/table.csv:secret",
    "results/bad<name.csv",
    "results/bad>name.csv",
    'results/bad"name.csv',
    "results/bad|name.csv",
    "results/bad?name.csv",
    "results/bad*name.csv",
    "results/bad\x00name.csv",
    "results/bad\x01name.csv",
    "results/bad\x1fname.csv",
    "results/table.csv ",
    "results/table.csv.",
    "results /table.csv",
    "results./table.csv",
)


def _completed_manifest(run_id: str, attempt_id: str) -> RunManifest:
    qc = QCReport(status=QCStatus.PASS)
    return RunManifest(
        run_id=run_id,
        dataset_id=str(uuid4()),
        attempt_id=attempt_id,
        plan_revision=1,
        plan_hash=_PLAN_HASH,
        input_hashes={"counts": _SHA256, "metadata": "c" * 64},
        tool="deseq2",
        software_versions={
            "bioagent": "0.1.0",
            "r": "4.5.2",
            "deseq2": "1.50.2",
            "apeglm": "1.32.0",
        },
        git_commit="c96308fa37cd3377fca52fd8a666fa29c748f1ad",
        comparison=Comparison(
            factor="condition",
            numerator="AD",
            denominator="Control",
        ),
        alpha=0.05,
        lfc_shrink=True,
        random_seed=42,
        started_at=_STARTED_AT,
        ended_at=_STARTED_AT + timedelta(minutes=5),
        status=RunStatus.COMPLETED,
        qc=qc,
        approvals=(
            ApprovalRecord(
                decision="APPROVED",
                actor="user",
                decided_at=_STARTED_AT - timedelta(minutes=1),
                plan_revision=1,
                plan_hash=_PLAN_HASH,
            ),
        ),
        attempts=(
            AttemptRecord(
                attempt_id=attempt_id,
                started_at=_STARTED_AT,
                ended_at=_STARTED_AT + timedelta(minutes=5),
                status=RunStatus.COMPLETED,
                qc=qc,
            ),
        ),
        artifacts=(
            ArtifactRecord(relative_path="attempts/results/table.csv", sha256=_SHA256),
        ),
    )


def _warn_qc() -> QCReport:
    return QCReport(
        status=QCStatus.WARN,
        issues=(
            QCIssue(
                code="TEST_WARNING",
                status=QCStatus.WARN,
                message="test warning",
            ),
        ),
    )


@pytest.mark.parametrize("relative_path", ["../secret", "/secret", r"C:\secret"])
def test_artifact_record_requires_safe_relative_path(relative_path: str) -> None:
    with pytest.raises(ValidationError, match="relative_path"):
        ArtifactRecord(relative_path=relative_path, sha256=_SHA256)


@pytest.mark.parametrize("relative_path", _UNSAFE_WINDOWS_ARTIFACT_PATHS)
def test_artifact_record_rejects_unsafe_windows_path_components(
    relative_path: str,
) -> None:
    with pytest.raises(ValidationError, match="relative_path"):
        ArtifactRecord(relative_path=relative_path, sha256=_SHA256)


def test_manifest_contains_complete_provenance_fields() -> None:
    run_id = str(uuid4())
    attempt_id = str(uuid4())

    payload = _completed_manifest(run_id, attempt_id).model_dump(mode="json")

    assert payload["run_id"] == run_id
    assert payload["dataset_id"]
    assert payload["attempt_id"] == attempt_id
    assert payload["plan_revision"] == 1
    assert payload["plan_hash"] == _PLAN_HASH
    assert payload["input_hashes"] == {"counts": _SHA256, "metadata": "c" * 64}
    assert payload["tool"] == "deseq2"
    assert payload["software_versions"]["r"] == "4.5.2"
    assert payload["software_versions"]["deseq2"] == "1.50.2"
    assert payload["git_commit"] == "c96308fa37cd3377fca52fd8a666fa29c748f1ad"
    assert payload["comparison"] == {
        "factor": "condition",
        "numerator": "AD",
        "denominator": "Control",
    }
    assert payload["alpha"] == 0.05
    assert payload["lfc_shrink"] is True
    assert payload["random_seed"] == 42
    assert payload["started_at"] == "2026-08-16T08:00:00Z"
    assert payload["ended_at"] == "2026-08-16T08:05:00Z"
    assert payload["status"] == "COMPLETED"
    assert payload["qc"] == {"status": "PASS", "issues": []}
    assert payload["approvals"][0]["decision"] == "APPROVED"
    assert payload["attempts"][0]["attempt_id"] == attempt_id
    assert payload["artifacts"] == [
        {"relative_path": "attempts/results/table.csv", "sha256": _SHA256}
    ]
    assert payload["search_provenance"] is None


def test_manifest_preserves_verified_geo_search_provenance_and_old_manifests_default_none() -> None:
    manifest = _completed_manifest(str(uuid4()), str(uuid4()))
    provenance = GeoSearchProvenance(
        search_id=uuid4(),
        query_hash="a" * 64,
        provider="geo",
        selected_accession="GSE12345",
        selection_revision=2,
        retrieved_at="2026-09-14T00:00:00Z",
        evidence_sha256="b" * 64,
    )

    source_record = ArtifactRecord(relative_path="source/source.json", sha256="c" * 64)
    linked = manifest.model_copy(
        update={
            "source_id": uuid4(),
            "source_artifacts": (source_record,),
            "artifacts": (*manifest.artifacts, source_record),
            "search_provenance": provenance,
        }
    )

    assert linked.search_provenance == provenance
    old_payload = manifest.model_dump(mode="json")
    old_payload.pop("search_provenance", None)
    assert RunManifest.model_validate(old_payload).search_provenance is None


def test_manifest_nested_provenance_values_are_immutable() -> None:
    manifest = _completed_manifest(str(uuid4()), str(uuid4()))

    with pytest.raises(TypeError):
        manifest.input_hashes["counts"] = "d" * 64
    with pytest.raises(TypeError):
        manifest.software_versions["r"] = "0.0.0"
    with pytest.raises(ValidationError, match="frozen"):
        manifest.comparison.numerator = "Control"


@pytest.mark.parametrize(
    ("field_name", "corrupted_value"),
    [
        (
            "input_hashes",
            {"counts": "not-a-sha256", "metadata": "c" * 64},
        ),
        (
            "software_versions",
            {"bioagent": "0.1.0", "r": "", "deseq2": "1.50.2"},
        ),
        (
            "comparison",
            Comparison(
                factor="condition",
                numerator="Control",
                denominator="AD",
            ).model_copy(update={"denominator": "Control"}),
        ),
    ],
)
def test_manifest_write_revalidates_complete_payload_before_touching_disk(
    tmp_path: Path,
    field_name: str,
    corrupted_value: object,
) -> None:
    manager = ArtifactManager(tmp_path)
    run_id = manager.create_run()
    manifest = _completed_manifest(run_id, str(uuid4()))
    object.__setattr__(manifest, field_name, corrupted_value)

    with pytest.raises(ValidationError):
        manager.write_manifest(run_id, manifest)

    assert not manager.resolve(run_id, "manifest.json").exists()
    assert not manager.resolve(run_id, "manifest.json.tmp").exists()


def test_manifest_write_revalidates_shared_nested_qc_from_raw_payload(
    tmp_path: Path,
) -> None:
    manager = ArtifactManager(tmp_path)
    run_id = manager.create_run()
    manifest = _completed_manifest(run_id, str(uuid4()))
    object.__setattr__(manifest.qc, "status", QCStatus.WARN)

    with pytest.raises(ValidationError, match="QCReport status"):
        manager.write_manifest(run_id, manifest)

    assert not manager.resolve(run_id, "manifest.json").exists()
    assert not manager.resolve(run_id, "manifest.json.tmp").exists()


@pytest.mark.parametrize(
    ("field_name", "conflicting_value", "message"),
    [
        ("status", RunStatus.FAILED, "status must match current attempt"),
        ("qc", _warn_qc(), "qc must match current attempt"),
        (
            "ended_at",
            _STARTED_AT + timedelta(minutes=6),
            "ended_at must match current attempt",
        ),
    ],
)
def test_manifest_rejects_top_level_conflicts_with_current_attempt(
    field_name: str,
    conflicting_value: object,
    message: str,
) -> None:
    manifest = _completed_manifest(str(uuid4()), str(uuid4()))
    payload = manifest.model_dump(mode="python")
    payload[field_name] = conflicting_value

    with pytest.raises(ValidationError, match=message):
        RunManifest.model_validate(payload)


@pytest.mark.parametrize(
    ("field_name", "conflicting_value", "message"),
    [
        ("status", RunStatus.FAILED, "status must match current attempt"),
        ("qc", _warn_qc(), "qc must match current attempt"),
        (
            "ended_at",
            _STARTED_AT + timedelta(minutes=6),
            "ended_at must match current attempt",
        ),
    ],
)
def test_manifest_write_rejects_current_attempt_conflicts_before_disk_write(
    tmp_path: Path,
    field_name: str,
    conflicting_value: object,
    message: str,
) -> None:
    manager = ArtifactManager(tmp_path)
    run_id = manager.create_run()
    manifest = _completed_manifest(run_id, str(uuid4()))
    object.__setattr__(manifest, field_name, conflicting_value)

    with pytest.raises(ValidationError, match=message):
        manager.write_manifest(run_id, manifest)

    assert not manager.resolve(run_id, "manifest.json").exists()
    assert not manager.resolve(run_id, "manifest.json.tmp").exists()


def test_manifest_write_uses_tmp_file_then_atomic_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ArtifactManager(tmp_path)
    run_id = manager.create_run()
    attempt_id = str(uuid4())
    old_manifest = _completed_manifest(run_id, attempt_id)
    manager.write_manifest(run_id, old_manifest)
    manifest_path = manager.resolve(run_id, "manifest.json")
    previous_bytes = manifest_path.read_bytes()
    updated_manifest = old_manifest.model_copy(update={"git_commit": "d" * 40})
    original_replace = Path.replace
    observed: dict[str, object] = {}

    def observe_replace(source: Path, target: Path) -> Path:
        observed["source_name"] = source.name
        observed["target_name"] = target.name
        observed["tmp_exists"] = source.is_file()
        observed["old_bytes_during_replace"] = target.read_bytes()
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", observe_replace)

    result = manager.write_manifest(run_id, updated_manifest)

    assert observed == {
        "source_name": "manifest.json.tmp",
        "target_name": "manifest.json",
        "tmp_exists": True,
        "old_bytes_during_replace": previous_bytes,
    }
    assert result.relative_path == "manifest.json"
    assert json.loads(manifest_path.read_bytes())["git_commit"] == "d" * 40
    assert not manager.resolve(run_id, "manifest.json.tmp").exists()


def test_manifest_replace_failure_preserves_previous_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ArtifactManager(tmp_path)
    run_id = manager.create_run()
    manifest = _completed_manifest(run_id, str(uuid4()))
    manager.write_manifest(run_id, manifest)
    manifest_path = manager.resolve(run_id, "manifest.json")
    previous_bytes = manifest_path.read_bytes()

    def fail_replace(source: Path, target: Path) -> Path:
        raise OSError("injected replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        manager.write_manifest(
            run_id,
            manifest.model_copy(update={"git_commit": "e" * 40}),
        )

    assert manifest_path.read_bytes() == previous_bytes
    assert not manager.resolve(run_id, "manifest.json.tmp").exists()


def test_manifest_run_id_must_match_target_run(tmp_path: Path) -> None:
    manager = ArtifactManager(tmp_path)
    run_id = manager.create_run()
    manifest = _completed_manifest(str(uuid4()), str(uuid4()))

    with pytest.raises(ValueError, match="manifest run id does not match"):
        manager.write_manifest(run_id, manifest)
