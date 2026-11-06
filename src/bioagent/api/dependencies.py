from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from threading import RLock, local
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import Request
from langgraph.checkpoint.base import BaseCheckpointSaver

from bioagent.artifacts.manager import ArtifactManager
from bioagent.artifacts.manifest import RunManifest
from bioagent.config import Settings
from bioagent.datasets.repository import DatasetRepository
from bioagent.domain.plans import AnalysisPlan
from bioagent.domain.runs import RunStatus
from bioagent.execution.controller import ExecutionController, calculate_plan_hash
from bioagent.execution.job_runner import JobStatus, LocalJobRunner
from bioagent.execution.r_runner import RRunner
from bioagent.extensions.gateway import ToolGateway
from bioagent.extensions.mcp_client import McpClientAdapter
from bioagent.extensions.store import SkillStore
from bioagent.geo.client import GeoClient
from bioagent.geo.download import GeoDownloader
from bioagent.geo.repository import GeoRepository, GeoRepositoryError
from bioagent.geo.search import NcbiGeoCatalogProvider
from bioagent.geo.search_repository import (
    GeoSearchRepository,
    GeoSearchRepositoryError,
    GeoSearchStatus,
)
from bioagent.geo.search_service import GeoSearchService
from bioagent.geo.service import GeoImportService
from bioagent.geo.transport import GeoTransport
from bioagent.knowledge.answers import AnswerService
from bioagent.knowledge.retrieval import RetrievalEngine
from bioagent.knowledge.service import KnowledgeService
from bioagent.knowledge.store import KnowledgeStore
from bioagent.knowledge.wiki import WikiService
from bioagent.llm.factory import create_chat_model
from bioagent.llm.planner import AnalysisPlanner
from bioagent.models.adapters import ModelAdapter
from bioagent.models.secrets import SecretStore, SystemSecretStore
from bioagent.models.store import ModelProfileStore
from bioagent.reporting.workflow import ArtifactReporter
from bioagent.retrieval.knowledge import KnowledgeRetriever, NullKnowledgeRetriever
from bioagent.services.analysis import AnalysisService
from bioagent.services.datasets import DatasetImportService
from bioagent.storage.checkpoint import sqlite_checkpoint
from bioagent.storage.runs import RunRepository
from bioagent.tools.registry import ToolRegistry
from bioagent.workbench.knowledge import WorkbenchKnowledge
from bioagent.workbench.models import EventKind, TurnStatus
from bioagent.workbench.store import WorkbenchStore
from bioagent.workbench.tool_loop import ToolLoop
from bioagent.workbench.turns import ChatFactory, ConfiguredChatFactory, TurnService
from bioagent.workflow.graph import build_graph

ReadinessCheck = Callable[[], bool]
CancellationCheck = Callable[[], bool]


class _UnavailableDependency:
    def __init__(self, message: str) -> None:
        self._message = message

    def plan(self, **_: object) -> object:
        raise RuntimeError(self._message)

    def execute(self, *_: object, **__: object) -> object:
        raise RuntimeError(self._message)


class ExecutionAdapter:
    """Bind a job's cooperative cancellation callback to controller execution."""

    def __init__(self, executor: object) -> None:
        self._executor = executor
        self._context = local()

    @contextmanager
    def cancellation_scope(self, cancelled: CancellationCheck) -> Iterator[None]:
        previous = getattr(self._context, "cancelled", None)
        self._context.cancelled = cancelled
        try:
            yield
        finally:
            self._context.cancelled = previous

    def execute(self, state: Mapping[str, object]) -> object:
        method = getattr(self._executor, "execute", None)
        if method is None:
            if not callable(self._executor):
                raise TypeError("executor must be callable")
            method = self._executor
        cancelled = getattr(self._context, "cancelled", None)
        if isinstance(self._executor, ExecutionController):
            return self._executor.execute(state, cancelled=cancelled)
        return method(state)


