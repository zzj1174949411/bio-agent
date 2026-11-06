from __future__ import annotations

import json
import tempfile
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pandas as pd
import pytest
from langchain_core.messages import BaseMessage
from langgraph.types import Command
from pydantic import BaseModel

from bioagent.artifacts.manager import ArtifactManager
from bioagent.artifacts.manifest import AgentContext, RunManifest
from bioagent.datasets.repository import DatasetRepository
from bioagent.execution.controller import ExecutionController
from bioagent.execution.r_runner import RRunner
from bioagent.geo.models import GeoCandidate, GeoSource
from bioagent.geo.repository import GeoRepository, GeoRepositoryError
from bioagent.geo.transform import SourceSelection
from bioagent.llm.planner import AnalysisPlanner
from bioagent.services.analysis import AnalysisService
from bioagent.storage.checkpoint import sqlite_checkpoint
from bioagent.storage.runs import RunRepository
from bioagent.tools.registry import ToolRegistry
from bioagent.workflow.graph import build_graph

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COUNTS_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "counts_deseq2.csv"
METADATA_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "metadata_deseq2.csv"


class _FixedStructuredModel:
    def __init__(self, output: object) -> None:
        self.output = output

    def invoke(self, _messages: list[BaseMessage]) -> object:
        return self.output


class _FixedChatModel:
    def __init__(self, output: object) -> None:
        self.model = _FixedStructuredModel(output)

    def with_structured_output(
        self, _schema: type[BaseModel], *, method: str
    ) -> _FixedStructuredModel:
        assert method == "function_calling"
        return self.model


def _renv_environment() -> dict[str, str]:
    libraries = sorted((PROJECT_ROOT / "renv/library").glob("*/R-*/**/DESeq2"))
    if not libraries:
        return {}
    return {"R_LIBS": str(libraries[0].parent), "RENV_CONFIG_AUTOLOADER_ENABLED": "FALSE"}


def _source_fixture(root: Path, datasets: DatasetRepository, geo: GeoRepository) -> tuple[str, str]:
    counts_bytes = COUNTS_FIXTURE.read_bytes()
    metadata_bytes = METADATA_FIXTURE.read_bytes()
    dataset_id = datasets.create(counts_bytes, metadata_bytes, ".csv", ".csv")
    source_id = uuid4()
    candidate = GeoCandidate(
        id=uuid4(),
        source_id=source_id,
        accession="GSE12345",
        url="https://fixture.invalid/GSE12345_counts.csv",
        file_name="GSE12345_counts.csv",
        data_kind="RAW_COUNTS",
        evidence=("synthetic local GEO fixture",),
        compression="NONE",
    )
    source = GeoSource(
        id=source_id,
        accession="GSE12345",
        title="Synthetic GEO family",
        retrieved_at="2026-09-12T00:00:00Z",
        candidates=(candidate,),
    )
    raw_path = root / "synthetic_counts.csv"
    raw_path.write_bytes(counts_bytes)
    counts = pd.read_csv(raw_path, index_col=0)
    metadata = pd.read_csv(METADATA_FIXTURE, index_col=0)
    selection = SourceSelection(
        source_id=source_id,
        candidate_id=candidate.id,
        raw_sha256=sha256(counts_bytes).hexdigest(),
        feature_column="feature_id",
        sample_columns=tuple(str(item) for item in counts.columns),
        sample_map={str(item): str(item) for item in counts.columns},
        groups={str(item): str(metadata.loc[item, "condition"]) for item in metadata.index},
        numerator="AD",
        denominator="Control",
        revision=1,
        evidence=("user confirmed synthetic fixture mapping",),
    )
    record = geo.publish(
        source, candidate, selection, raw_path, counts, metadata, dataset_id=dataset_id
    )
    return dataset_id, str(record.source_id)


