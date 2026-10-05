"""Rule-based checks on what a step produced. No model is asked to grade its own work."""
from __future__ import annotations

# Tools whose reply may legitimately be short or empty.
_MAY_BE_EMPTY = frozenset({"memory.write", "fs.write", "fs.trash"})


def check_output(tool: str, output: str) -> str | None:
    """A reason the output is unacceptable, or None when it is fine."""
    if tool in _MAY_BE_EMPTY:
        return None
    if not output.strip():
        return "it returned nothing"
    return None
