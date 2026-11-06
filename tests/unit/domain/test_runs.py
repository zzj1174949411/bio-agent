import warnings

import pytest
from pydantic import ValidationError

from bioagent.config import Settings
from bioagent.domain.qc import QCIssue, QCReport, QCStatus
from bioagent.domain.runs import RunStatus, ensure_transition


def test_running_requires_queued_state() -> None:
    ensure_transition(RunStatus.QUEUED, RunStatus.RUNNING)
    with pytest.raises(ValueError, match="invalid run transition"):
        ensure_transition(RunStatus.DRAFT, RunStatus.RUNNING)


def test_qc_report_records_structured_evidence() -> None:
    issue = QCIssue(
        code="LOW_REPLICATION",
        status=QCStatus.WARN,
        message="one comparison group has two samples",
        evidence={"sample_count": 2},
    )

    report = QCReport(status=QCStatus.WARN, issues=[issue])

    assert report.status == QCStatus.WARN
    assert report.issues[0].evidence == {"sample_count": 2}


@pytest.mark.parametrize(
    ("report_status", "issue_statuses"),
    [
        (QCStatus.PASS, [QCStatus.WARN]),
        (QCStatus.WARN, [QCStatus.FAIL]),
        (QCStatus.FAIL, []),
        (QCStatus.WARN, [QCStatus.PASS]),
    ],
)
def test_qc_report_rejects_status_inconsistent_with_issue_severity(
    report_status: QCStatus,
    issue_statuses: list[QCStatus],
) -> None:
    issues = [
        QCIssue(code=f"ISSUE_{index}", status=status, message="test issue")
        for index, status in enumerate(issue_statuses)
    ]

    with pytest.raises(ValidationError, match="status must match issue severity"):
        QCReport(status=report_status, issues=issues)


def test_qc_report_cannot_be_mutated_out_of_consistency() -> None:
    report = QCReport(
        status=QCStatus.WARN,
        issues=[QCIssue(code="WARNING", status=QCStatus.WARN, message="warning")],
    )

    with pytest.raises(ValidationError, match="frozen_instance"):
        report.status = QCStatus.PASS
    with pytest.raises(ValidationError, match="frozen_instance"):
        report.issues[0].status = QCStatus.PASS
    assert not hasattr(report.issues, "append")


@pytest.mark.parametrize(
    "update",
    [
        {"status": QCStatus.PASS},
        {
            "issues": (
                QCIssue(code="FAILURE", status=QCStatus.FAIL, message="failure"),
            )
        },
    ],
)
def test_qc_report_copy_revalidates_consistency(update: dict[str, object]) -> None:
    report = QCReport(
        status=QCStatus.WARN,
        issues=[QCIssue(code="WARNING", status=QCStatus.WARN, message="warning")],
    )

    with pytest.raises(ValidationError, match="status must match issue severity"):
        report.model_copy(update=update)


def test_qc_report_copy_preserves_shallow_and_deep_semantics_without_warnings() -> None:
    warning_issue = QCIssue(code="WARNING", status=QCStatus.WARN, message="warning")
    failure_issue = QCIssue(code="FAILURE", status=QCStatus.FAIL, message="failure")
    report = QCReport(status=QCStatus.WARN, issues=[warning_issue])

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        updated = report.model_copy(
            update={"status": QCStatus.FAIL, "issues": [failure_issue]}
        )
        shallow = report.model_copy()
        deep = report.model_copy(deep=True)

    assert updated.status is QCStatus.FAIL
    assert updated.issues == (failure_issue,)
    assert shallow.issues[0] is report.issues[0]
    assert deep.issues[0] is not report.issues[0]


def test_settings_have_expected_execution_boundaries() -> None:
    settings = Settings(_env_file=None)

    assert settings.llm_provider == "deepseek"
    assert settings.rscript == "Rscript"
    assert settings.runs_dir.as_posix() == "runs"
