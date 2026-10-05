"""The reasoning layers every task passes through, and redaction for anything shown or logged."""
from __future__ import annotations

import re
from enum import IntEnum


class Layer(IntEnum):
    """Each layer leaves a visible trace in the task's event log."""

    UNDERSTAND = 0  # the model's restatement of the goal, assumptions and unknowns
    PLAN = 1        # the steps chosen
    CRITIQUE = 2    # policy preflight: what will be allowed, asked about or blocked
    ACT = 3         # per step: what runs and why
    VERIFY = 4      # per step: what came back
    REFLECT = 5     # the outcome and what it cost


_SECRETS = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}"
                      r"|Bearer\s+[A-Za-z0-9._~+/=-]{12,}|\b[A-Fa-f0-9]{40,}\b)")


def redact(text: str) -> str:
    """Mask anything that looks like an API key or token before it is stored or displayed."""
    return _SECRETS.sub("[redacted]", text)
