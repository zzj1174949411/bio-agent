from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import pandas as pd
import pytest

from bioagent.artifacts.manager import ArtifactManager
from bioagent.artifacts.manifest import RunManifest
from bioagent.datasets.repository import DatasetIntegrityError, DatasetRepository
from bioagent.domain.plans import AnalysisOptions, AnalysisPlan, Comparison
from bioagent.domain.qc import QCStatus
from bioagent.domain.runs import RunStatus
from bioagent.execution.controller import (
    ExecutionController,
    ExecutionRejectedError,
    calculate_plan_hash,
)
from bioagent.execution.r_runner import RExecutionFailedError
from bioagent.geo.models import GeoSearchProvenance
from bioagent.geo.search_repository import (
    GeoSearchRecord,
    GeoSearchRepository,
    GeoSearchStatus,
)
from bioagent.retrieval.contracts import DatasetSearchHit, DatasetSearchQuery, EvidenceRef
from bioagent.tools.registry import ToolRegistry, ToolSpec

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COUNTS_BYTES = (PROJECT_ROOT / "tests" / "fixtures" / "counts_valid.csv").read_bytes()
METADATA_BYTES = (PROJECT_ROOT / "tests" / "fixtures" / "metadata_valid.csv").read_bytes()
STARTED_AT = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)


def _plan(dataset_id: str, *, alpha: float = 0.05) -> AnalysisPlan:
    return AnalysisPlan(
        dataset_id=dataset_id,
        comparison=Comparison(
            factor="condition",
            numerator="AD",
            denominator="Control",
        ),
        options=AnalysisOptions(alpha=alpha),
    )


def _state(run_id: str, plan: AnalysisPlan) -> dict[str, object]:
    return {
        "run_id": run_id,
        "dataset_id": plan.dataset_id,
        "status": "QUEUED",
        "plan": plan.model_dump(mode="json"),
        "plan_revision": 1,
        "approval": {
            "action": "approve",
            "status": "APPROVED",
            "actor": "user",
            "decided_at": "2026-08-31T07:59:00Z",
            "plan_revision": 1,
            "plan_hash": calculate_plan_hash(plan),
        },
    }


def _write_valid_outputs(attempt_dir: Path, spec: ToolSpec) -> None:
    for artifact in spec.required_artifacts:
        path = attempt_dir / artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    sample_ids = ("AD_1", "AD_2", "AD_3", "CTRL_1", "CTRL_2", "CTRL_3")
    all_results = pd.DataFrame(
        {
            "feature_id": ["GENE_1", "GENE_2"],
            "baseMean": [10.0, 20.0],
            "log2FoldChange": [1.0, -1.0],
            "lfcSE": [0.1, 0.2],
            "stat": [10.0, -5.0],
            "pvalue": [0.001, 0.2],
            "padj": [0.002, 0.4],
        }
    )
    all_results.to_csv(attempt_dir / "results" / "all_results.csv", index=False)
    all_results.iloc[[0]].to_csv(
        attempt_dir / "results" / "significant_results.csv",
        index=False,
    )
    pd.DataFrame(
        {
            "feature_id": ["GENE_1", "GENE_2"],
            **{sample_id: [10.0, 20.0] for sample_id in sample_ids},
        }
    ).to_csv(attempt_dir / "results" / "normalized_counts.csv", index=False)
    pd.DataFrame(
        {
            "PC1": [3.0, 2.0, 1.0, -1.0, -2.0, -3.0],
            "PC2": [0.5, -0.5, 0.25, -0.25, 0.75, -0.75],
            "sample_id": sample_ids,
            "factor_level": ["AD", "AD", "AD", "Control", "Control", "Control"],
        }
    ).to_csv(attempt_dir / "results" / "pca.csv", index=False)
    pd.DataFrame(
        {"sample_id": sample_ids, "size_factor": [1.0] * len(sample_ids)}
    ).to_csv(attempt_dir / "results" / "size_factors.csv", index=False)
    (attempt_dir / "results" / "execution_summary.json").write_text(
        json.dumps({"status": "success", "n_features": 2, "n_samples": 6}),
        encoding="utf-8",
    )


