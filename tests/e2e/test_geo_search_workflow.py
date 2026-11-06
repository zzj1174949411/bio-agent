from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import sleep
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import BaseMessage
from langgraph.types import Command
from pydantic import BaseModel

from bioagent.artifacts.manager import ArtifactManager
from bioagent.artifacts.manifest import RunManifest
from bioagent.datasets.repository import DatasetRepository
from bioagent.execution.controller import ExecutionController, ExecutionRejectedError
from bioagent.execution.r_runner import RRunner
from bioagent.geo.download import DownloadResult
from bioagent.geo.models import (
    Compression,
    DataKind,
    GeoCandidate,
    GeoSample,
    GeoSearchProvenance,
    GeoSource,
    SourceSelection,
)
from bioagent.geo.repository import GeoRepository, GeoRepositoryError
from bioagent.geo.search import NcbiGeoCatalogProvider
from bioagent.geo.search_repository import GeoSearchRepository
from bioagent.geo.search_service import GeoSearchService
from bioagent.geo.service import GeoImportService
from bioagent.llm.planner import AnalysisPlanner
from bioagent.retrieval.contracts import DatasetSearchQuery
from bioagent.retrieval.knowledge import (
    KnowledgeQuery,
    KnowledgeRetrievalError,
    NullKnowledgeRetriever,
)
from bioagent.services.analysis import AnalysisService
from bioagent.services.datasets import DatasetImportService
from bioagent.storage.checkpoint import sqlite_checkpoint
from bioagent.storage.runs import RunRepository
from bioagent.tools.registry import ToolRegistry
from bioagent.workflow.graph import build_graph

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_ROWS = (PROJECT_ROOT / "tests" / "fixtures" / "counts_deseq2.csv").read_text(
    encoding="utf-8"
).splitlines()
COUNTS = (
    "feature_id,GSM1,GSM2,GSM3,GSM4,GSM5,GSM6\n" + "\n".join(_FIXTURE_ROWS[1:]) + "\n"
).encode("utf-8")
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "geo"


class _FixedStructuredModel:
    def __init__(self, output: object) -> None:
        self.output = output

    def invoke(self, _messages: list[BaseMessage]) -> object:
        return self.output


class _FixedChatModel:
    def __init__(self, output: object) -> None:
        self._model = _FixedStructuredModel(output)

    def with_structured_output(
        self, _schema: type[BaseModel], *, method: str
    ) -> _FixedStructuredModel:
        assert method == "function_calling"
        return self._model


class _Discovery:
    def discover(self, accession: str) -> GeoSource:
        source_id = uuid4()
        candidate = GeoCandidate(
            id=uuid4(),
            source_id=source_id,
            accession=accession,
            url="https://fixture.invalid/GSE12345_counts.csv",
            file_name="GSE12345_counts.csv",
            data_kind=DataKind.RAW_COUNTS,
            evidence=("synthetic counts fixture",),
            compression=Compression.NONE,
        )
        return GeoSource(
            id=source_id,
            accession=accession,
            title="Synthetic GEO family",
            retrieved_at=datetime.now(UTC),
            samples=tuple(GeoSample(accession=f"GSM{index}") for index in range(1, 7)),
            candidates=(candidate,),
        )


class _Downloader:
    def __init__(self) -> None:
        self.calls = 0

    def download(self, _url: str, destination: Path, **_kwargs: object) -> DownloadResult:
        self.calls += 1
        destination.write_bytes(COUNTS)
        return DownloadResult(
            path=destination,
            sha256=sha256(COUNTS).hexdigest(),
            bytes_downloaded=len(COUNTS),
            content_type="text/csv",
            etag=None,
            last_modified=None,
        )


def _wait(read: Any) -> dict[str, object]:
    for _ in range(200):
        state = read()
        if state["status"] not in {
            "QUEUED",
            "SEARCHING",
            "DISCOVERING",
            "DOWNLOADING",
            "VALIDATING",
        }:
            return state
        sleep(0.01)
    raise AssertionError("local GEO fixture did not reach a stable state")


def _catalog() -> NcbiGeoCatalogProvider:
    esearch = json.loads((FIXTURES / "search_esearch.json").read_text(encoding="utf-8"))
    esummary = json.loads((FIXTURES / "search_esummary.json").read_text(encoding="utf-8"))

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json=esearch, request=request)
        if request.url.path.endswith("esummary.fcgi"):
            return httpx.Response(200, json=esummary, request=request)
        raise AssertionError(f"unexpected local catalog request: {request.url!s}")

    return NcbiGeoCatalogProvider(httpx.Client(transport=httpx.MockTransport(respond)))


