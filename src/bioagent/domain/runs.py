from enum import StrEnum


class RunStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.DRAFT: frozenset({RunStatus.VALIDATING, RunStatus.CANCELLED}),
    RunStatus.VALIDATING: frozenset(
        {
            RunStatus.AWAITING_APPROVAL,
            RunStatus.VALIDATION_FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.AWAITING_APPROVAL: frozenset(
        {RunStatus.QUEUED, RunStatus.CANCELLED}
    ),
    RunStatus.QUEUED: frozenset(
        {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.RUNNING: frozenset(
        {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.VALIDATION_FAILED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


def ensure_transition(current: RunStatus, target: RunStatus) -> None:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"invalid run transition: {current} -> {target}")