@dataclass
class FakeRRunner:
    failures_remaining: int = 0
    calls: list[dict[str, Any]] = field(default_factory=list)

    def run(self, **kwargs: Any) -> Mock:
        self.calls.append(kwargs)
        attempt_dir = kwargs["attempt_dir"]
        spec = kwargs["spec"]
        log_dir = attempt_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        call_number = len(self.calls)
        (log_dir / "stdout.log").write_text(
            f"stdout attempt {call_number}", encoding="utf-8"
        )
        (log_dir / "stderr.log").write_text(
            f"stderr attempt {call_number}", encoding="utf-8"
        )
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RExecutionFailedError(17)
        _write_valid_outputs(attempt_dir, spec)
        return Mock(returncode=0)


@dataclass
class ControllerHarness:
    controller: ExecutionController
    runner: FakeRRunner
    datasets: DatasetRepository
    artifacts: ArtifactManager
    run_id: str
    plan: AnalysisPlan


def _harness(
    tmp_path: Path,
    *,
    failures: int = 0,
    search_repository: GeoSearchRepository | None = None,
) -> ControllerHarness:
    project_root = tmp_path / "project"
    project_root.mkdir()
    datasets = DatasetRepository(project_root / "data")
    dataset_id = datasets.create(COUNTS_BYTES, METADATA_BYTES, ".csv", ".csv")
    artifacts = ArtifactManager(project_root / "runs")
    run_id = artifacts.create_run()
    runner = FakeRRunner(failures_remaining=failures)
    controller = ExecutionController(
        project_root=project_root,
        r_runner=runner,
        dataset_repository=datasets,
        artifact_manager=artifacts,
        tool_registry=ToolRegistry(PROJECT_ROOT),
        git_commit="a" * 40,
        software_versions={
            "bioagent": "0.1.0",
            "r": "4.5.2",
            "deseq2": "1.50.2",
            "apeglm": "1.32.0",
        },
        clock=lambda: STARTED_AT,
        search_repository=search_repository,
    )
    return ControllerHarness(
        controller=controller,
        runner=runner,
        datasets=datasets,
        artifacts=artifacts,
        run_id=run_id,
        plan=_plan(dataset_id),
    )


def test_same_plan_has_same_hash() -> None:
    plan = _plan("b8b439c9-c576-4f87-ae41-69e0810c38c9")

    first = calculate_plan_hash(plan)
    second = calculate_plan_hash(plan)

    assert first == second
    assert len(first) == 64


def test_plan_hash_changes_when_alpha_changes() -> None:
    dataset_id = "b8b439c9-c576-4f87-ae41-69e0810c38c9"

    assert calculate_plan_hash(_plan(dataset_id)) != calculate_plan_hash(
        _plan(dataset_id, alpha=0.01)
    )


def test_plan_hash_matches_known_sha256() -> None:
    plan = _plan("b8b439c9-c576-4f87-ae41-69e0810c38c9")

    assert calculate_plan_hash(plan) == (
        "18b2beeaf009656bb40cbea790332d46"
        "bcb4cae523d91934d6eac656e9302b1f"
    )


