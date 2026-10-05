"""Receipt builder: produces verifiable proof of actions and costs from SQLite records only."""
from __future__ import annotations

import contextlib
import fnmatch
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lilly.engine.messages import RECEIPT_TEMPLATE
from lilly.store.db import Database
from lilly.store.tasks import list_steps

READ_TOOLS = frozenset({
    "fs.read", "fs.list", "fs.search", "data.profile",
    "web.fetch", "web.search", "web.research",
    "notes.read", "notes.search", "memory.search", "result.read",
})

WRITE_TOOLS = frozenset({
    "fs.write", "fs.edit", "fs.apply_moves", "fs.trash",
    "notes.write", "memory.write",
})

RUN_TOOLS = frozenset({
    "computer.run", "devbox.run", "computer.open_app", "computer.open_url",
    "computer.stop_process", "computer.notify", "computer.processes",
    "browser.open", "browser.read", "browser.find", "browser.click",
    "browser.type", "browser.select", "browser.press", "browser.submit",
    "browser.scroll", "browser.back", "browser.close",
})


@dataclass(frozen=True, slots=True)
class Receipt:
    task_id: str
    n_read: int
    n_written: int
    approved_time: str
    n_ran: int
    calls: int
    tokens_in: int
    tokens_out: int
    waited_s: float
    seconds: float
    n_tests: int
    skipped_or_failed: str

    def render(self) -> str:
        changed_tests_line = f"\nChanged test files: {self.n_tests}" if self.n_tests > 0 else ""
        return RECEIPT_TEMPLATE.format(
            n_read=self.n_read,
            n_written=self.n_written,
            time=self.approved_time,
            n_ran=self.n_ran,
            calls=self.calls,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            waited_s=self.waited_s,
            seconds=self.seconds,
            changed_tests_line=changed_tests_line,
            list_or_none=self.skipped_or_failed or "none",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "read_items": self.n_read,
            "written_items": self.n_written,
            "approved": self.approved_time,
            "ran_items": self.n_ran,
            "model_calls": self.calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "waited_seconds": self.waited_s,
            "duration_seconds": self.seconds,
            "changed_test_files": self.n_tests,
            "skipped_or_failed": self.skipped_or_failed,
            "text": self.render(),
        }


def _matches_any_glob(path_str: str, globs: tuple[str, ...]) -> bool:
    if not path_str or not globs:
        return False
    p = Path(path_str)
    name = p.name
    full = str(p)
    for pattern in globs:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(full, pattern):
            return True
        for part in p.parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


class ReceiptBuilder:
    """Builds a receipt strictly from database records without any model invocation."""

    @staticmethod
    def build_from_con(con: sqlite3.Connection, task_id: str,
                       protected_globs: tuple[str, ...] = ("*test*", "*tests*", "test_*", "*_test.*")) -> Receipt:
        # 1. Task record duration
        task_row = con.execute("SELECT created_at, finished_at FROM tasks WHERE id=?", (task_id,)).fetchone()
        if task_row:
            created_at, finished_at = float(task_row[0]), task_row[1]
            if finished_at is not None:
                duration_s = max(0.0, round(float(finished_at) - created_at, 1))
            else:
                duration_s = 0.0
        else:
            duration_s = 0.0

        # 2. Steps
        steps = list_steps(con, task_id)
        n_read = 0
        n_written = 0
        n_ran = 0
        n_tests = 0
        problems: list[str] = []

        for s in steps:
            tool = s.tool
            if s.status == "done":
                if tool in READ_TOOLS:
                    n_read += 1
                elif tool in WRITE_TOOLS:
                    n_written += 1
                    # Check if write touched protected test paths
                    args: dict[str, Any] = {}
                    if s.args_json:
                        with contextlib.suppress(Exception):
                            args = json.loads(s.args_json)
                    target = str(args.get("path") or args.get("root") or "")
                    if _matches_any_glob(target, protected_globs):
                        n_tests += 1
                elif tool in RUN_TOOLS:
                    n_ran += 1
            elif s.status in ("failed", "skipped"):
                desc = f"{tool} ({s.error or s.status})"
                problems.append(desc)

        # 3. Model calls
        mc_row = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(tokens_in), 0), COALESCE(SUM(tokens_out), 0), "
            "COALESCE(SUM(waited_ms), 0) FROM model_calls WHERE task_id=?",
            (task_id,),
        ).fetchone()
        calls = int(mc_row[0]) if mc_row else 0
        tokens_in = int(mc_row[1]) if mc_row else 0
        tokens_out = int(mc_row[2]) if mc_row else 0
        waited_s = round(float(mc_row[3]) / 1000.0, 1) if mc_row else 0.0

        # 4. Approvals for write actions
        appr_row = con.execute(
            "SELECT COUNT(*) FROM approvals WHERE task_id=? AND status='approved'",
            (task_id,),
        ).fetchone()
        approved_count = int(appr_row[0]) if appr_row else 0
        approved_time = str(approved_count)

        skipped_or_failed = ", ".join(problems) if problems else "none"

        return Receipt(
            task_id=task_id,
            n_read=n_read,
            n_written=n_written,
            approved_time=approved_time,
            n_ran=n_ran,
            calls=calls,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            waited_s=waited_s,
            seconds=duration_s,
            n_tests=n_tests,
            skipped_or_failed=skipped_or_failed,
        )

    @classmethod
    def build(cls, db: Database, task_id: str,
              protected_globs: tuple[str, ...] = ("*test*", "*tests*", "test_*", "*_test.*")) -> Receipt:
        return cls.build_from_con(db.reader, task_id, protected_globs)