@dataclass
class DependencyContainer:
    settings: Settings
    dataset_repository: DatasetRepository
    dataset_import_service: DatasetImportService
    run_repository: RunRepository
    artifact_manager: ArtifactManager
    graph: Any
    planning_graph: Callable[[object], Any]
    job_runner: LocalJobRunner
    execution_adapter: ExecutionAdapter
    readiness: ReadinessCheck
    max_upload_bytes: int
    max_rows: int
    max_columns: int
    parse_timeout_seconds: float
    model_profiles: ModelProfileStore
    extension_store: SkillStore
    mcp_client: McpClientAdapter
    secret_store: SecretStore
    gateway: ToolGateway
    model_adapter: ModelAdapter
    workbench: WorkbenchStore
    turn_service: TurnService
    geo_repository: GeoRepository
    geo_search_repository: GeoSearchRepository
    geo_service: GeoImportService
    geo_search_service: GeoSearchService
    knowledge_retriever: KnowledgeRetriever
    knowledge_service: KnowledgeService
    retrieval_engine: RetrievalEngine
    answer_service: AnswerService
    wiki_service: WikiService
    analysis_service: AnalysisService = field(init=False)
    jobs_by_run: dict[str, str] = field(default_factory=dict)
    jobs_lock: RLock = field(default_factory=RLock)
    run_locks: dict[str, RLock] = field(default_factory=dict)

    def run_lock(self, run_id: str) -> RLock:
        with self.jobs_lock:
            return self.run_locks.setdefault(run_id, RLock())

    def geo_api_owner(self) -> tuple[str, str]:
        """Create an explicit durable event owner for a direct GEO API request."""
        project = self.workbench.create_project("GEO API imports")
        conversation = self.workbench.create_conversation(project.id, "GEO import")
        turn = self.workbench.begin_turn(
            conversation.id, uuid4(), "GEO import requested through the API", None
        )
        self.workbench.update_turn(turn.id, TurnStatus.RUNNING)
        self.workbench.complete_output(turn.id)
        return str(conversation.id), str(turn.id)

    def shutdown(self) -> None:
        self.retrieval_engine.close()
        self.knowledge_service.close()
        self.geo_search_service.close()
        self.geo_service.close()
        self.job_runner.close()
        with self.jobs_lock:
            jobs = tuple(self.jobs_by_run.items())
        for run_id, job_id in jobs:
            try:
                job_status = self.job_runner.status(job_id)
                state = self.run_repository.read(run_id)
            except (FileNotFoundError, KeyError, TypeError, ValueError):
                continue
            if job_status is JobStatus.CANCELLED and state.get("status") in {
                RunStatus.QUEUED.value,
                RunStatus.RUNNING.value,
            }:
                state["status"] = RunStatus.CANCELLED.value
                state["error"] = {"code": "API_SHUTDOWN"}
                self.run_repository.write(run_id, state)


def get_dependencies(request: Request) -> DependencyContainer:
    dependencies = getattr(request.app.state, "dependencies", None)
    if not isinstance(dependencies, DependencyContainer):
        raise RuntimeError("application dependencies are not initialized")
    return dependencies


