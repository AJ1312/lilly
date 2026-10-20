"""Unit tests for Phase A (truthful task outcomes) and Phase B (execution targets)."""

from __future__ import annotations

from lilly.domain.labels import Label
from lilly.domain.payload import payload_hash
from lilly.domain.tasks import ExecutionTarget, LoopAnswer, TaskOutcome, TaskState
from lilly.engine.intent import Intent
from lilly.store import tasks


def test_screenshot_regression_yt_music_unsupported() -> None:
    """The confirmed screenshot defect: YouTube Music unsupported message must never be marked success/verified."""
    from lilly.engine.agent_loop import AgentLoop

    loop = AgentLoop.__new__(AgentLoop)
    text = (
        "YouTube Music isn't optimized for this browser. For the best experience, use Google Chrome. "
        "Would you like me to switch to Chrome, search manually, or try another platform?"
    )
    outcome, reason, verified = loop._evaluate_outcome(
        text,
        intent=Intent.ACTION,
        action_performed=False,
        action_verified=False,
        had_blocked=False,
        had_declined=False,
        had_failed_step=False,
    )
    assert outcome in (TaskOutcome.BLOCKED, TaskOutcome.NEEDS_USER)
    assert outcome != TaskOutcome.SUCCESS
    assert not verified
    assert reason is not None


def test_action_verified_success() -> None:
    from lilly.engine.agent_loop import AgentLoop

    loop = AgentLoop.__new__(AgentLoop)
    text = "Playing Slow Hands by Niall Horan on the player."
    outcome, reason, verified = loop._evaluate_outcome(
        text,
        intent=Intent.ACTION,
        action_performed=True,
        action_verified=True,
        had_blocked=False,
        had_declined=False,
        had_failed_step=False,
    )
    assert outcome == TaskOutcome.SUCCESS
    assert verified
    assert reason == "action performed and verified"


def test_action_performed_unverified() -> None:
    from lilly.engine.agent_loop import AgentLoop

    loop = AgentLoop.__new__(AgentLoop)
    text = "Clicked the play button on the page."
    outcome, reason, verified = loop._evaluate_outcome(
        text,
        intent=Intent.ACTION,
        action_performed=True,
        action_verified=False,
        had_blocked=False,
        had_declined=False,
        had_failed_step=False,
    )
    assert outcome == TaskOutcome.UNVERIFIED
    assert not verified
    assert "not verified" in (reason or "")


def test_action_only_navigation_is_not_success() -> None:
    from lilly.engine.agent_loop import AgentLoop

    loop = AgentLoop.__new__(AgentLoop)
    text = "I opened the YouTube Music page for you. How would you like to proceed?"
    outcome, reason, verified = loop._evaluate_outcome(
        text,
        intent=Intent.ACTION,
        action_performed=False,
        action_verified=False,
        had_blocked=False,
        had_declined=False,
        had_failed_step=False,
    )
    assert outcome == TaskOutcome.NEEDS_USER
    assert not verified


def test_action_with_declined_approval() -> None:
    from lilly.engine.agent_loop import AgentLoop

    loop = AgentLoop.__new__(AgentLoop)
    text = "You declined the action."
    outcome, reason, verified = loop._evaluate_outcome(
        text,
        intent=Intent.ACTION,
        action_performed=False,
        action_verified=False,
        had_blocked=False,
        had_declined=True,
        had_failed_step=False,
    )
    assert outcome == TaskOutcome.NEEDS_USER
    assert not verified


def test_action_blocked_by_policy() -> None:
    from lilly.engine.agent_loop import AgentLoop

    loop = AgentLoop.__new__(AgentLoop)
    text = "The action was blocked by security policy."
    outcome, reason, verified = loop._evaluate_outcome(
        text,
        intent=Intent.ACTION,
        action_performed=False,
        action_verified=False,
        had_blocked=True,
        had_declined=False,
        had_failed_step=False,
    )
    assert outcome == TaskOutcome.BLOCKED
    assert not verified


def test_answer_intent_success_without_forcing_action_verification() -> None:
    from lilly.engine.agent_loop import AgentLoop

    loop = AgentLoop.__new__(AgentLoop)
    text = "Python was created by Guido van Rossum."
    outcome, reason, verified = loop._evaluate_outcome(
        text,
        intent=Intent.ANSWER,
        action_performed=False,
        action_verified=False,
        had_blocked=False,
        had_declined=False,
        had_failed_step=False,
    )
    assert outcome == TaskOutcome.SUCCESS
    assert not verified


