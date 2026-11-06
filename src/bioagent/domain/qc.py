from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class QCStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class QCIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    status: QCStatus
    message: str = Field(min_length=1)
    evidence: dict[str, JsonValue] = Field(default_factory=dict)


class QCReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: QCStatus
    issues: tuple[QCIssue, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def status_matches_issue_severity(self) -> Self:
        expected_status = QCStatus.PASS
        if any(issue.status is QCStatus.FAIL for issue in self.issues):
            expected_status = QCStatus.FAIL
        elif any(issue.status is QCStatus.WARN for issue in self.issues):
            expected_status = QCStatus.WARN

        if self.status is not expected_status:
            raise ValueError("QCReport status must match issue severity")
        return self

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        copied = super().model_copy(update=update, deep=deep)
        return type(self).model_validate(
            {"status": copied.status, "issues": copied.issues}
        )
