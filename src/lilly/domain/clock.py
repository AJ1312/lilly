"""Clock type alias. Time is always injected, never read directly in logic."""
from __future__ import annotations

from collections.abc import Callable

Clock = Callable[[], float]