def build_dependencies(
    settings: Settings,
    *,
    overrides: Mapping[str, object] | None,
    stack: ExitStack,
) -> DependencyContainer:
    supplied = dict(overrides or {})
    secrets = cast(SecretStore, supplied.get("secret_store") or SystemSecretStore())
    model_profiles = stack.enter_context(
        ModelProfileStore(settings.workbench_db, settings, secrets)
    )
    extension_store = stack.enter_context(SkillStore(settings.workbench_db))
    mcp_client = cast(
        McpClientAdapter,
        supplied.get("mcp_client")
        or McpClientAdapter(secret_resolver=_mcp_secret_resolver(secrets)),
    )
    model_adapter = cast(
        ModelAdapter, supplied.get("model_adapter") or ModelAdapter(model_profiles)
    )
    workbench = stack.enter_context(WorkbenchStore(settings.workbench_db))
    gateway = ToolGateway(extension_store, mcp_client, workbench)
    factory = cast(
        ChatFactory,
        supplied.get("chat_model_factory")
        or ConfiguredChatFactory(model_profiles, gateway=gateway, extension_store=extension_store),
    )
    turn_service = TurnService(
        workbench,
        factory,
        tool_loop=ToolLoop(gateway, extension_store),
        gateway=gateway,
    )
    project_root = Path(__file__).resolve().parents[3]
    errors: list[str] = []

    dataset_repository = cast(
        DatasetRepository,
        supplied.get("dataset_repository") or DatasetRepository(settings.data_dir),
    )
    run_repository = cast(
        RunRepository,
        supplied.get("run_repository") or RunRepository(settings.runs_dir),
    )
    artifact_manager = cast(
        ArtifactManager,
        supplied.get("artifact_manager") or ArtifactManager(settings.runs_dir),
    )
    search_repository_value = supplied.get("geo_search_repository") or GeoSearchRepository(
        settings.data_dir / "searches"
    )
    if not isinstance(search_repository_value, GeoSearchRepository):
        raise TypeError("geo_search_repository override must be a GeoSearchRepository")
    search_repository = search_repository_value
    geo_repository_value = supplied.get("geo_repository") or GeoRepository(
        settings.data_dir / "sources", search_repository=search_repository
    )
    if not isinstance(geo_repository_value, GeoRepository):
        raise TypeError("geo_repository override must be a GeoRepository")
    geo_repository = geo_repository_value
    geo_repository.bind_search_repository(search_repository)
    _recover_orphaned_api_runs(
        run_repository,
        artifact_manager,
        settings.runs_dir,
        geo_repository,
        search_repository,
    )

    planner = supplied.get("planner")
    if planner is None:
        try:
            planner = AnalysisPlanner(create_chat_model(settings))
        except Exception as error:
            errors.append(f"planner: {type(error).__name__}")
            planner = _UnavailableDependency("planner dependency is unavailable")

    executor = supplied.get("executor")
    if executor is None:
        try:
            executor = _build_controller(
                settings=settings,
                project_root=project_root,
                dataset_repository=dataset_repository,
                artifact_manager=artifact_manager,
                search_repository=search_repository,
            )
        except Exception as error:
            errors.append(f"executor: {type(error).__name__}")
            executor = _UnavailableDependency("execution dependency is unavailable")

    graph = supplied.get("graph")
    planning_graph: Callable[[object], Any]
    if graph is None:
        checkpointer = supplied.get("checkpointer")
        if checkpointer is None:
            checkpointer = stack.enter_context(sqlite_checkpoint(settings.checkpoint_db))
        execution_adapter = ExecutionAdapter(executor)

        def planning_graph(bound_planner: object) -> Any:
            # Each invocation owns its model dependency. Only JSON state is
            # checkpointed; approval resume uses the already-persisted plan.
            return build_graph(
                bound_planner,
                execution_adapter,
                cast(BaseCheckpointSaver[Any], checkpointer),
                reporter=ArtifactReporter(artifact_manager)
                if isinstance(executor, ExecutionController)
                else None,
            )

        graph = planning_graph(planner)
    else:
        execution_adapter = ExecutionAdapter(executor)

        def planning_graph(bound_planner: object) -> Any:
            raise RuntimeError("profile planning requires an assembled workflow graph")

    job_runner = supplied.get("job_runner")
    if job_runner is None:
        job_runner = LocalJobRunner()
    if not isinstance(job_runner, LocalJobRunner):
        raise TypeError("job_runner override must be a LocalJobRunner")

    readiness_value = supplied.get("readiness")
    if callable(readiness_value):
        readiness = cast(ReadinessCheck, readiness_value)
    elif readiness_value is not None:
        raise TypeError("readiness override must be callable")

    max_upload_value = supplied.get("max_upload_bytes", 10 * 1024 * 1024)
    if not isinstance(max_upload_value, int) or isinstance(max_upload_value, bool):
        raise TypeError("max_upload_bytes must be an integer")
    if max_upload_value <= 0:
        raise ValueError("max_upload_bytes must be positive")

    max_rows = _positive_int(supplied.get("max_rows", 100_000), "max_rows")
    max_columns = _positive_int(supplied.get("max_columns", 10_000), "max_columns")
    timeout_value = supplied.get("parse_timeout_seconds", 10.0)
    if not isinstance(timeout_value, (int, float)) or isinstance(timeout_value, bool):
        raise TypeError("parse_timeout_seconds must be a number")
    if timeout_value <= 0:
        raise ValueError("parse_timeout_seconds must be positive")

    dataset_import_service = cast(
        DatasetImportService,
        supplied.get("dataset_import_service")
        or DatasetImportService(
            dataset_repository,
            max_upload_bytes=max_upload_value,
            max_rows=max_rows,
            max_columns=max_columns,
            parse_timeout_seconds=float(timeout_value),
        ),
    )
    geo_service = cast(
        GeoImportService,
        supplied.get("geo_service")
        or GeoImportService(
            geo_repository,
            GeoClient(GeoTransport()),
            GeoDownloader(GeoTransport(), root=settings.data_dir / "sources"),
            dataset_import_service,
            event_sink=_workbench_geo_event_sink(workbench),
            search_repository=search_repository,
        ),
    )

    def create_search_source(
        accession: str,
        conversation_id: str,
        turn_id: str,
        provenance: object,
    ) -> dict[str, object]:
        from bioagent.geo.models import GeoSearchProvenance

        if not isinstance(provenance, GeoSearchProvenance):
            raise ValueError("GEO_SEARCH_PROVENANCE_INVALID")
        source = geo_service.create_source(
            accession,
            conversation_id=conversation_id,
            turn_id=turn_id,
            provenance=provenance,
        )
        source_id = source.get("id")
        if not isinstance(source_id, str):
            return source
        try:
            workbench.set_geo_source(conversation_id, UUID(source_id))
        except (TypeError, ValueError) as error:
            raise ValueError("GEO_SEARCH_SOURCE_FAILED") from error
        return source

    geo_search_service = cast(
        GeoSearchService,
        supplied.get("geo_search_service")
        or GeoSearchService(
            settings.data_dir,
            NcbiGeoCatalogProvider(GeoTransport(max_redirects=0)),
            create_search_source,
            event_sink=_workbench_geo_event_sink(workbench),
            repository=search_repository,
        ),
    )
    knowledge_retriever = cast(
        KnowledgeRetriever,
        supplied.get("knowledge_retriever") or NullKnowledgeRetriever(),
    )

    def default_readiness() -> bool:
        return (
            not errors
            and settings.data_dir.resolve().is_dir()
            and settings.runs_dir.resolve().is_dir()
            and settings.checkpoint_db.resolve().parent.is_dir()
            and shutil.which(settings.rscript) is not None
        )

    if readiness_value is None:
        readiness = default_readiness

    knowledge_store = KnowledgeStore(settings.knowledge_dir or settings.data_dir / "knowledge")
    retrieval_engine = RetrievalEngine(knowledge_store, settings.knowledge_embedding_models_dir)
    wiki_service = WikiService(retrieval_engine, model_profiles, model_adapter)
    answer_service = AnswerService(
        retrieval_engine, model_profiles, model_adapter, wiki=wiki_service
    )
    container = DependencyContainer(
        settings=settings,
        dataset_repository=dataset_repository,
        dataset_import_service=dataset_import_service,
        run_repository=run_repository,
        artifact_manager=artifact_manager,
        graph=graph,
        planning_graph=planning_graph,
        job_runner=job_runner,
        execution_adapter=execution_adapter,
        readiness=readiness,
        max_upload_bytes=max_upload_value,
        max_rows=max_rows,
        max_columns=max_columns,
        parse_timeout_seconds=float(timeout_value),
        model_profiles=model_profiles,
        extension_store=extension_store,
        mcp_client=mcp_client,
        secret_store=secrets,
        gateway=gateway,
        model_adapter=model_adapter,
        workbench=workbench,
        turn_service=turn_service,
        geo_repository=geo_repository,
        geo_search_repository=search_repository,
        geo_service=geo_service,
        geo_search_service=geo_search_service,
        knowledge_retriever=knowledge_retriever,
        knowledge_service=KnowledgeService(
            knowledge_store,
            settings.knowledge_models_dir,
            timeout_seconds=settings.knowledge_parse_timeout_seconds,
            memory_bytes=settings.knowledge_memory_bytes,
        ),
        retrieval_engine=retrieval_engine,
        answer_service=answer_service,
        wiki_service=wiki_service,
    )
    analysis_service = AnalysisService(container)
    container.analysis_service = analysis_service
    turn_service.bind_analysis(analysis_service)
    turn_service.bind_knowledge(WorkbenchKnowledge(workbench, answer_service))
    turn_service.bind_geo(geo_service)
    turn_service.bind_geo_search(geo_search_service)
    geo_service.bind_event_sink(_workbench_geo_event_sink(workbench))
    geo_search_service.bind_event_sink(_workbench_geo_event_sink(workbench))
    geo_service.bind_ready_sink(turn_service.resume_geo_ready)
    stack.callback(container.shutdown)
    container.retrieval_engine.start()
    container.knowledge_service.start()
    return container


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{label} must be an integer")
    if value <= 0:
        raise ValueError(f"{label} must be positive")
    return value


