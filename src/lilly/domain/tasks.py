"""Task lifecycle: the states a task can be in and the moves between them."""

from __future__ import annotations

from enum import Enum

from lilly.domain.errors import ConflictError


class TaskState(Enum):
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    VERIFYING = "VERIFYING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class TaskOutcome(str, Enum):
    UNVERIFIED = "unverified"
    SUCCESS = "success"
    PARTIAL = "partial"
    NEEDS_USER = "needs_user"
    BLOCKED = "blocked"


class ExecutionTarget(str, Enum):
    HOST = "host"
    DEVBOX = "devbox"


class LoopAnswer(str):
    outcome: TaskOutcome
    outcome_reason: str | None
    verified: bool

    def __new__(
        cls,
        content: str,
        outcome: TaskOutcome = TaskOutcome.SUCCESS,
        outcome_reason: str | None = None,
        verified: bool = False,
    ) -> LoopAnswer:
        instance = super().__new__(cls, content)
        instance.outcome = outcome
        instance.outcome_reason = outcome_reason
        instance.verified = verified
        return instance


TERMINAL: frozenset[TaskState] = frozenset({TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED, TaskState.EXPIRED})

_S = TaskState
_FORWARD: dict[TaskState, frozenset[TaskState]] = {
    _S.PENDING: frozenset({_S.PLANNING}),
    _S.PLANNING: frozenset(
        {_S.RUNNING, _S.DONE, _S.WAITING_APPROVAL}
    ),  # DONE: direct answer; WAITING_APPROVAL: model grant
    _S.RUNNING: frozenset({_S.WAITING_APPROVAL, _S.VERIFYING}),
    _S.WAITING_APPROVAL: frozenset({_S.PLANNING, _S.RUNNING, _S.EXPIRED}),
    _S.VERIFYING: frozenset({_S.DONE}),
}


def check_transition(old: TaskState, new: TaskState) -> None:
    """Raise ConflictError unless `old -> new` is legal. Any live task may fail or be cancelled."""
    if old in TERMINAL:
        raise ConflictError(f"task is already {old.value}")
    if new in (_S.FAILED, _S.CANCELLED) or new in _FORWARD.get(old, frozenset()):
        return
    raise ConflictError(f"illegal task transition {old.value} -> {new.value}")
