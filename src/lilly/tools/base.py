"""The Tool base class and helpers for reading arguments safely."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path

from lilly.domain.errors import PolicyDenied, ValidationFailed
from lilly.domain.labels import Verdict
from lilly.domain.policy import PathScope
from lilly.domain.ports import ToolContext, ToolResult
from lilly.domain.tools_registry import DEFAULT_TOOLS, ToolSpec


class Tool(ABC):
    """A capability the engine can run. Its risk and labels are pinned in DEFAULT_TOOLS."""

    name: str

    @property
    def spec(self) -> ToolSpec:
        return DEFAULT_TOOLS[self.name]

    def review(self, args: Mapping[str, object], task_id: str) -> tuple[Verdict, str]:
        """A tool's own check of the exact arguments, applied on top of the policy: it can ask for approval or
        refuse, never allow more than the policy did. Most tools have none."""
        return Verdict.ALLOW, "ok"

    def warm(self) -> None:
        """Called when a plan that uses this tool is accepted, so anything slow to start can begin early. It must
        return at once and never fail."""
        return None

    def summary(self, args: Mapping[str, object], output: str) -> str:
        """The sentence shown as the answer when this tool ends a task. Default: the tool's own output."""
        return output

    def standing_target(self, args: Mapping[str, object]) -> str | None:
        """Return the standing approval target for this tool, or None if not applicable."""
        return None

    @abstractmethod
    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        """Run with the already-resolved arguments. Raises ToolError, ValidationFailed or PolicyDenied."""


def int_arg(args: Mapping[str, object], key: str, default: int, *, lo: int, hi: int) -> int:
    """A whole-number argument, clamped to [lo, hi]. Anything that is not a number is a validation error."""
    raw = args.get(key)
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise ValidationFailed(f"'{key}' must be a number")
    try:
        value = int(float(raw))
    except (ValueError, OverflowError):
        raise ValidationFailed(f"'{key}' must be a number") from None
    return max(lo, min(hi, value))


def str_arg(args: Mapping[str, object], key: str, *, max_len: int = 100_000, required: bool = True) -> str:
    raw = args.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if required:
            raise ValidationFailed(f"missing required argument '{key}'")
        return ""
    if not isinstance(raw, str):
        raise ValidationFailed(f"'{key}' must be text")
    if len(raw) > max_len:
        raise ValidationFailed(f"'{key}' is too long")
    return raw


def bool_arg(args: Mapping[str, object], key: str) -> bool:
    raw = args.get(key, False)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.strip().lower() in ("true", "false"):
        return raw.strip().lower() == "true"
    raise ValidationFailed(f"'{key}' must be true or false")


def resolve_in_scope(raw: str, scope: PathScope) -> Path:
    """The canonical path, or PolicyDenied when it is outside every shared folder."""
    if not scope.allows(raw):
        raise PolicyDenied("that path is outside the folders you share with Lilly (see Settings → Privacy & access)")
    return Path(raw).expanduser().resolve()