def test_target_bound_in_approval_payload_hash() -> None:
    """Approval payload hash must differ when target changes, preventing approval reuse across targets."""
    payload_host = {"tool": "computer.click", "args": {"x": 100, "y": 200}, "target": "host"}
    payload_devbox = {"tool": "computer.click", "args": {"x": 100, "y": 200}, "target": "devbox"}

    hash_host = payload_hash("task_1", "step_1", "step", payload_host)
    hash_devbox = payload_hash("task_1", "step_1", "step", payload_devbox)

    assert hash_host != hash_devbox


def test_loop_answer_properties() -> None:
    ans = LoopAnswer(
        "Done successfully", outcome=TaskOutcome.SUCCESS, outcome_reason="Verified file match", verified=True
    )
    assert isinstance(ans, str)
    assert ans == "Done successfully"
    assert ans.outcome == TaskOutcome.SUCCESS
    assert ans.outcome_reason == "Verified file match"
    assert ans.verified


from pathlib import Path

from lilly.store.connection import open_db


def test_task_store_outcomes_and_targets_migration_and_query(tmp_path: Path) -> None:
    """Validate DB operations with outcomes, targets, count_tasks, and list_tasks."""
    db_file = tmp_path / "test.db"
    con = open_db(db_file)

    now = 1000.0
    t1 = tasks.create_task(
        con, id="t1", goal="Goal 1", mode=0, label=Label.PUBLIC, tainted=False, now=now, target=ExecutionTarget.HOST
    )
    assert t1.outcome == TaskOutcome.UNVERIFIED
    assert t1.target == ExecutionTarget.HOST

    t2 = tasks.create_task(
        con,
        id="t2",
        goal="Goal 2 in container",
        mode=0,
        label=Label.PUBLIC,
        tainted=False,
        now=now + 1,
        target=ExecutionTarget.DEVBOX,
    )
    assert t2.target == ExecutionTarget.DEVBOX

    # Move t1 through PLANNING to DONE with explicit SUCCESS outcome
    tasks.set_state(con, "t1", TaskState.PLANNING, now + 2)
    t1_updated = tasks.set_state(
        con, "t1", TaskState.DONE, now + 10, answer="Done", outcome=TaskOutcome.SUCCESS, outcome_reason="Verified"
    )
    assert t1_updated.state == TaskState.DONE
    assert t1_updated.outcome == TaskOutcome.SUCCESS
    assert t1_updated.outcome_reason == "Verified"

    # Move t2 to FAILED without explicit outcome; should default to BLOCKED
    t2_updated = tasks.set_state(con, "t2", TaskState.FAILED, now + 10, error="Timed out")
    assert t2_updated.state == TaskState.FAILED
    assert t2_updated.outcome == TaskOutcome.BLOCKED

    # Test count_tasks and list_tasks with target and outcome filters
    assert tasks.count_tasks(con, target=ExecutionTarget.HOST) == 1
    assert tasks.count_tasks(con, target=ExecutionTarget.DEVBOX) == 1
    assert tasks.count_tasks(con, outcomes=(TaskOutcome.SUCCESS,)) == 1
    assert tasks.count_tasks(con, outcomes=(TaskOutcome.BLOCKED,)) == 1

    host_tasks = tasks.list_tasks(con, target=ExecutionTarget.HOST)
    assert len(host_tasks) == 1
    assert host_tasks[0].id == "t1"

    devbox_tasks = tasks.list_tasks(con, target=ExecutionTarget.DEVBOX)
    assert len(devbox_tasks) == 1
    assert devbox_tasks[0].id == "t2"


def test_cross_target_approval_hash_isolation() -> None:
    from lilly.domain.payload import payload_hash

    task_id = "task-cross-target"
    step_id = "s1"
    tool = "fs.write"
    args = {"path": "/shared/data.txt", "content": "test"}

    host_payload = {"tool": tool, "args": args}
    devbox_payload = {"tool": tool, "args": args, "target": "devbox"}

    host_hash = payload_hash(task_id, step_id, "step", host_payload)
    devbox_hash = payload_hash(task_id, step_id, "step", devbox_payload)

    assert host_hash != devbox_hash, "Approvals must not be transferable between Host and DevBox"
