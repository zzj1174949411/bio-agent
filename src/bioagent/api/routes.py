from __future__ import annotations

import csv
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from hashlib import sha256
from io import StringIO
from multiprocessing import get_context
from multiprocessing.connection import Connection
from pathlib import Path
from time import monotonic
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from bioagent.api.dependencies import DependencyContainer, get_dependencies
from bioagent.artifacts.manifest import RunManifest
from bioagent.datasets.parser import ParsedDataset, load_dataset
from bioagent.datasets.validator import DatasetValidation, validate_dataset
from bioagent.domain.plans import Comparison
from bioagent.domain.qc import QCReport, QCStatus
from bioagent.domain.runs import RunStatus
from bioagent.execution.r_runner import RExecutionCancelledError
from bioagent.llm.planner import PlanningDatasetSummary
from bioagent.services.datasets import DatasetImportError
from bioagent.workflow.state import (
    WorkflowState,
    validate_approval_decision,
    validate_run_id,
    validate_workflow_state,
)

router = APIRouter()
Dependencies = Annotated[DependencyContainer, Depends(get_dependencies)]
_ALLOWED_SUFFIXES = {".csv", ".tsv"}
_ALLOWED_CONTENT_TYPES = {
    "application/octet-stream",
    "application/vnd.ms-excel",
    "text/csv",
    "text/plain",
    "text/tab-separated-values",
}
_WORKFLOW_STATE_KEYS = frozenset(WorkflowState.__annotations__)
_FACTOR_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    dataset_id: str = Field(min_length=36, max_length=36)
    goal: str = Field(min_length=1, max_length=4000)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["approve", "reject", "cancel", "revise", "modify"]
    plan_revision: int | None = Field(default=None, ge=1)
    plan: dict[str, JsonValue] | None = None


class RunListItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    run_id: str
    dataset_id: str
    status: RunStatus
    qc_status: QCStatus | None = None
    plan_revision: int | None = None
    attempt_id: str | None = None
    index_updated_at: datetime
    completed_at: datetime | None = None
    evidence_status: Literal["VERIFIED", "INDEX_ONLY", "INVALID"]


class RunListIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    run_id: str
    code: Literal["RUN_INDEX_INVALID", "RUN_MANIFEST_INVALID"]


class RunListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    runs: tuple[RunListItem, ...]
    issues: tuple[RunListIssue, ...]


def _error(code: str, status_code: int, **details: object) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, **details})


