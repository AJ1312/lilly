"""Data labels, risk levels, verdicts, access modes and the per-task context."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum


class Label(IntEnum):
    PUBLIC = 0
    PERSONAL = 1
    SECRET = 2


class Risk(IntEnum):
    R0 = 0  # read-only
    R1 = 1  # reversible local change
    R2 = 2  # external or irreversible
    R3 = 3  # forbidden


class Verdict(IntEnum):
    ALLOW = 0
    NEEDS_APPROVAL = 1
    DENY = 2


class Mode(IntEnum):
    """How much an agent may do with private data. Chosen per agent."""
    LOCKED = 0  # no private access: PERSONAL/SECRET data is off limits
    ASK = 1     # asks before reading or sharing private data
    OPEN = 2    # no prompts for private data or irreversible actions; the floor still applies


class ApprovalMode(StrEnum):
    """How approval-required actions are handled."""
    MANUAL = "MANUAL"
    AUTO = "AUTO"
    OFF = "OFF"


@dataclass(frozen=True, slots=True)
class TaskCtx:
    label: Label = Label.PUBLIC
    tainted: bool = False
    mode: Mode = Mode.ASK
    approval_mode: ApprovalMode = ApprovalMode.MANUAL

    def absorb(self, label: Label, untrusted: bool) -> TaskCtx:
        """Join with a new input: label is a max-lattice, taint is OR."""
        return TaskCtx(max(self.label, label), self.tainted or untrusted, self.mode, self.approval_mode)


@dataclass(frozen=True, slots=True)
class ToolCall:
    tool: str
    risk: Risk
    egress: bool = False
    paths: tuple[str, ...] = ()
    reads_label: Label = Label.PUBLIC   # sensitivity of the data this call reads
    confirm: bool = False               # the user must approve every time, in every mode
