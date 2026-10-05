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


TERMINAL: frozenset[TaskState] = frozenset(
    {TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED, TaskState.EXPIRED}
)

_S = TaskState
_FORWARD: dict[TaskState, frozenset[TaskState]] = {
    _S.PENDING: frozenset({_S.PLANNING}),
    _S.PLANNING: frozenset({_S.RUNNING, _S.DONE}),  # DONE: the planner answered directly
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