async def _read_upload(upload: UploadFile, dependencies: DependencyContainer) -> bytes:
    filename = upload.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise _error("UNSUPPORTED_FILE_TYPE", status.HTTP_422_UNPROCESSABLE_CONTENT)
    if upload.content_type not in _ALLOWED_CONTENT_TYPES:
        raise _error("UNSUPPORTED_MEDIA_TYPE", status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
    content = await upload.read(dependencies.max_upload_bytes + 1)
    if len(content) > dependencies.max_upload_bytes:
        raise _error("UPLOAD_TOO_LARGE", status.HTTP_413_CONTENT_TOO_LARGE)
    if not content:
        raise _error("EMPTY_UPLOAD", status.HTTP_422_UNPROCESSABLE_CONTENT)
    _preflight_table(content, suffix, dependencies)
    return content


def _preflight_table(
    content: bytes,
    suffix: str,
    dependencies: DependencyContainer,
) -> None:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise _error("INVALID_DATASET_ENCODING", status.HTTP_422_UNPROCESSABLE_CONTENT) from error
    separator = "," if suffix == ".csv" else "\t"
    reader = csv.reader(StringIO(text), delimiter=separator)
    started = monotonic()
    try:
        header = next(reader)
    except StopIteration:
        return
    if len(header) > dependencies.max_columns:
        raise _error("DATASET_LIMIT_EXCEEDED", status.HTTP_413_CONTENT_TOO_LARGE)
    for row_count, row in enumerate(reader, start=1):
        if row_count > dependencies.max_rows or len(row) > dependencies.max_columns:
            raise _error("DATASET_LIMIT_EXCEEDED", status.HTTP_413_CONTENT_TOO_LARGE)
        if monotonic() - started > dependencies.parse_timeout_seconds:
            raise _error("DATASET_PARSE_TIMEOUT", status.HTTP_408_REQUEST_TIMEOUT)


def _upload_suffix(upload: UploadFile) -> str:
    return Path(upload.filename or "").suffix.lower()


def _comparison_for(dataset: ParsedDataset) -> Comparison:
    if len(dataset.metadata.columns) == 0:
        raise _error(
            "MISSING_FACTOR",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    for position, column in enumerate(dataset.metadata.columns):
        factor = str(column)
        if not _FACTOR_PATTERN.fullmatch(factor):
            continue
        values = dataset.metadata.iloc[:, position].dropna().astype(str).unique().tolist()
        if len(values) == 2:
            return Comparison(
                factor=factor,
                numerator=values[0],
                denominator=values[1],
            )
    raise _error(
        "BINARY_FACTOR_NOT_FOUND",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


def _validation_worker(
    connection: Connection,
    counts_path: str,
    metadata_path: str,
) -> None:
    """Parse and validate outside the API process so timeout can terminate work."""
    try:
        dataset = load_dataset(Path(counts_path), Path(metadata_path))
        validation = validate_dataset(dataset, _comparison_for(dataset))
        connection.send(("ok", validation))
    except HTTPException as error:
        connection.send(("http_error", error.status_code, error.detail))
    except (OSError, TypeError, ValueError):
        connection.send(("invalid_dataset",))
    finally:
        connection.close()


def _validate_paths(
    counts_path: Path,
    metadata_path: Path,
    dependencies: DependencyContainer,
) -> DatasetValidation:
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_validation_worker,
        args=(sender, str(counts_path), str(metadata_path)),
    )
    process.start()
    sender.close()
    try:
        if not receiver.poll(dependencies.parse_timeout_seconds):
            raise _error("DATASET_PARSE_TIMEOUT", status.HTTP_408_REQUEST_TIMEOUT)
        try:
            result = receiver.recv()
        except EOFError as error:
            raise _error(
                "INVALID_DATASET",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            ) from error
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        process.join()
        process.close()

    if not isinstance(result, tuple) or not result:
        raise _error(
            "INVALID_DATASET",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    if result[0] == "http_error" and len(result) == 3:
        raise HTTPException(status_code=result[1], detail=result[2])
    if result[0] != "ok" or len(result) != 2:
        raise _error("INVALID_DATASET", status.HTTP_422_UNPROCESSABLE_CONTENT)
    validation = result[1]
    if not isinstance(validation, DatasetValidation):
        raise _error("INVALID_DATASET", status.HTTP_422_UNPROCESSABLE_CONTENT)
    if not validation.is_valid:
        failures = [issue for issue in validation.qc.issues if issue.status.value == "FAIL"]
        code = failures[0].code if failures else "DATASET_VALIDATION_FAILED"
        raise _error(
            code,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            issues=[issue.model_dump(mode="json") for issue in validation.qc.issues],
        )
    return validation


def _summary(dataset_id: str, validation: DatasetValidation) -> PlanningDatasetSummary:
    categorical_levels: dict[str, tuple[str, ...]] = {}
    for column in validation.metadata.columns:
        name = str(column)
        levels = tuple(validation.metadata[column].dropna().astype(str).unique().tolist())
        if len(levels) == 2:
            categorical_levels[name] = levels
    return PlanningDatasetSummary(
        dataset_id=dataset_id,
        feature_count=len(validation.counts.index),
        sample_count=len(validation.counts.columns),
        categorical_levels=categorical_levels,
    )


def _stored_validation(
    dataset_id: str,
    dependencies: DependencyContainer,
) -> tuple[DatasetValidation, PlanningDatasetSummary]:
    try:
        counts_path, metadata_path = dependencies.dataset_repository.paths(dataset_id)
        validation = _validate_paths(counts_path, metadata_path, dependencies)
        summary = _summary(dataset_id, validation)
    except HTTPException:
        raise
    except (FileNotFoundError, TypeError, ValueError) as error:
        raise _error("DATASET_NOT_FOUND", status.HTTP_404_NOT_FOUND) from error
    return validation, summary


@router.post("/api/v1/datasets", status_code=status.HTTP_201_CREATED)
async def create_dataset(
    counts: UploadFile,
    metadata: UploadFile,
    dependencies: Dependencies,
) -> dict[str, object]:
    counts_content = await _read_upload(counts, dependencies)
    metadata_content = await _read_upload(metadata, dependencies)
    try:
        dataset_id = dependencies.dataset_import_service.import_uploaded(
            counts_content,
            metadata_content,
            _upload_suffix(counts),
            _upload_suffix(metadata),
        )
    except DatasetImportError as error:
        raise _error(error.code, error.status_code, **error.details) from error
    return {"dataset_id": dataset_id}


@router.get("/api/v1/datasets/{dataset_id}/validation")
def get_dataset_validation(
    dataset_id: str,
    dependencies: Dependencies,
) -> dict[str, object]:
    validation, summary = _stored_validation(dataset_id, dependencies)
    return {
        "dataset_id": dataset_id,
        "is_valid": validation.is_valid,
        "zero_feature_count": validation.zero_feature_count,
        "qc": validation.qc.model_dump(mode="json"),
        "summary": summary.model_dump(mode="json"),
    }


def _read_run(run_id: str, dependencies: DependencyContainer) -> dict[str, JsonValue]:
    try:
        return dependencies.run_repository.read(run_id)
    except (FileNotFoundError, TypeError, ValueError) as error:
        raise _error("RUN_NOT_FOUND", status.HTTP_404_NOT_FOUND) from error


def _workflow_state(value: object) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError("workflow must return a mapping")
    state = {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and key in _WORKFLOW_STATE_KEYS
    }
    validate_workflow_state(cast(WorkflowState, state))
    return cast(dict[str, JsonValue], state)


@router.post("/api/v1/runs", status_code=status.HTTP_201_CREATED)
def create_run(request: RunCreate, dependencies: Dependencies) -> dict[str, JsonValue]:
    run_id = dependencies.analysis_service.create_run(
        dataset_id=request.dataset_id,
        goal=request.goal,
    )
    return _read_run(run_id, dependencies)


def _optional_positive_int(state: Mapping[str, object], key: str) -> int | None:
    value = state.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"invalid {key}")
    return value


def _run_list_item(
    run_id: str,
    state: Mapping[str, object],
    updated_at: datetime,
) -> tuple[RunListItem, QCReport | None]:
    dataset_id = validate_run_id(state.get("dataset_id"))
    status_value = RunStatus(str(state.get("status")))
    plan_revision = _optional_positive_int(state, "plan_revision")
    attempt_value = state.get("attempt_id")
    attempt_id = None if attempt_value is None else validate_run_id(attempt_value)
    qc_value = state.get("qc")
    qc = None if qc_value is None else QCReport.model_validate(qc_value)
    return (
        RunListItem(
            run_id=run_id,
            dataset_id=dataset_id,
            status=status_value,
            qc_status=None if qc is None else qc.status,
            plan_revision=plan_revision,
            attempt_id=attempt_id,
            index_updated_at=updated_at,
            evidence_status="INDEX_ONLY",
        ),
        qc,
    )


def _verified_completed_manifest(
    item: RunListItem,
    qc: QCReport | None,
    dependencies: DependencyContainer,
) -> RunManifest | None:
    try:
        path = dependencies.artifact_manager.resolve(item.run_id, "manifest.json")
        manifest = RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
        if (
            str(manifest.run_id) != item.run_id
            or str(manifest.dataset_id) != item.dataset_id
            or str(manifest.attempt_id) != item.attempt_id
            or manifest.plan_revision != item.plan_revision
            or manifest.status != item.status
            or manifest.qc != qc
        ):
            raise ValueError("manifest does not match run index")
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return None
    return manifest


@router.get("/api/v1/runs", response_model=RunListResponse)
def list_runs(
    dependencies: Dependencies,
    run_status: Annotated[RunStatus | None, Query(alias="status")] = None,
) -> RunListResponse:
    entries, index_issues = dependencies.run_repository.list_entries()
    runs: list[RunListItem] = []
    issues = [RunListIssue(run_id=issue.run_id, code=issue.code) for issue in index_issues]
    for entry in entries:
        try:
            item, qc = _run_list_item(entry.run_id, entry.state, entry.updated_at)
        except (TypeError, ValueError, ValidationError):
            issues.append(RunListIssue(run_id=entry.run_id, code="RUN_INDEX_INVALID"))
            continue
        if item.status == RunStatus.COMPLETED:
            manifest = _verified_completed_manifest(item, qc, dependencies)
            if manifest is None:
                item = item.model_copy(update={"evidence_status": "INVALID"})
                issues.append(
                    RunListIssue(
                        run_id=entry.run_id,
                        code="RUN_MANIFEST_INVALID",
                    )
                )
            else:
                item = item.model_copy(
                    update={
                        "completed_at": manifest.ended_at,
                        "evidence_status": "VERIFIED",
                    }
                )
        if run_status is not None and item.status != run_status:
            continue
        runs.append(item)
    return RunListResponse(runs=tuple(runs), issues=tuple(issues))


@router.get("/api/v1/runs/{run_id}")
def get_run(run_id: str, dependencies: Dependencies) -> dict[str, JsonValue]:
    return _read_run(run_id, dependencies)


@router.get("/api/v1/runs/{run_id}/plan")
def get_run_plan(run_id: str, dependencies: Dependencies) -> dict[str, object]:
    state = _read_run(run_id, dependencies)
    plan = state.get("plan")
    revision = state.get("plan_revision")
    if not isinstance(plan, dict) or not isinstance(revision, int):
        raise _error("PLAN_NOT_AVAILABLE", status.HTTP_409_CONFLICT)
    return {"run_id": run_id, "plan_revision": revision, "plan": plan}


def _resume(
    run_id: str,
    decision: Mapping[str, JsonValue],
    dependencies: DependencyContainer,
) -> dict[str, JsonValue]:
    result = dependencies.graph.invoke(
        Command(resume=dict(decision)),
        {"configurable": {"thread_id": run_id}},
    )
    state = _workflow_state(result)
    with dependencies.run_lock(run_id):
        dependencies.run_repository.write(run_id, state)
    return state


def _approve_run(
    run_id: str,
    request: ApprovalRequest,
    response: Response,
    dependencies: Dependencies,
) -> Mapping[str, object]:
    run_lock = dependencies.run_lock(run_id)
    with run_lock:
        current = _read_run(run_id, dependencies)
        if current.get("status") != RunStatus.AWAITING_APPROVAL.value:
            raise _error("RUN_NOT_AWAITING_APPROVAL", status.HTTP_409_CONFLICT)
        try:
            decision = validate_approval_decision(request.model_dump(mode="python"))
        except ValidationError as error:
            raise _error(
                "APPROVAL_INVALID",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            ) from error

        if request.action != "approve":
            return _resume(run_id, decision, dependencies)
        if request.plan_revision != current.get("plan_revision"):
            raise _error("PLAN_REVISION_MISMATCH", status.HTTP_409_CONFLICT)

        queued = dict(current)
        queued["status"] = RunStatus.QUEUED.value
        dependencies.run_repository.write(run_id, queued)

        def task(cancelled: Callable[[], bool]) -> object:
            try:
                with run_lock:
                    if cancelled():
                        _resume(
                            run_id,
                            cast(dict[str, JsonValue], {"action": "cancel"}),
                            dependencies,
                        )
                        raise RExecutionCancelledError()
                    running = dict(queued)
                    running["status"] = RunStatus.RUNNING.value
                    dependencies.run_repository.write(run_id, running)
                with dependencies.execution_adapter.cancellation_scope(cancelled):
                    state = _resume(run_id, decision, dependencies)
                if state.get("status") == RunStatus.COMPLETED.value:
                    dependencies.workbench.finish_run_turn(run_id, success=True)
                elif state.get("status") in {RunStatus.FAILED.value, RunStatus.CANCELLED.value}:
                    error_value = state.get("error")
                    error_code = "ANALYSIS_FAILED"
                    if isinstance(error_value, dict) and isinstance(error_value.get("code"), str):
                        error_code = cast(str, error_value["code"])
                    dependencies.workbench.finish_run_turn(
                        run_id, success=False, error_code=error_code
                    )
            except Exception:
                with run_lock:
                    latest = _read_run(run_id, dependencies)
                    if latest.get("status") in {
                        RunStatus.QUEUED.value,
                        RunStatus.RUNNING.value,
                    }:
                        latest["status"] = RunStatus.FAILED.value
                        latest["error"] = {"code": "API_JOB_FAILED"}
                        dependencies.run_repository.write(run_id, latest)
                raise
            if state.get("status") == RunStatus.CANCELLED.value:
                raise RExecutionCancelledError()
            if state.get("status") == RunStatus.FAILED.value:
                raise RuntimeError("background run failed")
            return state

        execution_key = f"{run_id}:{request.plan_revision}"
        try:
            job_id = dependencies.job_runner.submit(execution_key, task)
        except Exception:
            dependencies.run_repository.write(run_id, current)
            raise
        with dependencies.jobs_lock:
            dependencies.jobs_by_run[run_id] = job_id
    response.status_code = status.HTTP_202_ACCEPTED
    return {"run_id": run_id, "job_id": job_id, "status": RunStatus.QUEUED.value}


def _cancel_run(
    run_id: str,
    response: Response,
    dependencies: Dependencies,
) -> Mapping[str, object]:
    with dependencies.run_lock(run_id):
        current = _read_run(run_id, dependencies)
        current_status = str(current.get("status"))
        if current_status == RunStatus.AWAITING_APPROVAL.value:
            return _resume(
                run_id,
                cast(dict[str, JsonValue], {"action": "cancel"}),
                dependencies,
            )
        if current_status not in {RunStatus.QUEUED.value, RunStatus.RUNNING.value}:
            raise _error("RUN_NOT_CANCELLABLE", status.HTTP_409_CONFLICT)
        with dependencies.jobs_lock:
            job_id = dependencies.jobs_by_run.get(run_id)
        if job_id is None:
            raise _error("JOB_NOT_FOUND", status.HTTP_409_CONFLICT)
        cancelled = dependencies.job_runner.cancel(job_id)
        if cancelled:
            return _resume(
                run_id,
                cast(dict[str, JsonValue], {"action": "cancel"}),
                dependencies,
            )
    response.status_code = status.HTTP_202_ACCEPTED
    return {"run_id": run_id, "job_id": job_id, "status": "CANCELLATION_REQUESTED"}


@router.post("/api/v1/runs/{run_id}/approval")
def approve_run(
    run_id: str,
    request: ApprovalRequest,
    response: Response,
    dependencies: Dependencies,
) -> Mapping[str, object]:
    return dependencies.analysis_service.approve_run(run_id, request, response)


@router.post("/api/v1/runs/{run_id}/cancel")
def cancel_run(
    run_id: str,
    response: Response,
    dependencies: Dependencies,
) -> Mapping[str, object]:
    return dependencies.analysis_service.cancel_run(run_id, response)


def _manifest(run_id: str, dependencies: DependencyContainer) -> RunManifest:
    try:
        path = dependencies.artifact_manager.resolve(run_id, "manifest.json")
        manifest = RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
        if str(manifest.run_id) != run_id:
            raise ValueError("manifest run id does not match requested run")
        return manifest
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        raise _error("MANIFEST_NOT_FOUND", status.HTTP_404_NOT_FOUND) from error


def _require_completed(run_id: str, dependencies: DependencyContainer) -> None:
    state = _read_run(run_id, dependencies)
    if state.get("status") != RunStatus.COMPLETED.value:
        raise _error("RUN_NOT_COMPLETED", status.HTTP_409_CONFLICT)


@router.get("/api/v1/runs/{run_id}/artifacts")
def list_artifacts(run_id: str, dependencies: Dependencies) -> dict[str, object]:
    _require_completed(run_id, dependencies)
    manifest = _manifest(run_id, dependencies)
    return {
        "run_id": run_id,
        "artifacts": [
            {
                "artifact_id": _artifact_id(item.relative_path, item.sha256),
                "sha256": item.sha256,
                "name": Path(item.relative_path).name,
                "media_type": _artifact_media_type(item.relative_path),
            }
            for item in manifest.artifacts
        ]
        + [_manifest_download_record(run_id, dependencies)],
    }


def _artifact_media_type(name: str) -> str:
    # Fixed mapping: Windows registry MIME settings must not change this API contract.
    return {
        ".csv": "text/csv",
        ".tsv": "text/tab-separated-values",
        ".json": "application/json",
        ".html": "text/html",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".log": "text/plain",
        ".md": "text/markdown",
    }.get(Path(name).suffix.lower(), "application/octet-stream")


def _artifact_id(relative_path: str, digest: str) -> str:
    return sha256(f"{relative_path}\0{digest}".encode()).hexdigest()


def _manifest_download_record(run_id: str, dependencies: DependencyContainer) -> dict[str, str]:
    content = dependencies.artifact_manager.resolve(run_id, "manifest.json").read_bytes()
    digest = sha256(content).hexdigest()
    return {
        "artifact_id": _artifact_id("manifest.json", digest),
        "sha256": digest,
        "name": "manifest.json",
        "media_type": "application/json",
    }


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@router.get("/api/v1/runs/{run_id}/artifacts/{artifact_id}")
def download_artifact(
    run_id: str,
    artifact_id: str,
    dependencies: Dependencies,
) -> Response:
    _require_completed(run_id, dependencies)
    manifest = _manifest(run_id, dependencies)
    content = dependencies.artifact_manager.resolve(run_id, "manifest.json").read_bytes()
    if artifact_id == _artifact_id("manifest.json", sha256(content).hexdigest()):
        snapshot = RunManifest.model_validate_json(content)
        if str(snapshot.run_id) != run_id:
            raise _error("ARTIFACT_NOT_FOUND", status.HTTP_404_NOT_FOUND)
        return Response(
            content,
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="manifest.json"',
            },
        )
    record = next(
        (
            item
            for item in manifest.artifacts
            if _artifact_id(item.relative_path, item.sha256) == artifact_id
        ),
        None,
    )
    if record is None:
        raise _error("ARTIFACT_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    try:
        path = dependencies.artifact_manager.resolve(run_id, record.relative_path)
    except (TypeError, ValueError) as error:
        raise _error("ARTIFACT_NOT_FOUND", status.HTTP_404_NOT_FOUND) from error
    if not path.is_file():
        raise _error("ARTIFACT_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    if _file_sha256(path) != record.sha256:
        raise _error("ARTIFACT_INTEGRITY_ERROR", status.HTTP_409_CONFLICT)
    return FileResponse(path, filename=path.name)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(dependencies: Dependencies) -> dict[str, str]:
    try:
        is_ready = dependencies.readiness()
    except Exception:
        is_ready = False
    if not is_ready:
        raise _error("DEPENDENCIES_NOT_READY", status.HTTP_503_SERVICE_UNAVAILABLE)
    return {"status": "ready"}
