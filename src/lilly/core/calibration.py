"""Choosing a confidence threshold from the decision log: pure arithmetic, no model calls, changes nothing."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

MIN_LABELLED = 20     # fewer known outcomes than this say too little to suggest anything
MIN_KEPT = 10         # a threshold that keeps fewer answers than this is not trusted


@dataclass(frozen=True, slots=True)
class Calibration:
    labelled: int
    threshold: float | None            # the smallest confidence that meets the target; None if none does
    coverage_before: float             # share of answers kept at the current threshold
    precision_before: float | None     # share of those kept that were right (None when none were kept)
    coverage_after: float
    precision_after: float | None


def _at(samples: Sequence[tuple[float, bool]], threshold: float) -> tuple[float, float | None]:
    kept = [right for confidence, right in samples if confidence >= threshold]
    return len(kept) / len(samples), (sum(kept) / len(kept) if kept else None)


def calibrate(samples: Sequence[tuple[float, bool]], target: float, current: float) -> Calibration:
    """`samples` are (confidence, was_right) for answers whose outcome is known. Finds the smallest
    min_confidence at which the answers kept are right at least `target` of the time, and compares it with
    `current`. A threshold only counts when it keeps at least MIN_KEPT answers."""
    if len(samples) < MIN_LABELLED:
        before = _at(samples, current) if samples else (0.0, None)
        return Calibration(len(samples), None, *before, *before)
    best: float | None = None
    kept = right = 0
    ordered = sorted(samples, key=lambda s: -s[0])
    for i, (confidence, was_right) in enumerate(ordered):
        kept, right = kept + 1, right + was_right
        if i + 1 < len(ordered) and ordered[i + 1][0] == confidence:
            continue                                  # take every answer at this confidence together
        if kept >= MIN_KEPT and right / kept >= target:
            best = confidence                         # lower thresholds keep more, so the last hit is the smallest
    before = _at(samples, current)
    after = _at(samples, best) if best is not None else before
    return Calibration(len(samples), best, *before, *after)
