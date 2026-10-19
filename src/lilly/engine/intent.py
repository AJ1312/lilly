"""Small deterministic boundary between conversation and computer/web work."""
from __future__ import annotations

import re
from enum import StrEnum


class Intent(StrEnum):
    ANSWER = "ANSWER"
    WEB_RETRIEVE = "WEB RETRIEVE"
    NAVIGATE = "NAVIGATE"
    ACTION = "ACTION"


def parse_requested_intent(value: str | None) -> Intent | None:
    """Parse an optional user-selected intent; AUTO returns to classification."""
    if value is None:
        return None
    normalized = " ".join(value.replace("_", " ").split()).upper()
    if normalized in ("", "AUTO", "AUTOMATIC"):
        return None
    try:
        return Intent(normalized)
    except ValueError:
        raise ValueError(f"unknown request intent: {value}") from None


_ACTION = re.compile(
    r"\b(play|pause|send|post|buy|book|create|delete|fill|type|click|select|download|upload|"
    r"submit|share|save|install|run|move|drag|scroll)\b", re.I,
)
_NAVIGATE = re.compile(r"\b(open|go\s+to|visit|navigate\s+to|take\s+me\s+to)\b", re.I)
_RETRIEVE = re.compile(
    r"\b(search|look\s+up|find\s+out|research|latest|news|weather|price|summari[sz]e)\b", re.I,
)


def classify_intent(goal: str) -> Intent:
    """Classify the requested outcome, not the first tool-shaped phrase."""
    text = " ".join(goal.split())
    if _ACTION.search(text):
        return Intent.ACTION
    if _RETRIEVE.search(text):
        return Intent.WEB_RETRIEVE
    if _NAVIGATE.search(text):
        return Intent.NAVIGATE
    return Intent.ANSWER