def _mcp_secret_resolver(secrets: SecretStore) -> Callable[[str], str | None]:
    def resolve(reference: str) -> str | None:
        try:
            value = secrets.get(_mcp_secret_reference(reference))
        except Exception:
            return None
        return None if value is None else value.get_secret_value()

    return resolve


def _mcp_secret_reference(reference: str) -> str:
    """Keep MCP credentials in a separate keyring namespace from model keys."""
    return reference if reference.startswith("mcp:") else f"mcp:{reference}"


def _workbench_geo_event_sink(workbench: WorkbenchStore) -> Callable[[dict[str, object]], None]:
    """Project persisted GEO state onto the existing per-conversation event log."""

    def publish(event: dict[str, object]) -> None:
        conversation_id = event.pop("conversation_id", None)
        turn_id = event.pop("turn_id", None)
        kind = event.pop("kind", None)
        if not isinstance(conversation_id, str) or not isinstance(turn_id, str):
            return
        if kind != "geo.updated":
            return
        if "result_count" in event:
            event_kind: EventKind = "geo.search.updated"
            if event.get("status") == "SELECTED":
                event_kind = "geo.search.selected"
            workbench.append_event(conversation_id, turn_id, event_kind, event)
            return
        workbench.append_event(conversation_id, turn_id, "geo.updated", event)

    return publish


