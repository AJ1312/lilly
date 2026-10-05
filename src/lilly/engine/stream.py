"""Text that is still being written, shown live. Not stored: the finished answer is what the task records."""
from __future__ import annotations

from lilly.domain.clock import Clock
from lilly.engine.bus import EventBus

MIN_INTERVAL_S = 0.1     # at most ten updates a second, however fast the model writes
MAX_CHARS = 12_000       # what is shown while writing; the full answer arrives when the step ends


class TextStream:
    """Callable that receives the whole text so far and publishes it, no faster than `min_interval_s`."""

    def __init__(self, bus: EventBus, task_id: str, step_id: str, clock: Clock, *,
                 min_interval_s: float = MIN_INTERVAL_S, max_chars: int = MAX_CHARS) -> None:
        self._bus, self._task_id, self._step_id, self._clock = bus, task_id, step_id, clock
        self._min, self._max = min_interval_s, max_chars
        self._last: float | None = None

    def __call__(self, text: str) -> None:
        now = self._clock()
        if self._last is not None and now - self._last < self._min:
            return
        self._last = now
        shown = text if len(text) <= self._max else "…" + text[-(self._max - 1):]
        self._bus.publish({"type": "text", "task_id": self._task_id, "step_id": self._step_id, "text": shown})
