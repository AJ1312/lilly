"""The decision log: round-trip, bounds, pruning, outcomes, calibration arithmetic, and the `lilly decisions` command."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from lilly.core.calibration import MIN_KEPT, MIN_LABELLED, calibrate
from lilly.daemon.cli import main
from lilly.domain.decisions import Context, DecisionRecord, DecisionSettings, Kind, Option
from lilly.engine.decisions import DatabaseSink, DecisionPipeline
from lilly.store import decisions, retention
from lilly.store.connection import open_db
from lilly.store.db import Database
from tests.helpers import Clock

DAY = 86400.0


@pytest.fixture
def con(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = open_db(tmp_path / "t.db")
    yield c
    c.close()


def rec(ts: float = 1000.0, kind: Kind = Kind.PICK, decider: str | None = "match", choice: str | None = "a",
        confidence: float | None = 0.9, shadow: bool = False, summary: str = "open firefox",
        reason: str = "ok", outcome: str = "unknown") -> DecisionRecord:
    return DecisionRecord(ts, kind, "task-1", decider, choice, confidence, shadow, 3, summary, reason, outcome)


def test_a_record_comes_back_unchanged(con: sqlite3.Connection) -> None:
    row_id = decisions.insert(con, rec(shadow=True))
    [row] = decisions.recent(con)
    assert (row.id, row.ts, row.task_id, row.kind, row.decider, row.choice, row.confidence, row.shadow,
            row.outcome, row.options, row.summary, row.reason) == (
        row_id, 1000.0, "task-1", "pick", "match", "a", 0.9, True, "unknown", 3, "open firefox", "ok")


def test_a_no_decision_row_has_empty_decider_choice_and_confidence(con: sqlite3.Connection) -> None:
    decisions.insert(con, rec(decider=None, choice=None, confidence=None))
    [row] = decisions.recent(con)
    assert (row.decider, row.choice, row.confidence) == (None, None, None)


def test_the_store_redacts_and_caps_text_even_if_a_caller_did_not(con: sqlite3.Connection) -> None:
    decisions.insert(con, rec(summary=("word " * 200) + "sk-abcdefghijklmnopqrstuv", reason="r" * 999, choice="c" * 999))
    [row] = decisions.recent(con)
    assert len(row.summary) <= 300 and len(row.reason) <= 200 and len(row.choice or "") <= 120
    decisions.insert(con, rec(summary="key sk-abcdefghijklmnopqrstuv here"))
    assert "sk-abc" not in decisions.recent(con)[0].summary


def test_an_unknown_outcome_is_stored_as_unknown(con: sqlite3.Connection) -> None:
    decisions.insert(con, rec(outcome="bogus"))
    assert decisions.recent(con)[0].outcome == "unknown"


def test_recent_is_newest_first_limited_and_filterable_by_question(con: sqlite3.Connection) -> None:
    for i in range(5):
        decisions.insert(con, rec(ts=float(i), kind=Kind.LOOP if i % 2 else Kind.PICK))
    assert [r.ts for r in decisions.recent(con, 3)] == [4.0, 3.0, 2.0]
    assert [r.ts for r in decisions.recent(con, 10, Kind.LOOP)] == [3.0, 1.0]
    assert decisions.recent(con, 0) == []


def test_outcomes_are_recorded_later_and_only_from_the_known_set(con: sqlite3.Connection) -> None:
    row_id = decisions.insert(con, rec())
    assert decisions.set_outcome(con, row_id, "accepted") and decisions.recent(con)[0].outcome == "accepted"
    assert decisions.set_outcome(con, row_id + 99, "corrected") is False
    with pytest.raises(ValueError):
        decisions.set_outcome(con, row_id, "allowed")


def test_summary_counts_per_question_and_decider(con: sqlite3.Connection) -> None:
    for outcome in ("accepted", "accepted", "corrected", "unknown"):
        decisions.insert(con, rec(outcome=outcome))
    decisions.insert(con, rec(shadow=True))
    decisions.insert(con, rec(decider=None, choice=None, confidence=None))
    decisions.insert(con, rec(kind=Kind.LOOP, decider="loop"))
    rows = {(s.kind, s.decider): s for s in decisions.summary(con)}
    match = rows[("pick", "match")]
    assert (match.decisions, match.answered, match.shadow, match.accepted, match.corrected) == (5, 5, 1, 2, 1)
    none = rows[("pick", None)]
    assert (none.decisions, none.answered) == (1, 0)
    assert rows[("loop", "loop")].decisions == 1


def test_labelled_returns_only_answers_with_a_known_outcome(con: sqlite3.Connection) -> None:
    decisions.insert(con, rec(outcome="accepted", confidence=0.9))
    decisions.insert(con, rec(outcome="corrected", confidence=0.6))
    decisions.insert(con, rec(outcome="unknown"))
    decisions.insert(con, rec(outcome="accepted", decider=None, choice=None, confidence=None))
    assert sorted(decisions.labelled(con)) == [("pick", "match", 0.6, False), ("pick", "match", 0.9, True)]


def test_the_log_never_grows_past_its_bound_even_without_pruning(con: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decisions, "MAX_ROWS", 10)
    for i in range(25):
        decisions.insert(con, rec(ts=float(i)))
    rows = decisions.recent(con, 100)
    assert len(rows) == 10 and rows[-1].ts == 15.0 and rows[0].ts == 24.0


def test_pruning_removes_rows_older_than_the_cutoff_and_enforces_the_bound(con: sqlite3.Connection,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    now = 100 * DAY
    for age in (1, 5, 40, 60):
        decisions.insert(con, rec(ts=now - age * DAY))
    assert decisions.prune(con, 30, now) == 2
    assert len(decisions.recent(con)) == 2
    assert decisions.prune(con, 0, now) == 0                         # 0 days: keep everything
    monkeypatch.setattr(decisions, "MAX_ROWS", 1)
    assert decisions.prune(con, 30, now) == 1 and len(decisions.recent(con)) == 1


def test_task_retention_also_prunes_the_decision_log(con: sqlite3.Connection) -> None:
    now = 400 * DAY
    decisions.insert(con, rec(ts=now - 200 * DAY))
    decisions.insert(con, rec(ts=now - DAY))
    retention.prune_tasks(con, 90, now)
    assert len(decisions.recent(con)) == 1


async def test_the_pipeline_logs_through_the_database_sink(tmp_path: Path) -> None:
    db = Database(tmp_path / "lilly.db")
    try:
        class Always:
            name = "match"

            async def decide(self, request: object) -> object:
                from lilly.domain.decisions import Answer
                return Answer("match", "a", 0.95)

        pipeline = DecisionPipeline(DecisionSettings, lambda: {"match": Always()}, DatabaseSink(db), Clock())  # type: ignore[dict-item]
        out = await pipeline.decide(Kind.PICK, "t1", (Option("a", "Alpha"),), Context("open alpha"))
        [row] = decisions.recent(db.reader)
        assert out.log_id == row.id and (row.decider, row.choice, row.summary) == ("match", "a", "open alpha")
        await db.write(lambda c: decisions.set_outcome(c, row.id, "accepted"))
        assert decisions.recent(db.reader)[0].outcome == "accepted"
    finally:
        db.close()


# ---- calibration -----------------------------------------------------------------------------------------------
def synthetic() -> list[tuple[float, bool]]:
    """Confidence 0.5-0.6: half right. 0.7-0.8: 80% right. 0.9: all right."""
    low = [(0.55, i % 2 == 0) for i in range(20)]
    mid = [(0.75, i % 5 != 0) for i in range(30)]
    high = [(0.9, True) for _ in range(40)]
    return low + mid + high


def test_the_smallest_threshold_meeting_the_target_is_found_with_its_effect() -> None:
    c = calibrate(synthetic(), target=0.95, current=0.5)
    assert c.threshold == 0.9 and c.labelled == 90
    assert c.coverage_before == 1.0 and c.precision_before == pytest.approx((10 + 24 + 40) / 90)
    assert c.coverage_after == pytest.approx(40 / 90) and c.precision_after == 1.0


def test_a_lower_target_gives_a_lower_threshold() -> None:
    c = calibrate(synthetic(), target=0.85, current=0.5)
    assert c.threshold == 0.75 and c.precision_after == pytest.approx(64 / 70)


def test_the_threshold_is_the_smallest_one_that_still_meets_the_target() -> None:
    samples = [(0.6, True)] * 12 + [(0.8, True)] * 12 + [(0.4, False)] * 12
    assert calibrate(samples, 0.95, 0.4).threshold == 0.6


def test_no_suggestion_when_the_target_is_out_of_reach_or_support_is_thin() -> None:
    wrong = [(0.9, i % 2 == 0) for i in range(60)]
    assert calibrate(wrong, 0.95, 0.5).threshold is None
    thin = [(0.9, True)] * (MIN_KEPT - 1) + [(0.5, False)] * 30
    assert calibrate(thin, 0.95, 0.5).threshold is None


def test_too_few_outcomes_make_no_suggestion() -> None:
    few = [(0.9, True)] * (MIN_LABELLED - 1)
    c = calibrate(few, 0.95, 0.5)
    assert c.threshold is None and c.coverage_before == 1.0
    empty = calibrate([], 0.95, 0.5)
    assert empty.threshold is None and empty.precision_before is None and empty.coverage_before == 0.0


def test_samples_at_the_same_confidence_are_judged_together() -> None:
    samples = [(0.9, True)] * 10 + [(0.9, False)] * 10      # one level, half right: it cannot be split
    assert calibrate(samples, 0.95, 0.5).threshold is None


# ---- the command ----------------------------------------------------------------------------------------------
@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LILLY_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_report_and_calibrate_say_so_when_there_is_no_log_yet(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["decisions", "report"]) == 0
    assert "No decisions have been logged yet." in capsys.readouterr().out
    assert main(["decisions", "calibrate"]) == 0
    assert "nothing to calibrate" in capsys.readouterr().out


def test_report_lists_each_question_and_decider(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["decisions", "report"])
    con = open_db(home / "lilly.db")
    for outcome in ("accepted", "accepted", "accepted", "corrected"):
        decisions.insert(con, rec(outcome=outcome))
    decisions.insert(con, rec(decider=None, choice=None, confidence=None))
    con.close()
    capsys.readouterr()
    assert main(["decisions", "report"]) == 0
    out = capsys.readouterr().out
    assert "pick" in out and "match" in out and "(none)" in out
    line = next(line for line in out.splitlines() if " match " in line)
    assert "4" in line and "100%" in line and "75%" in line and "4 known" in line


def test_calibrate_suggests_a_threshold_and_changes_nothing(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["decisions", "report"])
    con = open_db(home / "lilly.db")
    for confidence, right in synthetic():
        decisions.insert(con, rec(confidence=confidence, outcome="accepted" if right else "corrected"))
    decisions.insert(con, rec(kind=Kind.LOOP, decider="loop", confidence=0.9, outcome="accepted"))
    con.close()
    capsys.readouterr()
    assert main(["decisions", "calibrate", "--target", "0.95"]) == 0
    out = capsys.readouterr().out
    assert "pick / match: 90 answers" in out and "min_confidence now 0.85" in out
    assert "suggested 0.90" in out and "keeps 44% of answers" in out and "right 100% of the time" in out
    assert "loop / loop" in out and "too few outcomes" in out
    assert "Nothing was changed" in out
    assert not (home / "config" / "settings.json").exists()      # no setting was written
    assert main(["decisions", "calibrate", "--target", "1.0"]) == 0
    assert "pick / match: 90 answers" in capsys.readouterr().out


def test_calibrate_rejects_a_target_outside_zero_to_one(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["decisions", "calibrate", "--target", "1.5"]) == 2
    assert "--target" in capsys.readouterr().err


async def test_a_busy_database_means_the_decision_is_not_logged_but_is_still_made(tmp_path: Path) -> None:
    from lilly.domain.errors import WriterBusy

    class Busy:
        async def write(self, fn: object) -> int:
            raise WriterBusy()

    assert await DatabaseSink(Busy()).record(rec()) is None  # type: ignore[arg-type]


def test_the_two_assist_questions_appear_in_report_and_calibrate_like_any_other(home: Path,
                                                                                capsys: pytest.CaptureFixture[str]) -> None:
    main(["decisions", "report"])
    con = open_db(home / "lilly.db")
    for kind, choice in ((Kind.PLAN, "off"), (Kind.REPLY, "drifts")):
        for confidence, right in synthetic():
            decisions.insert(con, rec(kind=kind, decider="laya", choice=choice, shadow=True, confidence=confidence,
                                      outcome="accepted" if right else "corrected"))
    con.close()
    capsys.readouterr()
    assert main(["decisions", "report"]) == 0
    report = capsys.readouterr().out
    for kind in ("plan", "reply"):
        line = next(line for line in report.splitlines() if line.startswith(kind) and " laya " in line)
        assert "90" in line and "100%" in line and "82%" in line      # 90 asked, all answered, 74 of 90 right
    assert main(["decisions", "calibrate", "--target", "0.95"]) == 0
    calibrated = capsys.readouterr().out
    assert "plan / laya: 90 answers" in calibrated and "reply / laya: 90 answers" in calibrated
    assert "min_confidence now 0.70" in calibrated and "suggested 0.90" in calibrated
