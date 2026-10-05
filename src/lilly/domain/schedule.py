"""When a routine runs. Pure functions: time and time zone are passed in, nothing reads the clock."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from lilly.domain.errors import ValidationFailed

MIN_EVERY_MINUTES = 5
MAX_EVERY_MINUTES = 7 * 24 * 60
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_AT = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


@dataclass(frozen=True, slots=True)
class Schedule:
    """`every`: every N minutes. `at`: at HH:MM local time on the listed weekdays (0 = Monday); all seven for daily."""
    kind: str
    every_minutes: int = 0
    at: str = ""
    days: tuple[int, ...] = ()


def parse_schedule(raw: object) -> Schedule:
    if not isinstance(raw, Mapping):
        raise ValidationFailed("schedule must be an object")
    kind = raw.get("kind")
    if kind == "every":
        n = raw.get("every_minutes")
        if isinstance(n, bool) or not isinstance(n, int) or not MIN_EVERY_MINUTES <= n <= MAX_EVERY_MINUTES:
            raise ValidationFailed(f"repeat every {MIN_EVERY_MINUTES} to {MAX_EVERY_MINUTES} minutes")
        return Schedule("every", every_minutes=n)
    if kind == "at":
        at, days = raw.get("at"), raw.get("days")
        if not isinstance(at, str) or not _AT.fullmatch(at):
            raise ValidationFailed("time must look like 08:30")
        if (not isinstance(days, list) or not days or len(set(days)) != len(days)
                or any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in days)):
            raise ValidationFailed("choose at least one weekday")
        return Schedule("at", at=at, days=tuple(sorted(days)))
    raise ValidationFailed("schedule kind must be 'every' or 'at'")


def schedule_to_dict(s: Schedule) -> dict[str, Any]:
    if s.kind == "every":
        return {"kind": "every", "every_minutes": s.every_minutes}
    return {"kind": "at", "at": s.at, "days": list(s.days)}


def next_run(s: Schedule, after: float, tz: tzinfo | None = None) -> float:
    """The first run strictly after `after`. `tz` None means the computer's local time zone."""
    if s.kind == "every":
        return after + s.every_minutes * 60.0
    hour, minute = int(s.at[:2]), int(s.at[3:])
    start: date = datetime.fromtimestamp(after, tz).date()
    for offset in range(0, 9):
        day = start + timedelta(days=offset)
        if day.weekday() not in s.days:
            continue
        stamp = datetime.combine(day, time(hour, minute), tzinfo=tz).timestamp()
        if stamp > after:
            return stamp
    raise ValidationFailed("schedule has no upcoming run")  # unreachable: parse_schedule requires a weekday


def describe(s: Schedule) -> str:
    if s.kind == "every":
        n = s.every_minutes
        if n % 1440 == 0:
            return "Every day" if n == 1440 else f"Every {n // 1440} days"
        if n % 60 == 0:
            return "Every hour" if n == 60 else f"Every {n // 60} hours"
        return f"Every {n} minutes"
    if len(s.days) == 7:
        return f"Every day at {s.at}"
    if s.days == (0, 1, 2, 3, 4):
        return f"Weekdays at {s.at}"
    return f"{', '.join(DAY_NAMES[d] for d in s.days)} at {s.at}"
