"""Tests verifying the audit fixes for LLY-003, LLY-005, LLY-006, LLY-007, LLY-008, LLY-009, LLY-017, LLY-023."""

from lilly.domain.tasks import ExecutionTarget
from lilly.store import approvals as approval_store
from lilly.store import conversations, memory, tasks


def test_approval_json_extracts_risk_tool_why_target():
    """Verify approval_json extracts top-level tool, target, risk, and why (LLY-007)."""
    from lilly.ui.support import approval_json

    row = approval_store.ApprovalRow(
        id="appr-1",
        task_id="task-1",
        step_id="step-1",
        kind="step",
        summary="fs.delete — Delete temporary cache",
        payload_json='{"tool": "fs.delete", "target": "/tmp/cache", "why": "Cleanup cache", "risk": "high"}',
        payload_hash="hash123",
        status="pending",
        created_at=1000.0,
        expires_at=1060.0,
        decided_at=None,
    )
    dto = approval_json(row)
    assert dto["tool"] == "fs.delete"
    assert dto["target"] == "/tmp/cache"
    assert dto["risk"] == "high"
    assert dto["why"] == "Cleanup cache"
    assert dto["summary"] == "fs.delete — Delete temporary cache"


def test_memory_json_contains_both_text_and_fact_tags_and_category():
    """Verify memory_json supports both API and frontend expectations (LLY-006)."""
    from lilly.domain.labels import Label
    from lilly.ui.support import memory_json

    row = memory.MemoryRow(
        id="mem-1",
        text="Never use rm -rf on root",
        source="user",
        label=Label.PERSONAL,
        created_at=12345.0,
        tags=("constraint", "safety"),
    )
    dto = memory_json(row)
    assert dto["text"] == "Never use rm -rf on root"
    assert dto["fact"] == "Never use rm -rf on root"
    assert dto["category"] == "constraint"
    assert dto["tags"] == ["constraint", "safety"]
    assert dto["at"] == 12345.0
    assert dto["created_at"] == 12345.0


def test_step_and_task_and_message_json_compatibility():
    """Verify step_json has result and duration_s, task_json has duration_s, message_json has created_at (LLY-017, LLY-023)."""
    from lilly.domain.labels import Label
    from lilly.domain.tasks import TaskOutcome, TaskState
    from lilly.ui.support import message_json, step_json, task_json

    step_row = tasks.StepRow(
        step_id="s1",
        position=1,
        tool="shell.exec",
        status="success",
        args_json='{"command": "echo hi"}',
        output="hi\n",
        label=Label.PUBLIC,
        untrusted=False,
        error=None,
        started_at=100.0,
        finished_at=102.5,
    )
    s_dto = step_json(step_row)
    assert s_dto["output"] == "hi\n"
    assert s_dto["result"] == "hi\n"
    assert s_dto["duration_s"] == 2.5

    task_row = tasks.TaskRow(
        id="t1",
        conversation_id="c1",
        agent_id=None,
        state=TaskState.DONE,
        goal="Run command",
        mode=1,
        label=Label.PUBLIC,
        tainted=False,
        skill=None,
        plan_json=None,
        pinned_model=None,
        answer="Finished",
        error=None,
        created_at=100.0,
        updated_at=105.0,
        finished_at=105.0,
        outcome=TaskOutcome.SUCCESS,
        outcome_reason=None,
        target=ExecutionTarget.HOST,
    )
    t_dto = task_json(task_row)
    assert t_dto["duration_s"] == 5.0

    msg_row = conversations.MessageRow(
        id="m1",
        conversation_id="c1",
        task_id="t1",
        role="assistant",
        content="Hello",
        label=Label.PUBLIC,
        untrusted=False,
        created_at=200.0,
    )
    m_dto = message_json(msg_row)
    assert m_dto["at"] == 200.0
    assert m_dto["created_at"] == 200.0
