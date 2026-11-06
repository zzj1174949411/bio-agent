from __future__ import annotations

import sqlite3
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pandas as pd
from langchain_core.messages import BaseMessage
from langgraph.types import Command
from pydantic import BaseModel

from bioagent.artifacts.manager import ArtifactManager
from bioagent.artifacts.manifest import RunManifest
from bioagent.datasets.repository import DatasetRepository
from bioagent.execution.controller import ExecutionController, ExecutionResult
from bioagent.execution.r_runner import RRunner, RRunResult
from bioagent.llm.planner import AnalysisPlanner
from bioagent.storage.checkpoint import sqlite_checkpoint
from bioagent.tools.registry import ToolRegistry, ToolSpec
from bioagent.workflow.graph import build_graph

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COUNTS_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "counts_deseq2.csv"
METADATA_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "metadata_deseq2.csv"


@dataclass(frozen=True)
class WorkflowEvidence:
    paused_status: str
    completed_status: str
    log2_fold_change: float
    required_artifacts_present: bool
    manifest_hashes_valid: bool
    same_attempt_reused: bool
    r_calls: int
    sqlite_checkpoint_count: int


class FixedStructuredModel:
    def __init__(self, outputs: Sequence[object]) -> None:
        self._outputs = iter(outputs)
        self.calls: list[list[BaseMessage]] = []

    def invoke(self, messages: list[BaseMessage]) -> object:
        self.calls.append(messages)
        return next(self._outputs)


class FixedChatModel:
    def __init__(self, outputs: Sequence[object]) -> None:
        self.structured_model = FixedStructuredModel(outputs)

    def with_structured_output(
        self, schema: type[BaseModel], *, method: str
    ) -> FixedStructuredModel:
        assert method == "function_calling"
        return self.structured_model


@dataclass
class CountingRRunner:
    runner: RRunner
    calls: int = 0

    def run(
        self,
        *,
        spec: ToolSpec,
        attempt_dir: Path,
        parameters: Path,
        cancelled: Any = None,
    ) -> RRunResult:
        self.calls += 1
        return self.runner.run(
            spec=spec,
            attempt_dir=attempt_dir,
            parameters=parameters,
            cancelled=cancelled,
        )


@dataclass
class RecordingExecutor:
    controller: ExecutionController
    states: list[dict[str, Any]]

    def __call__(self, state: dict[str, Any]) -> ExecutionResult:
        self.states.append(state)
        return self.controller.execute(state)


