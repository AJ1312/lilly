"""How a step or a task ends: the two ways to stop early, plain-English error text, and argument helpers.

Shared by the runner, the step executor and the lane scheduler so none of them imports another's internals."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal

from lilly.domain.errors import (
    ApprovalExpired,
    ConflictError,
    LillyError,
    NoModelAvailable,
    PolicyDenied,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    ToolError,
    ValidationFailed,
)
from lilly.domain.plan import REF
from lilly.domain.tasks import TaskState
from lilly.engine.messages import RATE_LIMITED_PROVIDER_ERROR


class Stop(Exception):
    """End the task in a given state with a message for the user."""

    def __init__(self, state: TaskState, message: str) -> None:
        super().__init__(message)
        self.state, self.message = state, message


StepFailureKind = Literal["tool", "policy", "capacity"]


class StepFailed(Exception):
    """One step could not finish. The task may still recover by planning another way."""

    def __init__(self, reason: str, kind: StepFailureKind = "tool") -> None:
        super().__init__(reason)
        self.reason = reason
        self.kind: StepFailureKind = kind


def describe_provider_error(exc: ProviderError) -> str:
    """Say what happened and what to do about it, in plain words."""
    if isinstance(exc, RateLimited):
        model = exc.model or "The model"
        seconds = int(round(exc.retry_after or 0.0))
        return RATE_LIMITED_PROVIDER_ERROR.format(model=model, scope=exc.scope, seconds=seconds)
    status = f" (HTTP {exc.status})" if exc.status else ""
    if exc.status in (401, 403):
        return f"The model provider rejected the API key{status}. Check it in Settings → Models & keys."
    if exc.status == 404:
        return f"The model provider does not know that model{status}. Check the model id in Settings → Models & keys."
    if isinstance(exc, QuotaExhausted):
        return f"The model is rate limited right now{status}. Try again shortly, or add another model to fall back to."
    if exc.retryable:
        return (f"The model service is temporarily overloaded or unreachable{status}. Lilly retried and tried the other "
                "models that have keys. Try again in a minute, or add another model key in Settings → Models & keys.")
    return f"{exc.public}{status}."


def describe_error(exc: BaseException) -> str:
    """A message safe and useful to show the owner. Secrets and payloads never reach it."""
    if isinstance(exc, NoModelAvailable):
        return f"{exc.public}: {exc.reason}"
    if isinstance(exc, ProviderError):
        return describe_provider_error(exc)
    if isinstance(exc, (ToolError, ValidationFailed, PolicyDenied, ApprovalExpired, ConflictError)):
        return str(exc) or exc.public
    if isinstance(exc, LillyError):
        return exc.public
    return "Something went wrong inside Lilly. The details are in the log."


def resolve_refs(value: Any, outputs: Mapping[str, str]) -> Any:
    """Replace `$id.output` with that step's output, everywhere inside an argument value."""
    if isinstance(value, str):
        def one(m: Any) -> str:
            if m.group(1) not in outputs:
                raise StepFailed(f"it needs the result of step {m.group(1)}, which did not produce one")
            return outputs[m.group(1)]
        return REF.sub(one, value)
    if isinstance(value, list):
        return [resolve_refs(v, outputs) for v in value]
    if isinstance(value, dict):
        return {k: resolve_refs(v, outputs) for k, v in value.items()}
    return value


MAX_ITEMS = 20
_MORE = re.compile(r"… \d+ more items")
_CUT = re.compile(r"… \[\d+ characters\]$")


def clip(value: Any, limit: int = 600) -> Any:
    """A display copy of arguments with long strings and long lists shortened, each cut marked where it was made."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"… [{len(value)} characters]"
    if isinstance(value, list):
        shown = [clip(v, limit) for v in value[:MAX_ITEMS]]
        return shown + [f"… {len(value) - MAX_ITEMS} more items"] if len(value) > MAX_ITEMS else shown
    if isinstance(value, dict):
        return {k: clip(v, limit) for k, v in value.items()}
    return value


def is_clipped(value: Any) -> bool:
    """Whether `clip` cut something out of this display copy, so what is shown is not everything that will run."""
    if isinstance(value, str):
        return bool(_MORE.fullmatch(value) or _CUT.search(value))
    if isinstance(value, list):
        return any(is_clipped(v) for v in value)
    if isinstance(value, dict):
        return any(is_clipped(v) for v in value.values())
    return False
