"""Model capability flags."""
from __future__ import annotations

from enum import IntFlag


class Cap(IntFlag):
    NONE = 0
    JSON = 1          # reliable structured JSON output: needed to plan
    LONG_CONTEXT = 2  # accepts a very long prompt: needed to read big documents
    TOOLS = 4         # tool calling supported (advisory)
