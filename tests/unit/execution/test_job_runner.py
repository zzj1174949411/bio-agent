from __future__ import annotations

from collections.abc import Callable
from threading import Event, Thread

import pytest

from bioagent.domain.qc import QCIssue, QCReport, QCStatus
from bioagent.domain.runs import RunStatus
from bioagent.execution.controller import ExecutionResult
from bioagent.execution.job_runner import JobStatus, LocalJobRunner
from bioagent.execution.r_runner import RExecutionCancelledError


def test_submit_returns_immediately_with_job_id() -> None:
    release = Event()
    started = Event()

    def task(cancelled: Callable[[], bool]) -> None:
        started.set()
        release.wait(timeout=5)

    with LocalJobRunner() as runner:
        job_id = runner.submit("execution-key", task)

        assert job_id
        assert started.wait(timeout=1)
        assert runner.status(job_id) is JobStatus.RUNNING
        release.set()
        runner.wait(job_id, timeout=1)
        assert runner.status(job_id) is JobStatus.COMPLETED


def test_duplicate_in_flight_submission_returns_existing_job() -> None:
    release = Event()
    started = Event()
    calls = 0

    def task(cancelled: Callable[[], bool]) -> None:
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=5)

    with LocalJobRunner() as runner:
        first = runner.submit("same-key", task)
        assert started.wait(timeout=1)
        second = runner.submit("same-key", task)
        release.set()
        runner.wait(first, timeout=1)

    assert second == first
    assert calls == 1


def test_terminal_failure_resubmission_gets_new_job() -> None:
    calls = 0

    def task(cancelled: Callable[[], bool]) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("injected failure")

    with LocalJobRunner() as runner:
        first = runner.submit("same-key", task)
        runner.wait(first, timeout=1)
        assert runner.status(first) is JobStatus.FAILED

        second = runner.submit("same-key", task)
        runner.wait(second, timeout=1)

    assert second != first
    assert calls == 2


def test_cancel_queued_job_prevents_execution() -> None:
    release_first = Event()
    first_started = Event()
    second_called = Event()

    def first_task(cancelled: Callable[[], bool]) -> None:
        first_started.set()
        release_first.wait(timeout=5)

    def second_task(cancelled: Callable[[], bool]) -> None:
        second_called.set()

    with LocalJobRunner() as runner:
        first = runner.submit("first", first_task)
        assert first_started.wait(timeout=1)
        second = runner.submit("second", second_task)

        assert runner.cancel(second) is True
        assert runner.status(second) is JobStatus.CANCELLED
        release_first.set()
        runner.wait(first, timeout=1)

    assert second_called.is_set() is False


def test_cancel_running_job_has_stable_cancelled_terminal_state() -> None:
    started = Event()
    saw_cancellation = Event()

    def task(cancelled: Callable[[], bool]) -> None:
        started.set()
        while not cancelled():
            saw_cancellation.wait(timeout=0.01)
        saw_cancellation.set()
        raise RExecutionCancelledError

    with LocalJobRunner() as runner:
        job_id = runner.submit("cancel-running", task)
        assert started.wait(timeout=1)

        assert runner.cancel(job_id) is False
        runner.wait(job_id, timeout=1)

        assert saw_cancellation.is_set()
        assert runner.status(job_id) is JobStatus.CANCELLED
        assert runner.cancel(job_id) is False


def test_running_cancellation_request_cannot_promise_cancelled_if_task_ignores_it(
) -> None:
    started = Event()
    release = Event()

    def task(cancelled: Callable[[], bool]) -> None:
        started.set()
        release.wait(timeout=5)

    with LocalJobRunner() as runner:
        job_id = runner.submit("ignores-cancellation", task)
        assert started.wait(timeout=1)

        assert runner.cancel(job_id) is False
        release.set()
        runner.wait(job_id, timeout=1)

        assert runner.status(job_id) is JobStatus.COMPLETED


def test_close_marks_queued_jobs_cancelled() -> None:
    release_first = Event()
    first_started = Event()
    second_called = Event()
    runner = LocalJobRunner()

    def first_task(cancelled: Callable[[], bool]) -> None:
        first_started.set()
        release_first.wait(timeout=5)

    def second_task(cancelled: Callable[[], bool]) -> None:
        second_called.set()

    first = runner.submit("first", first_task)
    assert first_started.wait(timeout=1)
    second = runner.submit("second", second_task)
    closer = Thread(target=runner.close)
    closer.start()

    assert runner.status(second) is JobStatus.CANCELLED
    release_first.set()
    closer.join(timeout=1)

    assert not closer.is_alive()
    assert runner.status(first) is JobStatus.COMPLETED
    assert runner.status(second) is JobStatus.CANCELLED
    assert second_called.is_set() is False


@pytest.mark.parametrize(
    ("run_status", "expected_job_status", "error_code"),
    [
        (RunStatus.FAILED, JobStatus.FAILED, "R_EXECUTION_FAILED"),
        (RunStatus.CANCELLED, JobStatus.CANCELLED, "R_EXECUTION_CANCELLED"),
    ],
)
def test_execution_result_terminal_status_controls_job_status(
    run_status: RunStatus,
    expected_job_status: JobStatus,
    error_code: str,
) -> None:
    result = ExecutionResult(
        attempt_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        execution_key="e" * 64,
        status=run_status,
        qc=QCReport(
            status=QCStatus.FAIL,
            issues=(
                QCIssue(
                    code=error_code,
                    status=QCStatus.FAIL,
                    message="execution ended without a completed result",
                ),
            ),
        ),
        reused=False,
    )

    with LocalJobRunner() as runner:
        job_id = runner.submit("controller-result", lambda cancelled: result)
        runner.wait(job_id, timeout=1)

        assert runner.status(job_id) is expected_job_status