def _renv_environment() -> dict[str, str]:
    library_root = PROJECT_ROOT / "renv" / "library"
    deseq2_packages = sorted(library_root.glob("*/R-*/**/DESeq2"))
    if not deseq2_packages:
        return {}
    return {
        "R_LIBS": str(deseq2_packages[0].parent),
        "RENV_CONFIG_AUTOLOADER_ENABLED": "FALSE",
    }


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _run_real_workflow() -> WorkflowEvidence:
    with tempfile.TemporaryDirectory(prefix=".task13-e2e-", dir=PROJECT_ROOT) as raw:
        working_root = Path(raw).resolve()
        datasets = DatasetRepository(working_root / "data")
        dataset_id = datasets.create(
            COUNTS_FIXTURE.read_bytes(),
            METADATA_FIXTURE.read_bytes(),
            ".csv",
            ".csv",
        )
        artifacts = ArtifactManager(working_root / "runs")
        run_id = artifacts.create_run()
        spec = ToolRegistry(PROJECT_ROOT).get("deseq2")
        counted_runner = CountingRRunner(
            RRunner(
                project_root=PROJECT_ROOT,
                rscript="Rscript",
                extra_env=_renv_environment(),
            )
        )
        controller = ExecutionController(
            project_root=PROJECT_ROOT,
            r_runner=counted_runner,
            dataset_repository=datasets,
            artifact_manager=artifacts,
            tool_registry=ToolRegistry(PROJECT_ROOT),
            git_commit="a" * 40,
            software_versions={"bioagent": "0.1.0", "r": "4.5.2", "deseq2": "1.50.2"},
        )
        executor = RecordingExecutor(controller=controller, states=[])
        model = FixedChatModel(
            [
                {
                    "dataset_id": dataset_id,
                    "comparison": {
                        "factor": "condition",
                        "numerator": "AD",
                        "denominator": "Control",
                    },
                    "options": {
                        "alpha": 0.05,
                        "lfc_shrink": False,
                        "random_seed": 42,
                    },
                }
            ]
        )
        planner = AnalysisPlanner(cast(Any, model))
        database = working_root / "checkpoints.sqlite"
        config = {"configurable": {"thread_id": run_id}}
        initial_state = {
            "run_id": run_id,
            "dataset_id": dataset_id,
            "user_goal": "Compare AD with Control, reporting AD relative to Control.",
            "summary": {
                "dataset_id": dataset_id,
                "feature_count": 200,
                "sample_count": 6,
                "categorical_levels": {"condition": ["AD", "Control"]},
            },
        }

        with sqlite_checkpoint(database) as checkpointer:
            graph = build_graph(planner, executor, checkpointer)
            paused = graph.invoke(initial_state, config)
            completed = graph.invoke(
                Command(resume={"action": "approve", "plan_revision": 1}),
                config,
            )

        manifest_path = artifacts.resolve(run_id, "manifest.json")
        manifest = RunManifest.model_validate_json(manifest_path.read_bytes())
        attempt_id = str(manifest.attempt_id)
        result_table = pd.read_csv(
            artifacts.resolve(
                run_id, f"attempts/{attempt_id}/results/all_results.csv"
            )
        )
        log2_fold_change = float(
            result_table.loc[
                result_table["feature_id"] == "GENE_001", "log2FoldChange"
            ].iloc[0]
        )
        required_artifacts_present = all(
            artifacts.resolve(run_id, f"attempts/{attempt_id}/{relative}").is_file()
            for relative in spec.required_artifacts
        )
        manifest_hashes_valid = all(
            artifacts.resolve(run_id, record.relative_path).is_file()
            and _digest(artifacts.resolve(run_id, record.relative_path)) == record.sha256
            for record in manifest.artifacts
        )
        dataset_hashes = datasets.hashes(dataset_id)
        manifest_hashes_valid = manifest_hashes_valid and dict(
            manifest.input_hashes
        ) == {
            "counts": dataset_hashes.counts_sha256,
            "metadata": dataset_hashes.metadata_sha256,
        }
        manifest_hashes_valid = manifest_hashes_valid and (
            manifest.comparison.numerator == "AD"
            and manifest.comparison.denominator == "Control"
        )

        repeated = controller.execute(cast(Mapping[str, object], executor.states[0]))
        with closing(sqlite3.connect(database)) as connection:
            checkpoint_count = cast(
                int,
                connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0],
            )

        return WorkflowEvidence(
            paused_status=str(paused["status"]),
            completed_status=str(completed["status"]),
            log2_fold_change=log2_fold_change,
            required_artifacts_present=required_artifacts_present,
            manifest_hashes_valid=manifest_hashes_valid,
            same_attempt_reused=(
                repeated.reused and repeated.attempt_id == str(manifest.attempt_id)
            ),
            r_calls=counted_runner.calls,
            sqlite_checkpoint_count=checkpoint_count,
        )


def test_bulk_workflow_runs_real_deseq2_once_after_approval() -> None:
    evidence = _run_real_workflow()

    assert evidence.paused_status == "AWAITING_APPROVAL"
    assert evidence.completed_status == "COMPLETED"
    assert evidence.log2_fold_change > 0
    assert evidence.required_artifacts_present
    assert evidence.manifest_hashes_valid
    assert evidence.same_attempt_reused
    assert evidence.r_calls == 1
    assert evidence.sqlite_checkpoint_count > 0
