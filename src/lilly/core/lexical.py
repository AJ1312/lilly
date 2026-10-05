"""Plain keyword scoring (BM25) of a few short texts against a query: no model, no libraries, deterministic."""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

_WORD = re.compile(r"[a-z0-9]+")
# Words that say nothing about which tool or item is meant.
_FILLER = frozenset("a an and any are as at be by can do for from how i in is it its me my of on or please that the "
                    "this to use want what when with you your".split())
K1, B = 1.5, 0.75


def words(text: str) -> list[str]:
    """Lower-case words with a crude plural stripped, so "files" finds "file". Names like fs.read split in two."""
    return [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
            for w in _WORD.findall(text.lower()) if w not in _FILLER]


@dataclass(frozen=True, slots=True)
class Scored:
    scores: Mapping[str, float]    # BM25 score per text id; 0.0 when no query word appears
    coverage: float                # share of the query's words that appear in at least one text


def score(query: str, texts: Mapping[str, str]) -> Scored:
    """Score each text against the query. Ties are the caller's to break (by their own order)."""
    wanted = list(dict.fromkeys(words(query)))
    docs = {key: Counter(words(text)) for key, text in texts.items()}
    if not wanted or not docs:
        return Scored(dict.fromkeys(texts, 0.0), 0.0)
    avg = sum(sum(d.values()) for d in docs.values()) / len(docs) or 1.0
    total = len(docs)
    scores = dict.fromkeys(texts, 0.0)
    found = 0
    for word in wanted:
        holders = [key for key, d in docs.items() if word in d]
        found += bool(holders)
        idf = math.log(1 + (total - len(holders) + 0.5) / (len(holders) + 0.5))
        for key in holders:
            d = docs[key]
            tf, length = d[word], sum(d.values())
            scores[key] += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / avg))
    return Scored(scores, found / len(wanted))
