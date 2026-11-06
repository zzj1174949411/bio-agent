from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from langgraph.types import Command

from bioagent.artifacts.manager import ArtifactManager
from bioagent.artifacts.manifest import RunManifest
from bioagent.datasets.repository import DatasetRepository
from bioagent.domain.plans import AnalysisPlan
from bioagent.execution.controller import ExecutionController
from bioagent.llm.planner import PlanningDatasetSummary
from bioagent.storage.checkpoint import sqlite_checkpoint
from bioagent.tools.registry import ToolRegistry, ToolSpec
from bioagent.workflow.graph import build_graph

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COUNTS_BYTES = (PROJECT_ROOT / "tests" / "fixtures" / "counts_valid.csv").read_bytes()
METADATA_BYTES = (
    PROJECT_ROOT / "tests" / "fixtures" / "metadata_valid.csv"
).read_bytes()


@dataclass(frozen=True)
class RecoveryEvidence:
    completed_status: str
    old_attempt_id: str
    new_attempt_id: str
    manifest_attempt_id: str
    old_attempt_status: str
    old_stdout: str
    old_stderr: str


class SimulatedProcessCrash(BaseException):
    pass


@dataclass(frozen=True)
class FixedPlanner:
    dataset_id: str

    def plan(
        self, *, user_goal: str, summary: PlanningDatasetSummary
    ) -> AnalysisPlan:
        return AnalysisPlan(
            dataset_id=self.dataset_id,
            comparison={
                "factor": "condition",
                "numerator": "AD",
                "denominator": "Control",
            },
            options={"alpha": 0.05, "lfc_shrink": False, "random_seed": 42},
        )


class CrashAfterAttemptRunner:
    def run(self, **kwargs: Any) -> None:
        attempt_dir = kwargs["attempt_dir"]
        log_dir = attempt_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "stdout.log").write_text(
            "stdout before crash", encoding="utf-8"
        )
        (log_dir / "stderr.log").write_text(
            "stderr before crash", encoding="utf-8"
        )
        raise SimulatedProcessCrash


class SuccessfulRunner:
    def run(self, **kwargs: Any) -> None:
        attempt_dir = kwargs["attempt_dir"]
        spec = kwargs["spec"]
        log_dir = attempt_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "stdout.log").write_text("stdout recovered", encoding="utf-8")
        (log_dir / "stderr.log").write_text("", encoding="utf-8")
        _write_valid_outputs(attempt_dir, spec)


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
        attempt_dir / "results" / "significant_results.csv", index=False
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


def _controller(
    *,
    datasets: DatasetRepository,
    artifacts: ArtifactManager,
    runner: object,
) -> ExecutionController:
    return ExecutionController(
        project_root=PROJECT_ROOT,
        r_runner=runner,  # type: ignore[arg-type]
        dataset_repository=datasets,
        artifact_manager=artifacts,
        tool_registry=ToolRegistry(PROJECT_ROOT),
        git_commit="a" * 40,
        software_versions={"bioagent": "0.1.0", "r": "4.5.2", "deseq2": "1.50.2"},
    )


def _run_crash_recovery() -> RecoveryEvidence:
    with tempfile.TemporaryDirectory(prefix=".task13-recovery-", dir=PROJECT_ROOT) as raw:
        working_root = Path(raw).resolve()
        datasets = DatasetRepository(working_root / "data")
        dataset_id = datasets.create(COUNTS_BYTES, METADATA_BYTES, ".csv", ".csv")
        artifacts = ArtifactManager(working_root / "runs")
        run_id = artifacts.create_run()
        database = working_root / "checkpoints.sqlite"
        config = {"configurable": {"thread_id": run_id}}
        initial_state = {
            "run_id": run_id,
            "dataset_id": dataset_id,
            "user_goal": "Compare AD with Control, reporting AD relative to Control.",
            "summary": {
                "dataset_id": dataset_id,
                "feature_count": 2,
                "sample_count": 6,
                "categorical_levels": {"condition": ["AD", "Control"]},
            },
        }

        with sqlite_checkpoint(database) as checkpointer:
            first_graph = build_graph(
                FixedPlanner(dataset_id),
                _controller(
                    datasets=datasets,
                    artifacts=artifacts,
                    runner=CrashAfterAttemptRunner(),
                ),
                checkpointer,
            )
            paused = first_graph.invoke(initial_state, config)
            assert paused["status"] == "AWAITING_APPROVAL"
            with pytest.raises(SimulatedProcessCrash):
                first_graph.invoke(
                    Command(resume={"action": "approve", "plan_revision": 1}),
                    config,
                )

        attempts_root = artifacts.resolve(run_id, "attempts")
        old_attempt_dirs = [path for path in attempts_root.iterdir() if path.is_dir()]
        assert len(old_attempt_dirs) == 1
        old_attempt_dir = old_attempt_dirs[0]
        old_attempt_id = old_attempt_dir.name

        with sqlite_checkpoint(database) as checkpointer:
            resumed_graph = build_graph(
                FixedPlanner(dataset_id),
                _controller(
                    datasets=datasets,
                    artifacts=artifacts,
                    runner=SuccessfulRunner(),
                ),
                checkpointer,
            )
            completed = resumed_graph.invoke(
                Command(resume={"action": "approve", "plan_revision": 1}),
                config,
            )

        manifest = RunManifest.model_validate_json(
            artifacts.resolve(run_id, "manifest.json").read_bytes()
        )
        old_attempt = next(
            attempt
            for attempt in manifest.attempts
            if str(attempt.attempt_id) == old_attempt_id
        )
        new_attempt_id = str(manifest.attempt_id)
        return RecoveryEvidence(
            completed_status=str(completed["status"]),
            old_attempt_id=old_attempt_id,
            new_attempt_id=new_attempt_id,
            manifest_attempt_id=str(manifest.attempt_id),
            old_attempt_status=old_attempt.status.value,
            old_stdout=(old_attempt_dir / "logs" / "stdout.log").read_text(
                encoding="utf-8"
            ),
            old_stderr=(old_attempt_dir / "logs" / "stderr.log").read_text(
                encoding="utf-8"
            ),
        )


def test_graph_recovers_crashed_attempt_without_overwriting_logs() -> None:
    evidence = _run_crash_recovery()

    assert evidence.completed_status == "COMPLETED"
    assert evidence.old_attempt_id != evidence.new_attempt_id
    assert evidence.manifest_attempt_id == evidence.new_attempt_id
    assert evidence.old_attempt_status == "FAILED"
    assert evidence.old_stdout == "stdout before crash"
    assert evidence.old_stderr == "stderr before crash"
