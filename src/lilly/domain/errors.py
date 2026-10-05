"""One error hierarchy. Callers handle errors by type; `public` is always safe to show to a user.

Details (paths, payloads, provider messages) go only to the redacted log, never into `public`.
"""
from __future__ import annotations

from typing import Literal


class LillyError(Exception):
    """Base class. `public` is safe to show; never put a secret or a payload in it."""

    public: str = "Internal error"


class PolicyDenied(LillyError):
    public = "Blocked by policy"


class ValidationFailed(LillyError, ValueError):
    """Also a ValueError, so existing `except ValueError` callers keep working."""

    public = "Invalid input"


class NotFound(LillyError, KeyError):
    """Also a KeyError, for the same reason."""

    public = "Not found"


class ApprovalExpired(LillyError):
    public = "Approval expired"


class ToolError(LillyError):
    public = "The tool failed"


class ProviderError(LillyError):
    public = "The model provider failed"

    def __init__(self, retryable: bool, retry_after: float | None = None, status: int | None = None) -> None:
        super().__init__(retryable, retry_after, status)
        self.retryable, self.retry_after, self.status = retryable, retry_after, status


RateLimitScope = Literal["minute", "day", "tokens", "unknown"]


class QuotaExhausted(ProviderError):
    public = "Model quota used up for now"


class RateLimited(QuotaExhausted):
    public = "Model rate limited"

    def __init__(
        self,
        scope: RateLimitScope = "unknown",
        retry_after: float | None = None,
        status: int = 429,
        model: str | None = None,
    ) -> None:
        super().__init__(retryable=True, retry_after=retry_after, status=status)
        self.scope: RateLimitScope = scope
        self.model: str | None = model


class WriterBusy(LillyError):
    public = "Database writer is busy"


class ConfigurationError(LillyError):
    public = "Configuration error"


class ConflictError(LillyError):
    public = "Conflict or stale revision"




class NeedsGrant(LillyError):
    """No model may see this data yet, but some could if the user allows it."""

    public = "Needs your permission"

    def __init__(self, models: list[str], label: int) -> None:
        super().__init__(models, label)
        self.models, self.label = models, label


class NoModelAvailable(LillyError):
    """Every model is busy, over quota, down, or not allowed to see the data."""

    public = "No model is available right now"

    def __init__(self, reason: str, soonest: tuple[tuple[str, float], ...] = ()) -> None:
        super().__init__(reason)
        self.reason = reason
        self.soonest = soonest
