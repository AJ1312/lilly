"""Pure retrieval helper: safe FTS5 query building."""
from __future__ import annotations

import re

_TERM = re.compile(r"[^\W_]{2,}", re.UNICODE)


_STOPWORDS = frozenset(["the", "an", "and", "or", "of", "to", "in", "on", "for", "is", "it", "this", "that", "with", "as", "at", "by", "be", "are", "was"])


def fts_query(text: str, max_terms: int = 12) -> str | None:
    """Turn free text into a safe FTS5 query: each word is quoted, so operators such as
    NEAR, AND, '*', '-' or 'column:' in user text can never change the query's meaning.
    Returns None when nothing searchable remains."""
    terms: list[str] = []
    seen: set[str] = set()
    for m in _TERM.finditer(text.lower()):
        t = m.group(0)
        if t in _STOPWORDS or t in seen:
            continue
        seen.add(t)
        terms.append(t)
        if len(terms) >= max_terms:
            break
    return " OR ".join(f'"{t}"' for t in terms) if terms else None

