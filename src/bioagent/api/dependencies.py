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
from bioagent.llm.factory import create_chat_model
from bioagent.llm.planner import AnalysisPlanner
from bioagent.models.adapters import ModelAdapter
from bioagent.models.secrets import SecretStore, SystemSecretStore
from bioagent.models.store import ModelProfileStore
from bioagent.reporting.workflow import ArtifactReporter
from bioagent.services.analysis import AnalysisService
from bioagent.storage.checkpoint import sqlite_checkpoint
from bioagent.storage.runs import RunRepository
from bioagent.tools.registry import ToolRegistry
from bioagent.workbench.store import WorkbenchStore
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
    run_repository: RunRepository
    artifact_manager: ArtifactManager
    graph: Any
    job_runner: LocalJobRunner
    execution_adapter: ExecutionAdapter
    readiness: ReadinessCheck
    max_upload_bytes: int
    max_rows: int
    max_columns: int
    parse_timeout_seconds: float
    model_profiles: ModelProfileStore
    model_adapter: ModelAdapter
    workbench: WorkbenchStore
    turn_service: TurnService
    analysis_service: AnalysisService = field(init=False)
    jobs_by_run: dict[str, str] = field(default_factory=dict)
    jobs_lock: RLock = field(default_factory=RLock)
    run_locks: dict[str, RLock] = field(default_factory=dict)

    def run_lock(self, run_id: str) -> RLock:
        with self.jobs_lock:
            return self.run_locks.setdefault(run_id, RLock())

    def shutdown(self) -> None:
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
    model_adapter = ModelAdapter(model_profiles)
    workbench = stack.enter_context(WorkbenchStore(settings.workbench_db))
    factory = cast(
        ChatFactory, supplied.get("chat_model_factory") or ConfiguredChatFactory(model_profiles)
    )
    turn_service = TurnService(workbench, factory)
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
    _recover_orphaned_api_runs(run_repository, artifact_manager, settings.runs_dir)

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
            )
        except Exception as error:
            errors.append(f"executor: {type(error).__name__}")
            executor = _UnavailableDependency("execution dependency is unavailable")

    graph = supplied.get("graph")
    if graph is None:
        checkpointer = supplied.get("checkpointer")
        if checkpointer is None:
            checkpointer = stack.enter_context(sqlite_checkpoint(settings.checkpoint_db))
        execution_adapter = ExecutionAdapter(executor)
        graph = build_graph(
            planner,
            execution_adapter,
            cast(BaseCheckpointSaver[Any], checkpointer),
            reporter=ArtifactReporter(artifact_manager)
            if isinstance(executor, ExecutionController)
            else None,
        )
    else:
        execution_adapter = ExecutionAdapter(executor)

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

    container = DependencyContainer(
        settings=settings,
        dataset_repository=dataset_repository,
        run_repository=run_repository,
        artifact_manager=artifact_manager,
        graph=graph,
        job_runner=job_runner,
        execution_adapter=execution_adapter,
        readiness=readiness,
        max_upload_bytes=max_upload_value,
        max_rows=max_rows,
        max_columns=max_columns,
        parse_timeout_seconds=float(timeout_value),
        model_profiles=model_profiles,
        model_adapter=model_adapter,
        workbench=workbench,
        turn_service=turn_service,
    )
    analysis_service = AnalysisService(container)
    container.analysis_service = analysis_service
    turn_service.bind_analysis(analysis_service)
    stack.callback(container.shutdown)
    return container


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{label} must be an integer")
    if value <= 0:
        raise ValueError(f"{label} must be positive")
    return value


def _recover_orphaned_api_runs(
    repository: RunRepository,
    artifact_manager: ArtifactManager,
    runs_dir: Path,
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
        if _recover_completed_run(directory.name, state, repository, artifact_manager):
            continue
        state["status"] = RunStatus.FAILED.value
        state["error"] = {"code": "API_PROCESS_RESTARTED"}
        repository.write(directory.name, state)


def _recover_completed_run(
    run_id: str,
    state: dict[str, Any],
    repository: RunRepository,
    artifact_manager: ArtifactManager,
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
) -> ExecutionController:
    return ExecutionController(
        project_root=project_root,
        r_runner=RRunner(project_root=project_root, rscript=settings.rscript),
        dataset_repository=dataset_repository,
        artifact_manager=artifact_manager,
        tool_registry=ToolRegistry(project_root),
        git_commit=_git_commit(project_root),
        software_versions=_software_versions(project_root),
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