def _recover_orphaned_api_runs(
    repository: RunRepository,
    artifact_manager: ArtifactManager,
    runs_dir: Path,
    geo_repository: GeoRepository,
    search_repository: GeoSearchRepository,
) -> None:
    root = runs_dir.resolve()
    if not root.is_dir():
        return
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        try:
            state = repository.read(directory.name)
        except (FileNotFoundError, OSError, TypeError, ValueError):
            continue
        if state.get("status") not in {RunStatus.QUEUED.value, RunStatus.RUNNING.value}:
            continue
        if _recover_completed_run(
            directory.name,
            state,
            repository,
            artifact_manager,
            geo_repository,
            search_repository,
        ):
            continue
        state["status"] = RunStatus.FAILED.value
        state["error"] = {"code": "API_PROCESS_RESTARTED"}
        repository.write(directory.name, state)


def _recover_completed_run(
    run_id: str,
    state: dict[str, Any],
    repository: RunRepository,
    artifact_manager: ArtifactManager,
    geo_repository: GeoRepository,
    search_repository: GeoSearchRepository,
) -> bool:
    try:
        manifest_path = artifact_manager.resolve(run_id, "manifest.json")
        manifest = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        if str(manifest.run_id) != run_id or manifest.status is not RunStatus.COMPLETED:
            return False
        plan = AnalysisPlan.model_validate(state.get("plan"))
        if (
            str(manifest.dataset_id) != state.get("dataset_id")
            or plan.dataset_id != str(manifest.dataset_id)
            or manifest.plan_revision != state.get("plan_revision")
            or manifest.plan_hash != calculate_plan_hash(plan)
        ):
            return False
        if not _recovery_source_backing_is_verified(
            manifest,
            run_id,
            artifact_manager,
            geo_repository,
            search_repository,
        ):
            return False
        # The controller commits statistical completion before report publication.
        # Only a reporter-registered HTML artifact proves the full workflow finished.
        if not any(item.relative_path == "report/report.html" for item in manifest.artifacts):
            return False
        for artifact in manifest.artifacts:
            path = artifact_manager.resolve(run_id, artifact.relative_path)
            if not path.is_file() or _sha256_file(path) != artifact.sha256:
                return False
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return False
    state["status"] = RunStatus.COMPLETED.value
    state["attempt_id"] = str(manifest.attempt_id)
    state["qc"] = manifest.qc.model_dump(mode="json")
    state["report"] = {"status": "completed", "relative_path": "report/report.html"}
    state.pop("error", None)
    repository.write(run_id, state)
    return True


