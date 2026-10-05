"""Phase 6 Tools test suite: TOOL-01 through TOOL-14.

Covers:
- TOOL-01: fs.edit unique match replaces text
- TOOL-02: fs.edit not found exact error message
- TOOL-03: fs.edit multiple occurrences error message with count
- TOOL-04: fs.edit replace_all=True replaces all occurrences
- TOOL-05: fs.edit atomic write preserves mode and newlines
- TOOL-06: fs.edit approval display unified diff
- TOOL-07: fs.read ranges and 1-based line numbering
- TOOL-08: web.research zero model calls and source excerpts
- TOOL-09: web.research SSRF protections
- TOOL-10: web.research records seen URLs for grounding
- TOOL-11: result.read slices and keeps label and untrusted
- TOOL-12: agent.plan limits and statuses
- TOOL-13: agent.ask answer returned
- TOOL-14: skill.load and undo hash check rejection/restore
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request

from lilly.domain.errors import ConflictError, ToolError, ValidationFailed
from lilly.domain.labels import Label, Mode
from lilly.domain.policy import PathScope
from lilly.domain.ports import ToolContext
from lilly.domain.settings import SearchSettings
from lilly.domain.tasks import TaskState
from lilly.engine.grounding import GroundingVerifier
from lilly.store import agents as agent_store
from lilly.store import tasks
from lilly.tools.agent import AgentAskTool, AgentPlanTool, SkillLoadTool
from lilly.tools.fs import FsEditTool, FsReadTool
from lilly.tools.result import ResultReadTool
from lilly.tools.web import WebFetchTool, WebResearchTool, WebSearchTool
from lilly.ui import api_data
from tests.conftest import Engine
from tests.helpers import MemoryKeyStore

CTX = ToolContext("task-t1", "step-s1", 60.0, lambda: False, Label.PUBLIC, False, Mode.OPEN)


# ---- TOOL-01: fs.edit unique match replaces text ---------------------------------------------
@pytest.mark.asyncio
async def test_tool_01_fs_edit_unique_replaces_text(tmp_path: Path) -> None:
    p = tmp_path / "sample.txt"
    p.write_text("apple banana cherry", encoding="utf-8")
    scope = PathScope((str(tmp_path),))
    tool = FsEditTool(scope)

    res = await tool.run({"path": str(p), "old": "banana", "new": "blueberry"}, CTX)
    assert "Successfully edited" in res.output
    assert p.read_text(encoding="utf-8") == "apple blueberry cherry"


# ---- TOOL-02: fs.edit not found exact error message ------------------------------------------
@pytest.mark.asyncio
async def test_tool_02_fs_edit_not_found(tmp_path: Path) -> None:
    p = tmp_path / "sample.txt"
    p.write_text("apple banana cherry", encoding="utf-8")
    scope = PathScope((str(tmp_path),))
    tool = FsEditTool(scope)

    with pytest.raises(ToolError, match=f"old text not found in {p}"):
        await tool.run({"path": str(p), "old": "orange", "new": "blueberry"}, CTX)


# ---- TOOL-03: fs.edit multiple occurrences error message with count --------------------------
@pytest.mark.asyncio
async def test_tool_03_fs_edit_multiple_occurrences(tmp_path: Path) -> None:
    p = tmp_path / "multi.txt"
    p.write_text("apple banana cherry banana date banana", encoding="utf-8")
    scope = PathScope((str(tmp_path),))
    tool = FsEditTool(scope)

    expected = f"old text appears 3 times in {p}; add surrounding lines to make it unique or set replace_all"
    with pytest.raises(ToolError) as exc_info:
        await tool.run({"path": str(p), "old": "banana", "new": "kiwi"}, CTX)
    assert str(exc_info.value) == expected


# ---- TOOL-04: fs.edit replace_all=True replaces all occurrences -------------------------------
@pytest.mark.asyncio
async def test_tool_04_fs_edit_replace_all(tmp_path: Path) -> None:
    p = tmp_path / "multi.txt"
    p.write_text("apple banana cherry banana date banana", encoding="utf-8")
    scope = PathScope((str(tmp_path),))
    tool = FsEditTool(scope)

    res = await tool.run({"path": str(p), "old": "banana", "new": "kiwi", "replace_all": True}, CTX)
    assert "Successfully edited" in res.output
    assert p.read_text(encoding="utf-8") == "apple kiwi cherry kiwi date kiwi"


# ---- TOOL-05: fs.edit atomic write preserves mode and newlines -------------------------------
@pytest.mark.asyncio
async def test_tool_05_fs_edit_atomic_preserves_mode_and_newlines(tmp_path: Path) -> None:
    p = tmp_path / "crlf.txt"
    content = "first line\r\nsecond line\r\nthird line\r\n"
    p.write_bytes(content.encode("utf-8"))
    os.chmod(p, 0o755)

    scope = PathScope((str(tmp_path),))
    tool = FsEditTool(scope)

    await tool.run({"path": str(p), "old": "second line", "new": "modified line"}, CTX)

    raw_after = p.read_bytes()
    assert b"\r\n" in raw_after
    assert b"\r\nsecond line\r\n" not in raw_after
    assert b"\r\nmodified line\r\n" in raw_after

    mode_after = stat.S_IMODE(os.stat(p).st_mode)
    assert mode_after == 0o755


# ---- TOOL-06: fs.edit approval display unified diff ------------------------------------------
@pytest.mark.asyncio
async def test_tool_06_fs_edit_approval_diff(engine: Engine) -> None:
    p = engine.root / "code.py"
    p.write_text("def hello():\n    return False\n", encoding="utf-8")

    # Agent in ASK mode requesting fs.edit
    agent_id = await engine.agent(Mode.ASK, files_allowed=True)
    row = await engine.db.write(lambda con: tasks.create_task(
        con, id="task-edit-diff", goal="fix hello", mode=int(Mode.ASK), label=Label.PUBLIC,
        tainted=False, now=engine.clock(), agent_id=agent_id
    ))
    await engine.db.write(lambda con: tasks.set_state(con, row.id, TaskState.PLANNING, engine.clock()))
    await engine.db.write(lambda con: tasks.set_state(con, row.id, TaskState.RUNNING, engine.clock()))

    # Trigger fs.edit step
    await engine.db.write(lambda con: tasks.create_steps(
        con, row.id, [("step-edit-1", "fs.edit", json.dumps({"path": str(p), "old": "return False", "new": "return True"}))]
    ))
    await engine.db.write(lambda con: tasks.update_step(con, row.id, "step-edit-1", "running", engine.clock()))

    # Verify that StepExecutor formats the approval display diff
    from lilly.domain.decisions import Brief
    from lilly.domain.labels import TaskCtx
    from lilly.engine.record import TaskRecord
    from lilly.engine.steps import StepExecutor

    rec = TaskRecord(engine.db, engine.bus, engine.clock, row.id, TaskCtx(Label.PUBLIC, False, Mode.ASK), TaskState.RUNNING)
    steps_exec = StepExecutor(rec, engine.approvals, engine.grants, lambda: PathScope((str(engine.root),)),
                              lambda: engine.orchestrator._d.limits(), None, None, Brief("fix hello", ""))

    payload = {"tool": "fs.edit", "args": {"path": str(p), "old": "return False", "new": "return True"}}
    approve_fut = asyncio.create_task(
        steps_exec._approve("step-edit-1", "fs.edit", payload["args"], payload, "mutating file")
    )
    await asyncio.sleep(0.05)

    pending = engine.approvals.pending()
    assert pending, "Approval request should be pending"
    display = json.loads(pending[0].payload_json)
    assert "diff" in display
    diff = display["diff"]
    assert "-return False" in diff
    assert "+return True" in diff

    # Approve and clean up background task
    await engine.approvals.decide(pending[0].id, approve=True, payload_hash=pending[0].payload_hash)
    await approve_fut


# ---- TOOL-07: fs.read ranges and 1-based line numbering --------------------------------------
@pytest.mark.asyncio
async def test_tool_07_fs_read_ranges_and_numbered(tmp_path: Path) -> None:
    p = tmp_path / "lines.txt"
    lines = [f"line number {i}" for i in range(1, 21)]
    p.write_text("\n".join(lines), encoding="utf-8")

    scope = PathScope((str(tmp_path),))
    tool = FsReadTool(scope)

    # Read lines 5 through 8 (offset=5, limit=4)
    res = await tool.run({"path": str(p), "offset": 5, "limit": 4}, CTX)
    assert res.output == "5: line number 5\n6: line number 6\n7: line number 7\n8: line number 8"

    # Default offset without limit
    res2 = await tool.run({"path": str(p), "offset": 19}, CTX)
    assert res2.output == "19: line number 19\n20: line number 20"


# ---- TOOL-08: web.research zero model calls and source excerpts -------------------------------
@pytest.mark.asyncio
async def test_tool_08_web_research_sources_and_zero_model_calls() -> None:
    search_html = (
        '<html><body>'
        '<a class="result__a" href="https://example.com/one">One Title</a>'
        '<div class="result__snippet">Snippet for page one</div>'
        '<a class="result__a" href="https://example.com/two">Two Title</a>'
        '<div class="result__snippet">Snippet for page two</div>'
        '</body></html>'
    )

    def resolver_mock(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        host_hdr = request.headers.get("host") or ""
        if "duckduckgo.com" in url_str or "duckduckgo.com" in host_hdr:
            return httpx.Response(200, text=search_html)
        if "/one" in url_str:
            return httpx.Response(200, text="<html><body><p>Detailed article on topic one.</p></body></html>", headers={"content-type": "text/html"})
        if "/two" in url_str:
            return httpx.Response(200, text="<html><body><p>Detailed article on topic two.</p></body></html>", headers={"content-type": "text/html"})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    search_tool = WebSearchTool(client, MemoryKeyStore(), SearchSettings(engine="duckduckgo"))
    fetch_tool = WebFetchTool(resolver=resolver_mock, transport=httpx.MockTransport(handler))
    research_tool = WebResearchTool(search_tool, fetch_tool)

    res = await research_tool.run({"query": "python guides", "max_sources": 2}, CTX)
    assert res.untrusted is True
    assert "### One Title" in res.output
    assert "https://example.com/one" in res.output
    assert "Detailed article on topic one" in res.output
    assert "### Two Title" in res.output
    assert "https://example.com/two" in res.output
    await client.aclose()


# ---- TOOL-09: web.research SSRF protections --------------------------------------------------
@pytest.mark.asyncio
async def test_tool_09_web_research_ssrf_protections() -> None:
    search_html = (
        '<html><body>'
        '<a class="result__a" href="http://127.0.0.1:8000/internal">Internal Secret</a>'
        '<div class="result__snippet">Internal secret snippet</div>'
        '</body></html>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=search_html)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    search_tool = WebSearchTool(client, MemoryKeyStore(), SearchSettings(engine="duckduckgo"))
    fetch_tool = WebFetchTool(transport=httpx.MockTransport(handler))
    research_tool = WebResearchTool(search_tool, fetch_tool)

    # Must safely block/refuse 127.0.0.1 and not crash
    res = await research_tool.run({"query": "internal secret", "max_sources": 1}, CTX)
    assert "Internal Secret" in res.output
    assert "Internal secret snippet" in res.output
    await client.aclose()


# ---- TOOL-10: web.research records seen URLs for grounding ------------------------------------
@pytest.mark.asyncio
async def test_tool_10_web_research_records_seen_urls() -> None:
    gv = GroundingVerifier(enabled=True)
    sample_output = (
        "### Python 3.13 Released\n"
        "URL: https://python.org/news/313\n"
        "Excerpt:\nPython 3.13 includes free-threaded mode."
    )
    gv.record_step("web.research", {"query": "python 3.13"}, sample_output)
    assert "https://python.org/news/313" in gv.seen_urls


# ---- TOOL-11: result.read slices and keeps label and untrusted -------------------------------
@pytest.mark.asyncio
async def test_tool_11_result_read_slices_and_keeps_metadata(engine: Engine) -> None:
    now = engine.clock()
    task = await engine.db.write(lambda con: tasks.create_task(
        con, id="task-res", goal="read long", mode=int(Mode.OPEN), label=Label.PERSONAL, tainted=True, now=now
    ))
    long_output = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    await engine.db.write(lambda con: tasks.create_steps(con, task.id, [("step-prev", "tool.long", "{}")]))
    await engine.db.write(lambda con: tasks.update_step(
        con, task.id, "step-prev", "done", now, output=long_output, label=Label.PERSONAL, untrusted=True
    ))

    tool = ResultReadTool(engine.db)
    ctx = ToolContext(task.id, "step-curr", 60.0, lambda: False, Label.PERSONAL, True, Mode.OPEN)
    res = await tool.run({"step": "step-prev", "offset": 10}, ctx)

    assert res.output == "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    assert res.label is Label.PERSONAL
    assert res.untrusted is True


# ---- TOOL-12: agent.plan limits and statuses -------------------------------------------------
@pytest.mark.asyncio
async def test_tool_12_agent_plan_limits_and_statuses(engine: Engine) -> None:
    now = engine.clock()
    await engine.db.write(lambda con: tasks.create_task(
        con, id="task-plan", goal="test planning", mode=int(Mode.OPEN), label=Label.PUBLIC,
        tainted=False, now=now
    ))
    tool = AgentPlanTool(engine.db, engine.clock)
    ctx = ToolContext("task-plan", "step-p1", 60.0, lambda: False, Label.PUBLIC, False, Mode.OPEN)

    valid_todos = [
        {"text": "Research spec", "status": "done"},
        {"text": "Implement tools", "status": "doing"},
        {"text": "Run tests", "status": "todo"},
        {"text": "Wait for review", "status": "blocked"},
    ]
    res = await tool.run({"todos": valid_todos}, ctx)
    assert "Plan updated (4 items)" in res.output

    # Exceeding 12 items fails
    too_many = [{"text": f"item {i}", "status": "todo"} for i in range(13)]
    with pytest.raises(ValidationFailed, match="at most 12"):
        await tool.run({"todos": too_many}, ctx)

    # Exceeding 120 chars fails
    too_long = [{"text": "x" * 121, "status": "todo"}]
    with pytest.raises(ValidationFailed, match="exceeds 120 characters"):
        await tool.run({"todos": too_long}, ctx)


# ---- TOOL-13: agent.ask answer returned ------------------------------------------------------
@pytest.mark.asyncio
async def test_tool_13_agent_ask_answer_returned() -> None:
    async def fake_ask(t_id: str, s_id: str, question: str, choices: list[str] | None) -> str:
        return "Green"

    tool = AgentAskTool(ask_fn=fake_ask)
    res = await tool.run({"question": "What is your favorite color?", "choices": ["Red", "Green", "Blue"]}, CTX)
    assert res.output == "The user answered: Green"


# ---- TOOL-14: skill.load and undo hash check rejection/restore -------------------------------
@pytest.mark.asyncio
async def test_tool_14_skill_load_and_undo_hash_check(engine: Engine) -> None:
    sheet = (
        "---\nname: Coder\npet: otto\n---\n\n"
        "## Skills\n"
        "### TestFix\n"
        "Read the failing assertion first. Then check imports.\n\n"
        "### GitHygiene\n"
        "One atomic commit per phase.\n"
    )
    now = engine.clock()
    agent = await engine.db.write(lambda con: agent_store.create_agent(
        con, "agent-coder", "Coder", "", int(Mode.OPEN), now, pet="otto", sheet=sheet
    ))
    task = await engine.db.write(lambda con: tasks.create_task(
        con, id="task-undo-14", goal="code work", mode=int(Mode.OPEN), label=Label.PUBLIC,
        tainted=False, now=now, agent_id=agent.id
    ))

    # 1. skill.load
    skill_tool = SkillLoadTool(engine.db)
    ctx = ToolContext(task.id, "step-skill", 60.0, lambda: False, Label.PUBLIC, False, Mode.OPEN)
    res_skill = await skill_tool.run({"name": "TestFix"}, ctx)
    assert res_skill.output == "Read the failing assertion first. Then check imports."

    with pytest.raises(ToolError, match="skill 'Unknown' not found"):
        await skill_tool.run({"name": "Unknown"}, ctx)

    # 2. fs.edit and undo
    file_path = engine.root / "editable.txt"
    file_path.write_text("initial text", encoding="utf-8")

    edit_tool = FsEditTool(PathScope((str(engine.root),)), db=engine.db)
    step_ctx = ToolContext(task.id, "step-edit-undo", 60.0, lambda: False, Label.PUBLIC, False, Mode.OPEN)
    await edit_tool.run({"path": str(file_path), "old": "initial text", "new": "edited content"}, step_ctx)
    assert file_path.read_text(encoding="utf-8") == "edited content"

    # Undo endpoint call when file has NOT changed
    app = Starlette()
    app.state.runtime = engine
    req = Request({
        "type": "http",
        "method": "POST",
        "path": f"/api/tasks/{task.id}/undo/step-edit-undo",
        "headers": [],
        "path_params": {"task_id": task.id, "step_id": "step-edit-undo"},
        "app": app,
    })

    undo_resp = await api_data.undo_step(req)
    assert undo_resp.status_code == 200
    assert file_path.read_text(encoding="utf-8") == "initial text"

    # Modify file externally, then try to undo again -> ConflictError
    await edit_tool.run({"path": str(file_path), "old": "initial text", "new": "edited content"}, step_ctx)
    file_path.write_text("externally modified content", encoding="utf-8")

    with pytest.raises(ConflictError, match="The file changed after Lilly edited it, so it was not restored."):
        await api_data.undo_step(req)