def test_controller_rejects_unapproved_plan_before_runner_call(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    state = _state(harness.run_id, harness.plan)
    state["approval"] = {"status": "PENDING", "plan_revision": 1}

    with pytest.raises(ExecutionRejectedError, match="PLAN_NOT_APPROVED"):
        harness.controller.execute(state)

    assert harness.runner.calls == []


def test_controller_rejects_tampered_search_provenance_before_runner_call(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    source_id = uuid4()
    provenance = GeoSearchProvenance(
        search_id=uuid4(),
        query_hash="a" * 64,
        provider="geo",
        selected_accession="GSE12345",
        selection_revision=3,
        retrieved_at="2026-09-14T00:00:00Z",
        evidence_sha256="b" * 64,
    )
    raw, counts, metadata = b"raw", b"counts", b"metadata"
    harness.artifacts.write_bytes(harness.run_id, "source/raw/source.bin", raw)
    harness.artifacts.write_bytes(harness.run_id, "source/normalized/counts.csv", counts)
    harness.artifacts.write_bytes(harness.run_id, "source/normalized/metadata.csv", metadata)
    source_payload = {
        "source_id": str(source_id),
        "dataset_id": harness.plan.dataset_id,
        "accession": "GSE12345",
        "raw_sha256": sha256(raw).hexdigest(),
        "counts_sha256": sha256(counts).hexdigest(),
        "metadata_sha256": sha256(metadata).hexdigest(),
        "search_provenance": {
            **provenance.model_dump(mode="json"),
            "selected_accession": "GSE23456",
        },
        "search_provenance_sha256": provenance.provenance_sha256,
    }
    harness.artifacts.write_json(harness.run_id, "source/source.json", source_payload)
    state = _state(harness.run_id, harness.plan)
    state["agent_context"] = {
        "conversation_id": str(uuid4()),
        "turn_id": str(uuid4()),
        "source_id": str(source_id),
    }

    with pytest.raises(ExecutionRejectedError, match="SOURCE_SEARCH_PROVENANCE_TAMPERED"):
        harness.controller.execute(state)

    assert harness.runner.calls == []


def test_controller_rejects_self_consistent_forged_search_provenance_against_snapshot(
    tmp_path: Path,
) -> None:
    source_id = uuid4()
    query = DatasetSearchQuery(text="brain")
    verified = GeoSearchProvenance(
        search_id=uuid4(),
        query_hash=query.query_hash,
        provider="geo",
        selected_accession="GSE12345",
        selection_revision=3,
        retrieved_at="2026-09-14T00:00:00Z",
        evidence_sha256="b" * 64,
    )
    search_repository = GeoSearchRepository(tmp_path / "searches")
    search_repository.write(
        GeoSearchRecord(
            id=verified.search_id,
            status=GeoSearchStatus.SELECTED,
            revision=4,
            query=query,
            query_hash=query.query_hash,
            items=(
                DatasetSearchHit(
                    provider="geo",
                    source_id="GSE12345",
                    title="fixture",
                    source_uri="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345",
                    evidence=EvidenceRef(
                        provider="geo",
                        source_id="GSE12345",
                        source_uri="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345",
                        retrieved_at=verified.retrieved_at,
                        content_sha256=verified.evidence_sha256,
                    ),
                ),
            ),
            total=1,
            conversation_id=uuid4(),
            turn_id=uuid4(),
            source_id=str(source_id),
            selected_accession=verified.selected_accession,
            selection_revision=verified.selection_revision,
        )
    )
    harness = _harness(tmp_path, search_repository=search_repository)
    forged = verified.model_copy(update={"query_hash": "c" * 64})
    raw, counts, metadata = b"raw", b"counts", b"metadata"
    harness.artifacts.write_bytes(harness.run_id, "source/raw/source.bin", raw)
    harness.artifacts.write_bytes(harness.run_id, "source/normalized/counts.csv", counts)
    harness.artifacts.write_bytes(harness.run_id, "source/normalized/metadata.csv", metadata)
    harness.artifacts.write_json(
        harness.run_id,
        "source/source.json",
        {
            "source_id": str(source_id),
            "dataset_id": harness.plan.dataset_id,
            "accession": forged.selected_accession,
            "raw_sha256": sha256(raw).hexdigest(),
            "counts_sha256": sha256(counts).hexdigest(),
            "metadata_sha256": sha256(metadata).hexdigest(),
            "search_provenance": forged.model_dump(mode="json"),
            "search_provenance_sha256": forged.provenance_sha256,
        },
    )
    state = _state(harness.run_id, harness.plan)
    state["agent_context"] = {
        "conversation_id": str(uuid4()),
        "turn_id": str(uuid4()),
        "source_id": str(source_id),
    }

    with pytest.raises(ExecutionRejectedError, match="SOURCE_SEARCH_PROVENANCE_TAMPERED"):
        harness.controller.execute(state)

    assert harness.runner.calls == []


def test_controller_rejects_selected_source_when_copied_provenance_is_missing(
    tmp_path: Path,
) -> None:
    source_id = uuid4()
    query = DatasetSearchQuery(text="brain")
    provenance = GeoSearchProvenance(
        search_id=uuid4(),
        query_hash=query.query_hash,
        provider="geo",
        selected_accession="GSE12345",
        selection_revision=1,
        retrieved_at=STARTED_AT,
        evidence_sha256="a" * 64,
    )
    search_repository = GeoSearchRepository(tmp_path / "searches")
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
                    source_id="GSE12345",
                    title="fixture",
                    source_uri="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345",
                    evidence=EvidenceRef(
                        provider="geo",
                        source_id="GSE12345",
                        source_uri="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345",
                        retrieved_at=STARTED_AT,
                        content_sha256="a" * 64,
                    ),
                ),
            ),
            total=1,
            conversation_id=uuid4(),
            turn_id=uuid4(),
            source_id=str(source_id),
            selected_accession="GSE12345",
            selection_revision=1,
        )
    )
    harness = _harness(tmp_path, search_repository=search_repository)
    raw, counts, metadata = b"raw", b"counts", b"metadata"
    harness.artifacts.write_bytes(harness.run_id, "source/raw/source.bin", raw)
    harness.artifacts.write_bytes(harness.run_id, "source/normalized/counts.csv", counts)
    harness.artifacts.write_bytes(harness.run_id, "source/normalized/metadata.csv", metadata)
    harness.artifacts.write_json(
        harness.run_id,
        "source/source.json",
        {
            "source_id": str(source_id),
            "dataset_id": harness.plan.dataset_id,
            "accession": "GSE12345",
            "raw_sha256": sha256(raw).hexdigest(),
            "counts_sha256": sha256(counts).hexdigest(),
            "metadata_sha256": sha256(metadata).hexdigest(),
        },
    )
    state = _state(harness.run_id, harness.plan)
    state["agent_context"] = {
        "conversation_id": str(uuid4()),
        "turn_id": str(uuid4()),
        "source_id": str(source_id),
    }

    with pytest.raises(ExecutionRejectedError, match="SOURCE_SEARCH_PROVENANCE_TAMPERED"):
        harness.controller.execute(state)

    assert harness.runner.calls == []