@pytest.mark.parametrize("lfc_shrink", [False, True])
def test_geo_source_is_bound_before_approval_and_registered_after_real_r_run(
    lfc_shrink: bool,
) -> None:
    with tempfile.TemporaryDirectory(prefix="task27-geo-e2e-", dir=PROJECT_ROOT) as raw:
        root = Path(raw)
        datasets = DatasetRepository(root / "data")
        geo = GeoRepository(root / "sources")
        dataset_id, source_id = _source_fixture(root, datasets, geo)
        artifacts = ArtifactManager(root / "runs")
        runs = RunRepository(root / "runs")
        controller = ExecutionController(
            project_root=PROJECT_ROOT,
            r_runner=RRunner(
                project_root=PROJECT_ROOT,
                rscript="Rscript",
                extra_env=_renv_environment(),
            ),
            dataset_repository=datasets,
            artifact_manager=artifacts,
            tool_registry=ToolRegistry(PROJECT_ROOT),
            git_commit="a" * 40,
            software_versions={"bioagent": "0.1.0", "r": "4.5.2", "deseq2": "1.50.2"},
        )
        model = _FixedChatModel(
            {
                "dataset_id": dataset_id,
                "comparison": {
                    "factor": "condition",
                    "numerator": "AD",
                    "denominator": "Control",
                },
                "options": {"alpha": 0.05, "lfc_shrink": lfc_shrink, "random_seed": 42},
            }
        )
        with sqlite_checkpoint(root / "checkpoints.sqlite") as checkpointer:
            graph = build_graph(
                AnalysisPlanner(cast(Any, model)),
                controller,
                checkpointer,
            )
            dependencies = SimpleNamespace(
                dataset_repository=datasets,
                artifact_manager=artifacts,
                graph=graph,
                run_repository=runs,
                geo_repository=geo,
                parse_timeout_seconds=10.0,
            )
            run_id = AnalysisService(dependencies).create_run(
                dataset_id=dataset_id,
                goal="Compare AD with Control from synthetic GSE12345",
                agent_context={
                    "conversation_id": str(uuid4()),
                    "turn_id": str(uuid4()),
                    "source_id": source_id,
                },
            )
            run_dir = root / "runs" / run_id
            assert runs.read(run_id)["status"] == "AWAITING_APPROVAL"
            assert not list((run_dir / "attempts").glob("*"))
            source_files = tuple((run_dir / "source").rglob("*"))
            assert {
                item.relative_to(run_dir).as_posix()
                for item in source_files
                if item.is_file()
            } >= {
                "source/raw/source.bin",
                "source/source.json",
                "source/normalized/counts.csv",
                "source/normalized/metadata.csv",
            }

            completed = graph.invoke(
                Command(resume={"action": "approve", "plan_revision": 1}),
                {"configurable": {"thread_id": run_id}},
            )
            assert completed["status"] == "COMPLETED"

        manifest = RunManifest.model_validate_json(
            (root / "runs" / run_id / "manifest.json").read_bytes()
        )
        source_records = [
            record for record in manifest.artifacts if record.relative_path.startswith("source/")
        ]
        assert source_records
        assert any(record.relative_path == "source/source.json" for record in source_records)
        for record in source_records:
            path = root / "runs" / run_id / record.relative_path
            assert sha256(path.read_bytes()).hexdigest() == record.sha256
        source_payload = json.loads((root / "runs" / run_id / "source/source.json").read_text())
        assert source_payload["source_id"] == source_id
        assert source_payload["dataset_id"] == dataset_id
        assert manifest.agent_context is not None
        assert str(manifest.agent_context.source_id) == source_id


def test_geo_source_binding_rejects_404_tamper_and_missing_counts() -> None:
    with tempfile.TemporaryDirectory(prefix="task27-geo-negative-", dir=PROJECT_ROOT) as raw:
        root = Path(raw)
        datasets = DatasetRepository(root / "data")
        geo = GeoRepository(root / "sources")
        dataset_id, source_id = _source_fixture(root, datasets, geo)
        service = AnalysisService(SimpleNamespace(geo_repository=geo))
        missing = AgentContext(
            conversation_id=uuid4(), turn_id=uuid4(), source_id=uuid4()
        )
        with pytest.raises(GeoRepositoryError, match="GEO_SOURCE_NOT_FOUND"):
            service._source_for_run(dataset_id, missing)

        record = geo.read(source_id)
        record.raw_path.write_bytes(b"tampered")
        valid = missing.model_copy(update={"source_id": record.source_id})
        with pytest.raises(GeoRepositoryError, match="GEO_SOURCE_CACHE_TAMPERED"):
            service._source_for_run(dataset_id, valid)

        second_dataset_id, second_source_id = _source_fixture(root, datasets, geo)
        restored = geo.read(second_source_id)
        restored.counts_path.unlink()
        valid = valid.model_copy(update={"source_id": restored.source_id})
        with pytest.raises(GeoRepositoryError, match="GEO_SOURCE_CACHE_TAMPERED"):
            service._source_for_run(second_dataset_id, valid)
