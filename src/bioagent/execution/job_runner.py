from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Event, RLock
from typing import Self
from uuid import uuid4

from bioagent.domain.runs import RunStatus
from bioagent.execution.controller import ExecutionResult
from bioagent.execution.r_runner import RExecutionCancelledError

CancellationCheck = Callable[[], bool]
JobCallable = Callable[[CancellationCheck], object]


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_TERMINAL_STATUSES = frozenset(
    {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
)


@dataclass
class _JobRecord:
    job_id: str
    execution_key: str
    status: JobStatus = JobStatus.QUEUED
    cancellation: Event = field(default_factory=Event)
    future: Future[None] | None = None


class LocalJobRunner:
    """Process-local single-worker scheduler.

    The scheduler owns concurrency and cancellation signalling only. The submitted
    callable must recreate its own execution resources and delegate scientific
    execution/idempotency decisions to ``ExecutionController``.
    """

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="bioagent-job",
        )
        self._lock = RLock()
        self._jobs: dict[str, _JobRecord] = {}
        self._active_by_key: dict[str, str] = {}
        self._closed = False

    def submit(self, execution_key: str, task: JobCallable) -> str:
        if not execution_key:
            raise ValueError("execution_key must be non-empty")
        if not callable(task):
            raise TypeError("task must be callable")
        with self._lock:
            if self._closed:
                raise RuntimeError("job runner is closed")
            active_job_id = self._active_by_key.get(execution_key)
            if active_job_id is not None:
                active = self._jobs[active_job_id]
                if active.status not in _TERMINAL_STATUSES:
                    return active_job_id

            job_id = str(uuid4())
            record = _JobRecord(job_id=job_id, execution_key=execution_key)
            self._jobs[job_id] = record
            self._active_by_key[execution_key] = job_id
            record.future = self._executor.submit(self._run, record, task)
            return job_id

    def status(self, job_id: str) -> JobStatus:
        with self._lock:
            return self._record(job_id).status

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            record = self._record(job_id)
            if record.status in _TERMINAL_STATUSES:
                return False
            record.cancellation.set()
            future = record.future
            if (
                record.status is JobStatus.QUEUED
                and future is not None
                and future.cancel()
            ):
                record.status = JobStatus.CANCELLED
                self._release_active(record)
                return True
            return False

    def wait(self, job_id: str, *, timeout: float | None = None) -> None:
        with self._lock:
            future = self._record(job_id).future
        if future is None:
            return
        try:
            future.result(timeout=timeout)
        except CancelledError:
            return

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for record in self._jobs.values():
                if record.status is JobStatus.QUEUED:
                    record.cancellation.set()
                    if record.future is not None:
                        record.future.cancel()
                    record.status = JobStatus.CANCELLED
                    self._release_active(record)
                elif record.status is JobStatus.RUNNING:
                    record.cancellation.set()
        self._executor.shutdown(wait=True, cancel_futures=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _run(self, record: _JobRecord, task: JobCallable) -> None:
        with self._lock:
            if record.status is JobStatus.CANCELLED:
                return
            record.status = JobStatus.RUNNING
        try:
            result = task(record.cancellation.is_set)
        except RExecutionCancelledError:
            terminal_status = JobStatus.CANCELLED
        except Exception:
            terminal_status = JobStatus.FAILED
        else:
            if (
                not isinstance(result, ExecutionResult)
                or result.status is RunStatus.COMPLETED
            ):
                terminal_status = JobStatus.COMPLETED
            elif result.status is RunStatus.CANCELLED:
                terminal_status = JobStatus.CANCELLED
            else:
                terminal_status = JobStatus.FAILED
        with self._lock:
            record.status = terminal_status
            self._release_active(record)

    def _record(self, job_id: str) -> _JobRecord:
        try:
            return self._jobs[job_id]
        except KeyError as error:
            raise KeyError(f"job not found: {job_id}") from error

    def _release_active(self, record: _JobRecord) -> None:
        if self._active_by_key.get(record.execution_key) == record.job_id:
            del self._active_by_key[record.execution_key]
