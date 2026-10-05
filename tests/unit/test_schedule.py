"""Schedule maths: parsing, the next run time, and plain-language descriptions."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lilly.domain.errors import ValidationFailed
from lilly.domain.schedule import Schedule, describe, next_run, parse_schedule, schedule_to_dict


def stamp(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp()


@pytest.mark.parametrize("raw", [
    None, "daily", {}, {"kind": "cron"},
    {"kind": "every"}, {"kind": "every", "every_minutes": 4}, {"kind": "every", "every_minutes": True},
    {"kind": "every", "every_minutes": 10_081}, {"kind": "every", "every_minutes": "30"},
    {"kind": "at", "at": "8:30", "days": [0]}, {"kind": "at", "at": "24:00", "days": [0]},
    {"kind": "at", "at": "08:30", "days": []}, {"kind": "at", "at": "08:30", "days": [7]},
    {"kind": "at", "at": "08:30", "days": [1, 1]}, {"kind": "at", "at": "08:30"},
])
def test_bad_schedules_are_refused(raw: object) -> None:
    with pytest.raises(ValidationFailed):
        parse_schedule(raw)


def test_parse_round_trips_and_sorts_days() -> None:
    s = parse_schedule({"kind": "at", "at": "08:30", "days": [4, 0, 2]})
    assert s == Schedule("at", at="08:30", days=(0, 2, 4))
    assert parse_schedule(schedule_to_dict(s)) == s
    e = parse_schedule({"kind": "every", "every_minutes": 30})
    assert parse_schedule(schedule_to_dict(e)) == e


def test_every_adds_the_interval() -> None:
    assert next_run(Schedule("every", every_minutes=30), 1000.0) == 1000.0 + 1800.0


def test_daily_runs_later_today_or_tomorrow() -> None:
    daily = Schedule("at", at="08:30", days=(0, 1, 2, 3, 4, 5, 6))
    assert next_run(daily, stamp("2026-10-05T07:00:00"), UTC) == stamp("2026-10-05T08:30:00")
    assert next_run(daily, stamp("2026-10-05T08:30:00"), UTC) == stamp("2026-10-06T08:30:00")  # strictly after
    assert next_run(daily, stamp("2026-10-05T23:59:00"), UTC) == stamp("2026-10-06T08:30:00")


def test_weekly_skips_unchosen_days() -> None:
    weekdays = Schedule("at", at="09:00", days=(0, 1, 2, 3, 4))
    friday_evening = stamp("2026-10-09T18:00:00")  # 2026-10-09 is a Friday
    assert next_run(weekdays, friday_evening, UTC) == stamp("2026-10-12T09:00:00")  # Monday
    monday_only = Schedule("at", at="09:00", days=(0,))
    assert next_run(monday_only, stamp("2026-10-12T09:00:01"), UTC) == stamp("2026-10-19T09:00:00")


def test_descriptions_read_naturally() -> None:
    assert describe(Schedule("every", every_minutes=15)) == "Every 15 minutes"
    assert describe(Schedule("every", every_minutes=60)) == "Every hour"
    assert describe(Schedule("every", every_minutes=180)) == "Every 3 hours"
    assert describe(Schedule("every", every_minutes=1440)) == "Every day"
    assert describe(Schedule("at", at="08:30", days=(0, 1, 2, 3, 4, 5, 6))) == "Every day at 08:30"
    assert describe(Schedule("at", at="08:30", days=(0, 1, 2, 3, 4))) == "Weekdays at 08:30"
    assert describe(Schedule("at", at="18:00", days=(1, 3))) == "Tue, Thu at 18:00"
