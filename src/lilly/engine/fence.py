"""One place that wraps text from outside so the model reads it as data, never as instructions."""
from __future__ import annotations

import re

OPEN, CLOSE = "<untrusted_data>", "</untrusted_data>"
_TAG = re.compile(r"<\s*/?\s*untrusted_data\b[^>]*>", re.IGNORECASE)


def neutralise(text: str) -> str:
    """Break any fence-like tag inside the text. It stays readable ('&lt;/untrusted_data>') but cannot close ours."""
    return _TAG.sub(lambda m: m.group(0).replace("<", "&lt;", 1), text)


def fence(text: str, limit: int | None = None) -> tuple[str, bool]:
    """Truncate FIRST, neutralise, then wrap. Returns (fenced, was_truncated). The closing tag is always present."""
    cut = limit is not None and len(text) > limit
    body = neutralise(text[:limit] if cut else text)
    return f"{OPEN}\n{body}\n{CLOSE}", cut