def _recovery_source_backing_is_verified(
    manifest: RunManifest,
    run_id: str,
    artifact_manager: ArtifactManager,
    geo_repository: GeoRepository,
    search_repository: GeoSearchRepository,
) -> bool:
    """Verify copied source evidence against durable GEO state before recovery."""

    if manifest.source_id is None:
        return manifest.search_provenance is None and not manifest.source_artifacts
    try:
        source = geo_repository.read(manifest.source_id)
        source_artifacts = {
            record.relative_path: record.sha256 for record in manifest.source_artifacts
        }
        expected_paths = {
            "source/raw/source.bin": source.raw_sha256,
            "source/source.json": _sha256_file(source.source_json),
            "source/normalized/counts.csv": source.counts_sha256,
            "source/normalized/metadata.csv": source.metadata_sha256,
        }
        if len(source_artifacts) != len(expected_paths) or source_artifacts != expected_paths:
            return False
        for relative_path, expected_hash in expected_paths.items():
            copied_path = artifact_manager.resolve(run_id, relative_path)
            if not copied_path.is_file() or _sha256_file(copied_path) != expected_hash:
                return False
        if manifest.search_provenance is None:
            return source.search_provenance is None
        if source.search_provenance != manifest.search_provenance:
            return False
        search_repository.verify_provenance(
            manifest.search_provenance,
            expected_status=GeoSearchStatus.SELECTED,
            expected_source_id=manifest.source_id,
        )
        return True
    except (FileNotFoundError, GeoRepositoryError, GeoSearchRepositoryError, OSError, ValueError):
        return False


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_controller(
    *,
    settings: Settings,
    project_root: Path,
    dataset_repository: DatasetRepository,
    artifact_manager: ArtifactManager,
    search_repository: GeoSearchRepository,
) -> ExecutionController:
    return ExecutionController(
        project_root=project_root,
        r_runner=RRunner(project_root=project_root, rscript=settings.rscript),
        dataset_repository=dataset_repository,
        artifact_manager=artifact_manager,
        tool_registry=ToolRegistry(project_root),
        git_commit=_git_commit(project_root),
        software_versions=_software_versions(project_root),
        search_repository=search_repository,
    )


def _git_commit(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        capture_output=True,
        check=False,
        text=True,
        timeout=5,
    )
    commit = result.stdout.strip()
    if result.returncode != 0 or not commit:
        raise RuntimeError("git commit is unavailable")
    return commit


def _software_versions(project_root: Path) -> dict[str, str]:
    payload: object = json.loads((project_root / "renv.lock").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("renv.lock must contain an object")
    r_payload = payload.get("R")
    packages = payload.get("Packages")
    if not isinstance(r_payload, dict) or not isinstance(packages, dict):
        raise ValueError("renv.lock is missing version metadata")
    deseq2 = packages.get("DESeq2")
    if not isinstance(deseq2, dict):
        raise ValueError("renv.lock is missing DESeq2")
    r_version = r_payload.get("Version")
    deseq2_version = deseq2.get("Version")
    if not isinstance(r_version, str) or not isinstance(deseq2_version, str):
        raise ValueError("renv.lock has invalid version metadata")
    return {"r": r_version, "deseq2": deseq2_version}