@pytest.mark.parametrize(
    ("state_update", "approval_update", "expected_code"),
    [
        ({"status": "COMPLETED"}, {}, "RUN_STATUS_INVALID"),
        ({}, {"action": "reject"}, "PLAN_NOT_APPROVED"),
    ],
)
def test_controller_rejects_invalid_execution_state_before_runner_call(
    tmp_path: Path,
    state_update: dict[str, object],
    approval_update: dict[str, object],
    expected_code: str,
) -> None:
    harness = _harness(tmp_path)
    state = _state(harness.run_id, harness.plan)
    state.update(state_update)
    approval = state["approval"]
    assert isinstance(approval, dict)
    approval.update(approval_update)

    with pytest.raises(ExecutionRejectedError, match=expected_code):
        harness.controller.execute(state)

    assert harness.runner.calls == []


def test_controller_rejects_changed_plan_with_old_approval(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    changed_plan = _plan(harness.plan.dataset_id, alpha=0.01)
    state = _state(harness.run_id, changed_plan)
    approval = state["approval"]
    assert isinstance(approval, dict)
    approval["plan_hash"] = calculate_plan_hash(harness.plan)

    with pytest.raises(ExecutionRejectedError, match="PLAN_HASH_MISMATCH"):
        harness.controller.execute(state)

    assert harness.runner.calls == []


def test_controller_rejects_old_approval_revision(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    state = _state(harness.run_id, harness.plan)
    state["plan_revision"] = 2

    with pytest.raises(ExecutionRejectedError, match="PLAN_REVISION_MISMATCH"):
        harness.controller.execute(state)

    assert harness.runner.calls == []


def test_controller_requires_persisted_approval_audit_fields(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    state = _state(harness.run_id, harness.plan)
    approval = state["approval"]
    assert isinstance(approval, dict)
    del approval["decided_at"]

    with pytest.raises(ExecutionRejectedError, match="APPROVAL_INVALID"):
        harness.controller.execute(state)

    assert harness.runner.calls == []


def test_controller_rechecks_dataset_hash_before_runner_call(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    counts_path, _ = harness.datasets.paths(harness.plan.dataset_id)
    counts_path.write_text("feature_id,S1\nG1,1\n", encoding="utf-8")

    with pytest.raises(DatasetIntegrityError, match="counts SHA-256 mismatch"):
        harness.controller.execute(_state(harness.run_id, harness.plan))

    assert harness.runner.calls == []


def test_controller_revalidates_dataset_contents_before_runner_call(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    datasets = DatasetRepository(project_root / "data")
    dataset_id = datasets.create(
        b"feature_id,AD_1,AD_2,CTRL_1,CTRL_2\nGENE_1,10,-1,2,3\n",
        (
            b"sample_id,condition\nAD_1,AD\nAD_2,AD\n"
            b"CTRL_1,Control\nCTRL_2,Control\n"
        ),
        ".csv",
        ".csv",
    )
    artifacts = ArtifactManager(project_root / "runs")
    run_id = artifacts.create_run()
    runner = FakeRRunner()
    controller = ExecutionController(
        project_root=project_root,
        r_runner=runner,
        dataset_repository=datasets,
        artifact_manager=artifacts,
        tool_registry=ToolRegistry(PROJECT_ROOT),
        git_commit="a" * 40,
        software_versions={"r": "4.5.2", "deseq2": "1.50.2"},
    )
    plan = _plan(dataset_id)

    with pytest.raises(ExecutionRejectedError, match="DATASET_VALIDATION_FAILED"):
        controller.execute(_state(run_id, plan))

    assert runner.calls == []


def test_controller_runs_tool_writes_attempt_and_manifest(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    state = _state(harness.run_id, harness.plan)

    execution_key = harness.controller.execution_key(state)
    result = harness.controller.execute(state)

    assert result.execution_key == execution_key
    assert result.status is RunStatus.COMPLETED
    assert result.qc.status is QCStatus.PASS
    assert result.reused is False
    assert len(harness.runner.calls) == 1
    attempt_prefix = f"attempts/{result.attempt_id}"
    attempt_dir = harness.artifacts.resolve(harness.run_id, attempt_prefix)
    parameters = json.loads((attempt_dir / "parameters.json").read_text(encoding="utf-8"))
    assert parameters["counts_path"].endswith(f"runs/{harness.run_id}/input/counts.csv")
    assert parameters["metadata_path"].endswith(
        f"runs/{harness.run_id}/input/metadata.csv"
    )
    assert parameters["output_dir"].endswith(attempt_prefix)
    attempt_record = json.loads(
        (attempt_dir / "attempt.json").read_text(encoding="utf-8")
    )
    assert attempt_record["status"] == "COMPLETED"
    assert attempt_record["qc"]["status"] == "PASS"
    manifest = json.loads(
        harness.artifacts.resolve(harness.run_id, "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["attempt_id"] == result.attempt_id
    assert manifest["status"] == "COMPLETED"
    assert manifest["plan_hash"] == calculate_plan_hash(harness.plan)
    hashes = harness.datasets.hashes(harness.plan.dataset_id)
    assert manifest["input_hashes"] == {
        "counts": hashes.counts_sha256,
        "metadata": hashes.metadata_sha256,
    }
    artifact_paths = {artifact["relative_path"] for artifact in manifest["artifacts"]}
    assert f"{attempt_prefix}/logs/stdout.log" in artifact_paths
    assert f"{attempt_prefix}/logs/stderr.log" in artifact_paths
    assert f"{attempt_prefix}/results/all_results.csv" in artifact_paths


def test_controller_reuses_completed_identical_plan(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    state = _state(harness.run_id, harness.plan)

    first = harness.controller.execute(state)
    second = harness.controller.execute(state)

    assert first.attempt_id == second.attempt_id
    assert second.reused is True
    assert len(harness.runner.calls) == 1


@pytest.mark.parametrize("new_plan", [False, True])
def test_execution_manifest_does_not_republish_previous_report(
    tmp_path: Path, new_plan: bool
) -> None:
    harness = _harness(tmp_path)
    state = _state(harness.run_id, harness.plan)
    harness.controller.execute(state)
    report = harness.artifacts.write_bytes(harness.run_id, "report/report.html", b"old report")
    manifest_path = harness.artifacts.resolve(harness.run_id, "manifest.json")
    previous = RunManifest.model_validate_json(manifest_path.read_bytes())
    harness.artifacts.write_manifest(
        harness.run_id, previous.model_copy(update={"artifacts": (*previous.artifacts, report)})
    )
    if new_plan:
        state = _state(harness.run_id, _plan(harness.plan.dataset_id, alpha=0.01))
        state["plan_revision"] = 2
        state["approval"]["plan_revision"] = 2

    result = harness.controller.execute(state)

    assert result.reused is not new_plan
    updated = RunManifest.model_validate_json(manifest_path.read_bytes())
    assert "report/report.html" not in {item.relative_path for item in updated.artifacts}
    assert (
        harness.artifacts.resolve(harness.run_id, "report/report.html").read_bytes()
        == b"old report"
    )
    assert len(harness.runner.calls) == (2 if new_plan else 1)


def test_run_rejects_replaced_dataset_without_overwriting_input_snapshot(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    state = _state(harness.run_id, harness.plan)
    harness.controller.execute(state)
    snapshot = harness.artifacts.resolve(harness.run_id, "input/counts.csv")
    original_snapshot = snapshot.read_bytes()
    counts_path, _ = harness.datasets.paths(harness.plan.dataset_id)
    changed_counts = COUNTS_BYTES.replace(b"GENE_1,120", b"GENE_1,121")
    counts_path.write_bytes(changed_counts)
    dataset_record_path = counts_path.parent / "dataset.json"
    dataset_record = json.loads(dataset_record_path.read_text(encoding="utf-8"))
    dataset_record["counts_sha256"] = sha256(changed_counts).hexdigest()
    dataset_record_path.write_text(
        json.dumps(dataset_record, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(ExecutionRejectedError, match="RUN_INPUT_HASH_MISMATCH"):
        harness.controller.execute(state)

    assert snapshot.read_bytes() == original_snapshot
    assert len(harness.runner.calls) == 1


def test_controller_rejects_corrupt_manifest_without_overwriting_it(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    state = _state(harness.run_id, harness.plan)
    harness.controller.execute(state)
    manifest_path = harness.artifacts.resolve(harness.run_id, "manifest.json")
    corrupt_bytes = b"{not-valid-json"
    manifest_path.write_bytes(corrupt_bytes)

    with pytest.raises(ExecutionRejectedError, match="MANIFEST_INVALID"):
        harness.controller.execute(state)

    assert manifest_path.read_bytes() == corrupt_bytes
    assert len(harness.runner.calls) == 1


def test_controller_rejects_manifest_owned_by_another_run(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    state = _state(harness.run_id, harness.plan)
    harness.controller.execute(state)
    manifest_path = harness.artifacts.resolve(harness.run_id, "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["run_id"] = str(uuid4())
    foreign_manifest = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    manifest_path.write_bytes(foreign_manifest)

    with pytest.raises(ExecutionRejectedError, match="MANIFEST_RUN_ID_MISMATCH"):
        harness.controller.execute(state)

    assert manifest_path.read_bytes() == foreign_manifest
    assert len(harness.runner.calls) == 1


def test_controller_does_not_reuse_tampered_required_artifact(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    state = _state(harness.run_id, harness.plan)
    first = harness.controller.execute(state)
    first_result = harness.artifacts.resolve(
        harness.run_id,
        f"attempts/{first.attempt_id}/results/all_results.csv",
    )
    first_result.write_text("corrupted", encoding="utf-8")

    second = harness.controller.execute(state)

    assert second.attempt_id != first.attempt_id
    assert second.reused is False
    assert len(harness.runner.calls) == 2


def test_controller_does_not_reuse_unrecorded_tampered_parameters(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    state = _state(harness.run_id, harness.plan)
    first = harness.controller.execute(state)
    manifest_path = harness.artifacts.resolve(harness.run_id, "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parameter_artifact = f"attempts/{first.attempt_id}/parameters.json"
    manifest["artifacts"] = [
        artifact
        for artifact in manifest["artifacts"]
        if artifact["relative_path"] != parameter_artifact
    ]
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    parameter_path = harness.artifacts.resolve(harness.run_id, parameter_artifact)
    parameters = json.loads(parameter_path.read_text(encoding="utf-8"))
    parameters["alpha"] = 0.01
    parameter_path.write_text(
        json.dumps(parameters, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    second = harness.controller.execute(state)

    assert second.attempt_id != first.attempt_id
    assert second.reused is False
    assert len(harness.runner.calls) == 2


def test_reuse_backfills_missing_required_artifact_record(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    state = _state(harness.run_id, harness.plan)
    first = harness.controller.execute(state)
    manifest_path = harness.artifacts.resolve(harness.run_id, "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required_artifact = f"attempts/{first.attempt_id}/figures/volcano_plot.pdf"
    manifest["artifacts"] = [
        artifact
        for artifact in manifest["artifacts"]
        if artifact["relative_path"] != required_artifact
    ]
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    reused = harness.controller.execute(state)

    assert reused.attempt_id == first.attempt_id
    assert reused.reused is True
    assert len(harness.runner.calls) == 1
    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert required_artifact in {
        artifact["relative_path"] for artifact in updated["artifacts"]
    }


def test_failed_attempt_retry_keeps_old_logs_and_uses_new_attempt(tmp_path: Path) -> None:
    harness = _harness(tmp_path, failures=1)
    state = _state(harness.run_id, harness.plan)

    failed = harness.controller.execute(state)

    assert failed.status is RunStatus.FAILED
    assert failed.qc.issues[0].code == "R_EXECUTION_FAILED"

    failed_manifest = json.loads(
        harness.artifacts.resolve(harness.run_id, "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    failed_attempt_id = failed_manifest["attempt_id"]
    failed_stdout = harness.artifacts.resolve(
        harness.run_id,
        f"attempts/{failed_attempt_id}/logs/stdout.log",
    )
    failed_stderr = harness.artifacts.resolve(
        harness.run_id,
        f"attempts/{failed_attempt_id}/logs/stderr.log",
    )
    original_stdout = failed_stdout.read_text(encoding="utf-8")
    original_stderr = failed_stderr.read_text(encoding="utf-8")

    completed = harness.controller.execute(state)

    assert completed.attempt_id != failed_attempt_id
    assert failed_stdout.read_text(encoding="utf-8") == original_stdout
    assert failed_stderr.read_text(encoding="utf-8") == original_stderr
    manifest = json.loads(
        harness.artifacts.resolve(harness.run_id, "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert [attempt["status"] for attempt in manifest["attempts"]] == [
        "FAILED",
        "COMPLETED",
    ]


def test_interrupted_attempt_is_recovered_into_next_manifest(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    state = _state(harness.run_id, harness.plan)
    interrupted_id = str(uuid4())
    interrupted_dir = harness.artifacts.resolve(
        harness.run_id, f"attempts/{interrupted_id}"
    )
    interrupted_dir.mkdir()
    harness.artifacts.write_json(
        harness.run_id,
        f"attempts/{interrupted_id}/attempt.json",
        {
            "attempt_id": interrupted_id,
            "started_at": "2026-08-31T07:50:00Z",
            "ended_at": None,
            "status": "RUNNING",
            "qc": None,
        },
    )
    logs = interrupted_dir / "logs"
    logs.mkdir()
    (logs / "stdout.log").write_text("interrupted stdout", encoding="utf-8")
    (logs / "stderr.log").write_text("interrupted stderr", encoding="utf-8")

    completed = harness.controller.execute(state)

    assert completed.status is RunStatus.COMPLETED
    manifest = json.loads(
        harness.artifacts.resolve(harness.run_id, "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert [attempt["status"] for attempt in manifest["attempts"]] == [
        "FAILED",
        "COMPLETED",
    ]
    assert manifest["attempts"][0]["attempt_id"] == interrupted_id
    assert manifest["attempts"][0]["qc"]["issues"][0]["code"] == (
        "EXECUTION_INTERRUPTED"
    )
    artifact_paths = {artifact["relative_path"] for artifact in manifest["artifacts"]}
    assert f"attempts/{interrupted_id}/logs/stdout.log" in artifact_paths
    assert f"attempts/{interrupted_id}/logs/stderr.log" in artifact_paths
