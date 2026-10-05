"""Tests for GroundingVerifier, ReceiptBuilder, and protected paths safety (GR-01..08)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lilly.domain.labels import Label, Verdict
from lilly.domain.policy import PathScope
from lilly.domain.prompts import PROTECTED_PATH_REASON
from lilly.engine.grounding import GroundingVerifier
from lilly.engine.messages import GROUNDING_REMOVED_NOTE, GROUNDING_REPAIR
from lilly.engine.receipt import ReceiptBuilder
from lilly.store.approvals import create_approval, decide
from lilly.store.db import Database
from lilly.store.ledger import ModelCallRecord, record_model_call
from lilly.store.tasks import create_steps, create_task, update_step
from lilly.tools.fs import FsApplyMovesTool, FsTrashTool, FsWriteTool


# GR-01: Seen URLs and paths are kept without repair
def test_gr_01_seen_urls_and_paths_kept() -> None:
    gv = GroundingVerifier(file_roots=("/workspace/project",))
    gv.record_user_message("Check https://example.com/docs and file /workspace/project/README.md")
    gv.record_step("fs.read", {"path": "/workspace/project/src/main.py"}, "code content")

    candidate = (
        "I checked https://example.com/docs and found /workspace/project/src/main.py "
        "and /workspace/project/README.md."
    )
    ok, unseen = gv.verify(candidate)
    assert ok is True
    assert unseen == []


# GR-02: Unseen URL triggers repair turn
def test_gr_02_unseen_url_triggers_repair_turn() -> None:
    gv = GroundingVerifier()
    candidate = "According to https://hallucinated.example.com/paper, python is great."
    ok, unseen = gv.verify(candidate)
    assert ok is False
    assert unseen == ["https://hallucinated.example.com/paper"]

    repair = gv.repair_prompt(unseen)
    expected = GROUNDING_REPAIR.format(list="https://hallucinated.example.com/paper")
    assert repair == expected
    assert (
        repair == "These references in your answer did not come from any tool result or from the user: "
        "https://hallucinated.example.com/paper. Remove them, or fetch or read them first, then answer again."
    )


# GR-03: Unseen path triggers repair turn
def test_gr_03_unseen_path_triggers_repair_turn() -> None:
    gv = GroundingVerifier(file_roots=("/workspace/project",))
    candidate = "The results are saved at /etc/shadow or /nonexistent/hallucinated/file.txt."
    ok, unseen = gv.verify(candidate)
    assert ok is False
    assert "/etc/shadow" in unseen
    assert "/nonexistent/hallucinated/file.txt" in unseen

    repair = gv.repair_prompt(unseen)
    assert "These references in your answer did not come from any tool result or from the user:" in repair
    assert "/etc/shadow" in repair
    assert "Remove them, or fetch or read them first, then answer again." in repair


# GR-04: Still unseen after repair triggers removal and note
def test_gr_04_still_unseen_after_repair_triggers_removal_and_note() -> None:
    gv = GroundingVerifier()
    candidate = "Here is the download: https://invented.com/file and /var/fake/path.txt."
    ok, unseen = gv.verify(candidate)
    assert ok is False
    assert len(unseen) == 2

    cleaned = gv.remove_unseen(candidate, unseen)
    assert "https://invented.com/file" not in cleaned
    assert "/var/fake/path.txt" not in cleaned
    expected_note = GROUNDING_REMOVED_NOTE.format(n=2)
    assert expected_note == "Lilly removed 2 link(s) or path(s) from this answer because no step had returned them."
    assert cleaned.endswith(expected_note)


# GR-05: Grounding disabled passes unseen references untouched
def test_gr_05_grounding_disabled() -> None:
    gv = GroundingVerifier(enabled=False)
    candidate = "Check https://hallucinated.example.com and /fake/path.txt"
    ok, unseen = gv.verify(candidate)
    assert ok is True
    assert unseen == []


# GR-06: Receipt built without model invocation strictly from SQLite
@pytest.mark.asyncio
async def test_gr_06_receipt_built_without_model(tmp_path: Path) -> None:
    db = Database(tmp_path / "lilly.db")
    task_id = "task_test_06"

    def populate(con: Any) -> None:
        create_task(con, id=task_id, goal="organize files", mode=1, label=Label.PUBLIC, tainted=False, now=100.0)
        con.execute("UPDATE tasks SET finished_at=115.5 WHERE id=?", (task_id,))

        # Steps: 1 read done, 1 write done, 1 run done, 1 fetch failed
        steps = [
            ("s1", "fs.read", json.dumps({"path": "/app/a.txt"})),
            ("s2", "fs.write", json.dumps({"path": "/app/b.txt", "content": "hello"})),
            ("s3", "computer.run", json.dumps({"cmd": "ls"})),
            ("s4", "web.fetch", json.dumps({"url": "http://example.com"})),
        ]
        create_steps(con, task_id, steps)
        update_step(con, task_id, "s1", "done", 101.0, output="a content", label=Label.PERSONAL)
        update_step(con, task_id, "s2", "done", 102.0, output="wrote", label=Label.PERSONAL)
        update_step(con, task_id, "s3", "done", 103.0, output="run ok", label=Label.PERSONAL)
        update_step(con, task_id, "s4", "failed", 104.0, error="network timeout")

        # Model calls
        record_model_call(
            con,
            ModelCallRecord(
                id="mc1",
                task_id=task_id,
                turn=1,
                role="planner",
                model="test-model",
                started_at=100.5,
                ms=200,
                tokens_in=500,
                tokens_out=150,
                waited_ms=250,
                outcome="ok",
            ),
        )
        record_model_call(
            con,
            ModelCallRecord(
                id="mc2",
                task_id=task_id,
                turn=2,
                role="actor",
                model="test-model",
                started_at=102.5,
                ms=300,
                tokens_in=500,
                tokens_out=150,
                waited_ms=250,
                outcome="ok",
            ),
        )

        # Approval
        create_approval(
            con,
            id="appr1",
            task_id=task_id,
            step_id="s2",
            kind="step",
            summary="write b.txt",
            payload_json="{}",
            payload_hash="hash1",
            now=101.5,
            ttl_s=60.0,
        )
        decide(con, "appr1", approve=True, payload_hash="hash1", now=101.8)

    await db.write(populate)
    try:
        receipt = ReceiptBuilder.build(db, task_id)
    finally:
        db.close()
    assert receipt.n_read == 1
    assert receipt.n_written == 1
    assert receipt.n_ran == 1
    assert receipt.calls == 2
    assert receipt.tokens_in == 1000
    assert receipt.tokens_out == 300
    assert receipt.waited_s == 0.5
    assert receipt.seconds == 15.5
    assert receipt.approved_time == "1"
    assert "web.fetch (network timeout)" in receipt.skipped_or_failed
    assert receipt.n_tests == 0

    rendered = receipt.render()
    assert "Receipt" in rendered
    assert "Read: 1 item(s)   Wrote: 1 (approved 1)   Ran: 1" in rendered
    assert "Model calls: 2 (1000 in, 300 out)   Waited for capacity: 0.5 s   Time: 15.5 s" in rendered
    assert "web.fetch (network timeout)" in rendered
    # Changed test files is shown only when above zero
    assert "Changed test files:" not in rendered


# GR-07: Protected path returns NEEDS_APPROVAL with exact reason
def test_gr_07_protected_path_approval(tmp_path: Path) -> None:
    scope = PathScope(roots=(tmp_path,))
    protected_globs = ("*test*", "*tests*", "test_*", "*_test.*")

    write_tool = FsWriteTool(scope, protected_globs=protected_globs)
    trash_tool = FsTrashTool(scope, protected_globs=protected_globs)
    moves_tool = FsApplyMovesTool(scope, protected_globs=protected_globs)

    # 1. Non-protected path is allowed
    verdict, reason = write_tool.review({"path": str(tmp_path / "src" / "app.py")}, "task_1")
    assert verdict == Verdict.ALLOW
    assert reason == "ok"

    # 2. FsWriteTool with test file needs approval
    verdict, reason = write_tool.review({"path": str(tmp_path / "tests" / "test_app.py")}, "task_1")
    assert verdict == Verdict.NEEDS_APPROVAL
    assert reason == PROTECTED_PATH_REASON
    assert reason == "This file looks like a test. Changing tests can hide a bug instead of fixing it."

    # 3. FsTrashTool with test file needs approval
    verdict, reason = trash_tool.review({"path": str(tmp_path / "tests" / "test_runner.py")}, "task_1")
    assert verdict == Verdict.NEEDS_APPROVAL
    assert reason == PROTECTED_PATH_REASON

    # 4. FsApplyMovesTool targeting a test file needs approval
    moves_args = {
        "root": str(tmp_path),
        "moves": [{"from": "file.py", "to": "tests/test_x.py"}],
    }
    verdict, reason = moves_tool.review(moves_args, "task_1")
    assert verdict == Verdict.NEEDS_APPROVAL
    assert reason == PROTECTED_PATH_REASON


# GR-08: Test file changes counted in receipt and rendered when above zero
@pytest.mark.asyncio
async def test_gr_08_test_file_change_counted_in_receipt(tmp_path: Path) -> None:
    db = Database(tmp_path / "lilly.db")
    task_id = "task_test_08"

    def populate(con: Any) -> None:
        create_task(con, id=task_id, goal="fix test", mode=1, label=Label.PUBLIC, tainted=False, now=200.0)
        con.execute("UPDATE tasks SET finished_at=205.0 WHERE id=?", (task_id,))

        # Step modifying a test file
        steps = [
            ("s1", "fs.write", json.dumps({"path": "/repo/tests/test_auth.py", "content": "def test_ok(): pass"})),
        ]
        create_steps(con, task_id, steps)
        update_step(con, task_id, "s1", "done", 201.0, output="written", label=Label.PERSONAL)

    await db.write(populate)
    try:
        receipt = ReceiptBuilder.build(db, task_id)
    finally:
        db.close()

    assert receipt.n_tests == 1

    rendered = receipt.render()
    assert "Changed test files: 1" in rendered


def test_gr_additional_recording_coverage() -> None:
    gv = GroundingVerifier(file_roots=("/workspace/root",))
    gv.record_step(
        "web.fetch",
        {"urls": ["https://example.org/item1", "http://example.org/item2"]},
        "fetched content",
    )
    gv.record_step(
        "fs.list",
        {"urls": ["/workspace/root/a.txt", "/workspace/root/b.txt"]},
        json.dumps([{"path": "/workspace/root/sub/c.txt"}]),
    )
    gv.record_step(
        "fs.search",
        {"path": "/workspace/root"},
        json.dumps({"hits": [{"path": "/workspace/root/d.txt"}]}),
    )

    assert gv.is_url_seen("https://example.org/item1") is True
    assert gv.is_url_seen("http://example.org/item2") is True
    assert gv.is_path_seen("/workspace/root/a.txt") is True
    assert gv.is_path_seen("/workspace/root/sub/c.txt") is True
    assert gv.is_path_seen("/workspace/root/d.txt") is True
    assert gv.is_path_seen("/workspace/root/any/nested/file.txt") is True