def _renv_environment() -> dict[str, str]:
    libraries = sorted((PROJECT_ROOT / "renv/library").glob("*/R-*/**/DESeq2"))
    if not libraries:
        return {}
    return {"R_LIBS": str(libraries[0].parent), "RENV_CONFIG_AUTOLOADER_ENABLED": "FALSE"}


def test_geo_search_selection_carries_verified_provenance_to_the_completed_manifest() -> None:
    with tempfile.TemporaryDirectory(prefix="task36-geo-search-e2e-", dir=PROJECT_ROOT) as raw:
        root = Path(raw)
        datasets = DatasetRepository(root / "data")
        search_repository = GeoSearchRepository(root / "data" / "searches")
        sources = GeoRepository(root / "sources", search_repository=search_repository)
        downloader = _Downloader()
        imports = GeoImportService(
            sources,
            _Discovery(),
            downloader,
            DatasetImportService(datasets),
            search_repository=search_repository,
        )
        conversation_id, turn_id = str(uuid4()), str(uuid4())

        def create_source(
            accession: str,
            conversation: str,
            turn: str,
            provenance: GeoSearchProvenance,
        ) -> dict[str, object]:
            assert (conversation, turn) == (conversation_id, turn_id)
            return imports.create_source(
                accession,
                conversation_id=conversation,
                turn_id=turn,
                provenance=provenance,
            )

        search = GeoSearchService(
            root / "data", _catalog(), create_source, repository=search_repository
        )
        try:
            with pytest.raises(KnowledgeRetrievalError, match="^RAG_NOT_CONFIGURED$"):
                NullKnowledgeRetriever().retrieve(KnowledgeQuery(text="GEO RNA-seq protocol"))

            started = search.create(
                DatasetSearchQuery(text="brain RNA-seq"), conversation_id, turn_id
            )
            snapshot = _wait(lambda: search.get(str(started["id"])))
            assert snapshot["status"] == "AWAITING_SELECTION"
            assert downloader.calls == 0

            selected = search.select(
                str(snapshot["id"]), "GSE12345", int(snapshot["revision"])
            )
            source = _wait(lambda: imports.get_source(str(selected["source_id"])))
            assert source["status"] == "AWAITING_SELECTION"
            candidate_id = source["source"]["candidates"][0]["id"]
            requested = imports.request_import(str(selected["source_id"]), candidate_id, 1)
            mapping = _wait(lambda: imports.get_import(str(requested["id"])))
            assert mapping["status"] == "AWAITING_MAPPING"

            sample_columns = tuple(f"GSM{index}" for index in range(1, 7))
            imports.submit_selection(
                str(mapping["id"]),
                SourceSelection(
                    source_id=selected["source_id"],
                    candidate_id=candidate_id,
                    raw_sha256=mapping["raw_sha256"],
                    feature_column="feature_id",
                    sample_columns=sample_columns,
                    sample_map={column: column for column in sample_columns},
                    groups={
                        column: "Control" if index <= 3 else "AD"
                        for index, column in enumerate(sample_columns, start=1)
                    },
                    numerator="AD",
                    denominator="Control",
                    revision=1,
                    evidence=("user confirmed synthetic raw counts",),
                ),
            )
            ready = _wait(lambda: imports.get_import(str(mapping["id"])))
            assert ready["error_code"] is None, ready["error_code"]
            assert ready["status"] == "READY", ready
            assert downloader.calls == 1

            source_record = sources.read(str(ready["published_source_id"]))
            assert source_record.search_provenance is not None
            provenance = source_record.search_provenance
            assert str(provenance.search_id) == snapshot["id"]
            assert provenance.query_hash == snapshot["query_hash"]
            assert provenance.selected_accession == "GSE12345"

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
                search_repository=search_repository,
            )
            model = _FixedChatModel(
                {
                    "dataset_id": ready["dataset_id"],
                    "comparison": {
                        "factor": "condition",
                        "numerator": "AD",
                        "denominator": "Control",
                    },
                    "options": {"alpha": 0.05, "lfc_shrink": True, "random_seed": 42},
                }
            )
            with sqlite_checkpoint(root / "checkpoints.sqlite") as checkpointer:
                graph = build_graph(AnalysisPlanner(cast(Any, model)), controller, checkpointer)
                dependencies = SimpleNamespace(
                    dataset_repository=datasets,
                    artifact_manager=artifacts,
                    graph=graph,
                    run_repository=runs,
                    geo_repository=sources,
                    parse_timeout_seconds=10.0,
                )
                run_id = AnalysisService(dependencies).create_run(
                    dataset_id=str(ready["dataset_id"]),
                    goal="Compare fixture AD with Control",
                    agent_context={
                        "conversation_id": conversation_id,
                        "turn_id": turn_id,
                        "source_id": str(source_record.source_id),
                    },
                )
                run_dir = root / "runs" / run_id
                assert runs.read(run_id)["status"] == "AWAITING_APPROVAL"
                assert not list((run_dir / "attempts").glob("*"))

                completed = graph.invoke(
                    Command(resume={"action": "approve", "plan_revision": 1}),
                    {"configurable": {"thread_id": run_id}},
                )
                assert completed["status"] == "COMPLETED"

                published_source = json.loads(source_record.source_json.read_text(encoding="utf-8"))
                missing_provenance = dict(published_source)
                missing_provenance.pop("search_provenance")
                missing_provenance.pop("search_provenance_sha256")
                source_record.source_json.write_text(
                    json.dumps(missing_provenance), encoding="utf-8"
                )
                with pytest.raises(GeoRepositoryError, match="GEO_SEARCH_PROVENANCE_INVALID"):
                    AnalysisService(dependencies).create_run(
                        dataset_id=str(ready["dataset_id"]),
                        goal="Reject a selected source that dropped provenance",
                        agent_context={
                            "conversation_id": conversation_id,
                            "turn_id": turn_id,
                            "source_id": str(source_record.source_id),
                        },
                    )
                source_record.source_json.write_text(
                    json.dumps(published_source), encoding="utf-8"
                )
                forged_provenance = GeoSearchProvenance.model_validate(
                    {
                        **published_source["search_provenance"],
                        "query_hash": "c" * 64,
                    }
                )
                published_source["search_provenance"] = forged_provenance.model_dump(
                    mode="json"
                )
                published_source["search_provenance_sha256"] = (
                    forged_provenance.provenance_sha256
                )
                source_record.source_json.write_text(
                    json.dumps(published_source), encoding="utf-8"
                )
                with pytest.raises(GeoRepositoryError, match="GEO_SEARCH_PROVENANCE_INVALID"):
                    AnalysisService(dependencies).create_run(
                        dataset_id=str(ready["dataset_id"]),
                        goal="Reject forged selected-search provenance",
                        agent_context={
                            "conversation_id": conversation_id,
                            "turn_id": turn_id,
                            "source_id": str(source_record.source_id),
                        },
                    )

            manifest = RunManifest.model_validate_json((run_dir / "manifest.json").read_bytes())
            assert manifest.search_provenance == provenance
            assert manifest.source_id == source_record.source_id
            source_payload = json.loads((run_dir / "source" / "source.json").read_text())
            dataset_hashes = datasets.hashes(str(ready["dataset_id"]))
            source_artifacts = {
                artifact.relative_path: artifact.sha256 for artifact in manifest.source_artifacts
            }
            assert str(manifest.dataset_id) == ready["dataset_id"] == source_record.dataset_id
            assert manifest.input_hashes == {
                "counts": dataset_hashes.counts_sha256,
                "metadata": dataset_hashes.metadata_sha256,
            }
            assert source_record.counts_sha256 == dataset_hashes.counts_sha256
            assert source_record.metadata_sha256 == dataset_hashes.metadata_sha256
            assert source_payload["source_id"] == str(source_record.source_id)
            assert source_payload["dataset_id"] == ready["dataset_id"]
            assert source_payload["counts_sha256"] == source_record.counts_sha256
            assert source_payload["metadata_sha256"] == source_record.metadata_sha256
            assert source_payload["search_provenance_sha256"] == provenance.provenance_sha256
            assert GeoSearchProvenance.model_validate(
                source_payload["search_provenance"]
            ) == manifest.search_provenance
            assert source_artifacts["source/raw/source.bin"] == source_record.raw_sha256
            assert source_artifacts["source/normalized/counts.csv"] == source_record.counts_sha256
            assert (
                source_artifacts["source/normalized/metadata.csv"]
                == source_record.metadata_sha256
            )
            assert source_artifacts["source/source.json"] == sha256(
                (run_dir / "source" / "source.json").read_bytes()
            ).hexdigest()

            source_payload["search_provenance"]["selected_accession"] = "GSE23456"
            (run_dir / "source" / "source.json").write_text(json.dumps(source_payload))
            tampered = dict(completed)
            tampered["status"] = "QUEUED"
            with pytest.raises(ExecutionRejectedError, match="SOURCE_SEARCH_PROVENANCE_TAMPERED"):
                controller.execute(tampered)
        finally:
            search.close()
            imports.close()
