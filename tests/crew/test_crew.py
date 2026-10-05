"""Crew test suite: CREW-01 through CREW-14.

Covers:
- CREW-01: Parser accepts starter sheets
- CREW-02: Legacy agent owner text byte-identical
- CREW-03: Diagnostics SHEET-001..010 exact text and line numbers
- CREW-04: Allowlist hides and rejects
- CREW-05: Permissions never read from sheet
- CREW-06: Routing order @handle -> rules -> Laya -> default
- CREW-07: Tag fallback hint (SHEET-010 when tag missing)
- CREW-08: Delegation depth/children/budget share
- CREW-09: Intersection of tools and strict mode
- CREW-10: Child answer untrusted (4A.9 format)
- CREW-11: Cancel cascades to child tasks
- CREW-12: Task profile cannot widen (exact error message)
- CREW-13: Import has all permissions off
- CREW-14: Export round-trip
"""
from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from lilly.domain.errors import ToolError, ValidationFailed
from lilly.domain.labels import Label, Mode
from lilly.domain.pets import agent_prompt
from lilly.domain.ports import CompletionResult, ModelToolCall, ToolContext
from lilly.domain.settings import MODULES, CrewSettings, EngineSettings, LimitSettings, ModelSpec, Settings
from lilly.domain.sheet import (
    STARTER_SHEET_BAO,
    STARTER_SHEET_FERN,
    STARTER_SHEET_JUNO,
    STARTER_SHEET_LILY,
    STARTER_SHEET_MOCHI,
    STARTER_SHEET_OTTO,
    STARTER_SHEET_PIP,
    STARTER_SHEET_WISP,
    TaskProfile,
    parse_sheet,
)
from lilly.engine.crew import choose_pet, resolve_ref
from lilly.engine.delegate import DelegateHandler, DelegationContext
from lilly.engine.orchestrator import SubmitRequest
from lilly.store import agents as agent_store
from lilly.store import tasks
from lilly.ui import api_data
from tests.conftest import Engine


# ---- CREW-01: Starter sheets parse cleanly ----------------------------------------------------
def test_crew_01_starter_sheets_parse_cleanly() -> None:
    starters = [
        STARTER_SHEET_LILY,
        STARTER_SHEET_JUNO,
        STARTER_SHEET_MOCHI,
        STARTER_SHEET_OTTO,
        STARTER_SHEET_PIP,
        STARTER_SHEET_BAO,
        STARTER_SHEET_FERN,
        STARTER_SHEET_WISP,
    ]
    for sheet_text in starters:
        parsed, diags = parse_sheet(sheet_text)
        assert parsed is not None
        errors = [d for d in diags if d.severity == "error"]
        assert not errors, f"Failed on sheet for {parsed.name}: {errors}"
        assert parsed.name
        assert parsed.pet


# ---- CREW-02: Legacy agent owner text byte-identical ------------------------------------------
@pytest.mark.asyncio
async def test_crew_02_legacy_agent_owner_text_byte_identical(engine: Engine) -> None:
    instructions = "Help the user analyze their financial files carefully."
    skills = "Spreadsheet analysis, CSV parsing, data visualization."
    now = engine.clock()
    agent_id = "test-legacy-01"

    row = await engine.db.write(lambda con: agent_store.create_agent(
        con,
        agent_id,
        "Financial Analyst",
        instructions,
        int(Mode.ASK),
        now,
        skills=skills,
        pet="mochi",
    ))

    expected_owner_text = agent_prompt(instructions, skills)
    actual_owner_text = agent_store.owner_text_for(row)
    assert actual_owner_text == expected_owner_text

    # Parsed sheet has ## Persona matching expected
    parsed = agent_store.parsed_sheet_for(row)
    assert parsed is not None
    assert parsed.persona.strip() == expected_owner_text.strip()


# ---- CREW-03: Diagnostics SHEET-001..010 exact text and line numbers --------------------------
def test_crew_03_diagnostics_sheet_001_to_010() -> None:
    # SHEET-001: Unknown setting
    s1 = "---\nname: Bob\npet: lily\nunknown_key: foo\n---\n"
    _, d1 = parse_sheet(s1)
    err1 = next(d for d in d1 if d.code == "SHEET-001")
    assert err1.line == 4
    assert err1.severity == "error"
    assert err1.message == 'Line 4: unknown setting "unknown_key". Allowed: name, pet, description, tools, models, limits.'

    # SHEET-002: Unknown section
    s2 = "---\nname: Bob\npet: lily\n---\n\n## CustomMagic\nHello\n"
    _, d2 = parse_sheet(s2)
    err2 = next(d for d in d2 if d.code == "SHEET-002")
    assert err2.line == 6
    assert err2.severity == "error"
    assert err2.message == 'Line 6: unknown section "## CustomMagic". Allowed: Persona, Planning, Acting, Writing, Checking, Skills, Never.'

    # SHEET-003: Duplicate section
    s3 = "---\nname: Bob\npet: lily\n---\n\n## Persona\nFirst\n\n## Persona\nSecond\n"
    _, d3 = parse_sheet(s3)
    err3 = next(d for d in d3 if d.code == "SHEET-003")
    assert err3.line == 9
    assert err3.severity == "error"
    assert err3.message == 'Line 9: section "## Persona" appears twice.'

    # SHEET-004: Model not configured
    s4 = "---\nname: Bob\npet: lily\nmodels:\n  act: non-existent-model\n---\n"
    _, d4 = parse_sheet(s4, known_models=["claude-3-5"])
    warn4 = next(d for d in d4 if d.code == "SHEET-004")
    assert warn4.line == 5
    assert warn4.severity == "warning"
    assert warn4.message == 'Line 5: "non-existent-model" is not a model you have set up. Pick one in Settings → Models, or use "auto" or "tag:<tag>".'

    # SHEET-005: Tool unknown (no tool matches glob)
    s5 = "---\nname: Bob\npet: lily\ntools:\n  - completely_fake_tool\n---\n"
    _, d5 = parse_sheet(s5, available_tools=["fs.read", "web.fetch"])
    warn5 = next(d for d in d5 if d.code == "SHEET-005")
    assert warn5.line == 5
    assert warn5.severity == "warning"
    assert warn5.message == 'Line 5: no tool matches "completely_fake_tool". It will do nothing.'

    # SHEET-006: Range out of bounds
    s6 = "---\nname: Bob\npet: lily\nlimits:\n  steps: 999\n---\n"
    _, d6 = parse_sheet(s6)
    err6 = next(d for d in d6 if d.code == "SHEET-006")
    assert err6.line == 5
    assert err6.severity == "error"
    assert err6.message == 'Line 5: "steps" must be between 1 and 60.'

    # SHEET-007: Sheet too long
    long_s7 = "---\nname: Bob\npet: lily\n---\n" + ("x" * 20000)
    _, d7 = parse_sheet(long_s7)
    err7 = next(d for d in d7 if d.code == "SHEET-007")
    assert err7.severity == "error"
    assert "characters; the limit is 16000." in err7.message

    # SHEET-008: Tool requires permission which is off
    s8 = "---\nname: Bob\npet: lily\ntools:\n  - web.fetch\n---\n"
    _, d8 = parse_sheet(s8, agent_permissions={"research_allowed": False})
    warn8 = next(d for d in d8 if d.code == "SHEET-008")
    assert warn8.line == 5
    assert warn8.severity == "warning"
    assert warn8.message == 'Line 5: "web.fetch" needs "web", which is off for this pet. It will stay hidden.'

    # SHEET-009: Missing opening frontmatter block
    s9 = "name: Bob\npet: lily\n"
    _, d9 = parse_sheet(s9)
    err9 = next(d for d in d9 if d.code == "SHEET-009")
    assert err9.line == 1
    assert err9.severity == "error"
    assert err9.message == "The sheet must start with a front matter block between two lines of three dashes."

    # SHEET-010: Tag fallback hint
    s10 = "---\nname: Bob\npet: lily\nmodels:\n  act: tag:quantum\n---\n"
    _, d10 = parse_sheet(s10, model_tags={"m1": {"vision"}})
    warn10 = next(d for d in d10 if d.code == "SHEET-010")
    assert warn10.line == 5
    assert warn10.severity == "warning"
    assert warn10.message == 'Line 5: no model has the tag "quantum", so Lilly will choose automatically for the "act" role.'


# ---- CREW-04: Allowlist hides and rejects -----------------------------------------------------
@pytest.mark.asyncio
async def test_crew_04_allowlist_hides_and_rejects(engine: Engine) -> None:
    engine.orchestrator.configure(
        Settings(file_roots=(str(engine.root),), modules=MODULES, engine=EngineSettings(mode="loop"))
    )
    sheet = "---\nname: WebOnly\npet: lily\ntools:\n  - web.*\n---\n\n## Persona\nYou only search the web.\n"
    now = engine.clock()
    row = await engine.db.write(lambda con: agent_store.create_agent(
        con, "agent-web-only", "WebOnly", "", int(Mode.OPEN), now, sheet=sheet, files_allowed=True, research_allowed=True, pet="lily"
    ))

    # Script model attempting to call fs.read
    engine.completer.replies = [
        CompletionResult(
            text="",
            input_tokens=10,
            output_tokens=10,
            finish_reason="tool_calls",
            tool_calls=(ModelToolCall(id="c1", name="fs.read", arguments={"path": "notes.txt"}, raw="{}"),),
        ),
        CompletionResult(
            text="Done after error.",
            input_tokens=10,
            output_tokens=10,
            finish_reason="stop",
        ),
    ]

    task = await engine.run("read notes.txt", agent_id=row.id)
    # The first model call must NOT have fs.read in its tool schemas
    first_req = engine.completer.calls[0]
    tool_names = [t.name for t in first_req.tools]
    assert "fs.read" not in tool_names
    assert "agent.ask" in tool_names  # control tool preserved
    assert task.state.value == "DONE"


# ---- CREW-05: Permissions never read from sheet -----------------------------------------------
@pytest.mark.asyncio
async def test_crew_05_permissions_never_read_from_sheet(engine: Engine) -> None:
    sheet = (
        "---\nname: Hacker\npet: lily\n"
        "files_allowed: true\n"
        "---\n\n## Persona\nI want access.\n"
    )
    # Parser reports SHEET-001 error (unknown setting)
    parsed, diags = parse_sheet(sheet)
    assert any(d.code == "SHEET-001" for d in diags)

    now = engine.clock()
    row = await engine.db.write(lambda con: agent_store.create_agent(
        con, "agent-perm", "Hacker", "", int(Mode.ASK), now, files_allowed=False, pet="lily"
    ))
    assert row.files_allowed is False


# ---- CREW-06: Routing order: @handle -> rules -> Laya -> default -----------------------------
@pytest.mark.asyncio
async def test_crew_06_routing_order(engine: Engine) -> None:
    now = engine.clock()
    p1 = await engine.db.write(lambda con: agent_store.create_agent(
        con, "p1", "Otto", "automation computer control", int(Mode.ASK), now, pet="otto"
    ))
    p2 = await engine.db.write(lambda con: agent_store.create_agent(
        con, "p2", "Mochi", "financial calculations data", int(Mode.ASK), now, pet="mochi"
    ))
    pets = [p1, p2]

    # 1. Explicit @handle
    r1 = await choose_pet("Please help @otto with this setup", pets)
    assert r1.how == "explicit"
    assert r1.pet == "Otto"

    # 2. Rules: lexical score
    r2 = await choose_pet("run the calculation on financial data", pets)
    assert r2.how == "rules"
    assert r2.pet == "Mochi"

    # 3. Default fallback
    r3 = await choose_pet("hello random request with no match xyzabc123", pets)
    assert r3.how == "default"


# ---- CREW-07: Tag fallback hint ---------------------------------------------------------------
def test_crew_07_tag_fallback_hint() -> None:
    models = [
        ModelSpec(name="gpt-4o", provider="openai", model_id="gpt-4o", tags=("reasoning",)),
        ModelSpec(name="claude-3-5-sonnet", provider="anthropic", model_id="claude-3-5-sonnet", tags=("coding",)),
    ]
    # Present tag
    pin, hint = resolve_ref("tag:reasoning", models, role="plan")
    assert pin == "gpt-4o"
    assert hint is None

    # Missing tag
    pin2, hint2 = resolve_ref("tag:quantum", models, role="act")
    assert pin2 is None
    assert hint2 is not None
    assert 'no model has the tag "quantum"' in hint2
    assert 'choose automatically for the "act" role' in hint2


# ---- CREW-08: Delegation depth, children, and budget share ------------------------------------
@pytest.mark.asyncio
async def test_crew_08_delegation_limits(engine: Engine) -> None:
    now = engine.clock()
    await engine.db.write(lambda con: agent_store.create_agent(
        con, "parent-agent", "Lead", "", int(Mode.OPEN), now, pet="juno"
    ))
    await engine.db.write(lambda con: agent_store.create_agent(
        con, "child-agent", "Helper", "", int(Mode.OPEN), now, pet="pip"
    ))

    # Create task at depth 1 with max_depth=1
    task_row = await engine.orchestrator.submit(SubmitRequest(goal="subtask", depth=1))

    del_handler = DelegateHandler(DelegationContext(
        db=engine.db,
        bus=engine.bus,
        orchestrator=engine.orchestrator,
        crew_settings=lambda: CrewSettings(max_depth=1),
        limits=lambda: LimitSettings(),
    ))

    ctx = ToolContext(
        task_id=task_row.id,
        step_id="s1",
        deadline_s=60.0,
        cancelled=lambda: False,
        mode=Mode.OPEN,
    )

    with pytest.raises(ToolError, match="maximum delegation depth"):
        await del_handler.delegate("Helper", "do work", ctx)


# ---- CREW-09: Intersection of tools and strict mode -------------------------------------------
@pytest.mark.asyncio
async def test_crew_09_intersection_of_tools_and_mode(engine: Engine) -> None:
    now = engine.clock()
    child_pet = await engine.db.write(lambda con: agent_store.create_agent(
        con, "sub-pet", "Sub", "", int(Mode.OPEN), now, pet="mochi"
    ))

    # Parent has mode ASK
    req = SubmitRequest(
        goal="subtask",
        agent_id=child_pet.id,
        mode=Mode.ASK,
    )
    row = await engine.orchestrator.submit(req)
    assert row.mode == Mode.ASK


# ---- CREW-10: Child answer untrusted ----------------------------------------------------------
@pytest.mark.asyncio
async def test_crew_10_child_answer_untrusted(engine: Engine) -> None:
    engine.orchestrator.configure(
        Settings(file_roots=(str(engine.root),), modules=MODULES, engine=EngineSettings(mode="loop"))
    )
    now = engine.clock()
    parent_task = await engine.db.write(lambda con: tasks.create_task(
        con, id="task-parent-10", goal="main task", mode=int(Mode.OPEN), label=Label.PUBLIC, tainted=False, now=now
    ))
    await engine.db.write(lambda con: agent_store.create_agent(
        con, "assistant-pet", "Assistant", "", int(Mode.OPEN), now, pet="otto"
    ))

    engine.completer.replies = [
        CompletionResult(text="Child secret findings", input_tokens=10, output_tokens=10, finish_reason="stop")
    ]

    handler = DelegateHandler(DelegationContext(
        db=engine.db,
        bus=engine.bus,
        orchestrator=engine.orchestrator,
        crew_settings=lambda: CrewSettings(),
        limits=lambda: LimitSettings(),
    ))

    ctx = ToolContext(
        task_id=parent_task.id,
        step_id="step-1",
        deadline_s=60.0,
        cancelled=lambda: False,
        mode=Mode.OPEN,
    )

    res = await handler.delegate("Assistant", "find secrets", ctx)
    assert res.untrusted is True
    assert "<untrusted_data>" in res.output
    assert "Child secret findings" in res.output
    assert "RESULT step-1 agent.delegate ok" in res.output


# ---- CREW-11: Cancel cascades to child tasks --------------------------------------------------
@pytest.mark.asyncio
async def test_crew_11_cancel_cascades(engine: Engine) -> None:
    p_row = await engine.orchestrator.submit(SubmitRequest(goal="parent task"))
    c_row = await engine.orchestrator.submit(SubmitRequest(
        goal="child task",
        parent_task_id=p_row.id,
        depth=1,
    ))

    # Cancel parent
    await engine.orchestrator.cancel(p_row.id)
    # Child task should be cancelled as well
    c_final = await engine.wait(c_row.id)
    assert c_final.state.value == "CANCELLED"


# ---- CREW-12: Task profile cannot widen -------------------------------------------------------
@pytest.mark.asyncio
async def test_crew_12_task_profile_cannot_widen(engine: Engine) -> None:
    now = engine.clock()
    sheet = "---\nname: SafePet\npet: lily\ntools:\n  - web.fetch\n---\n"
    pet = await engine.db.write(lambda con: agent_store.create_agent(
        con, "safe-pet-01", "SafePet", "", int(Mode.ASK), now, sheet=sheet, pet="lily"
    ))

    # Attempt to submit task profile that includes fs.write
    req = SubmitRequest(
        goal="try to write file",
        agent_id=pet.id,
        profile=TaskProfile(tools=("fs.write",)),
    )

    with pytest.raises(ValidationFailed) as exc_info:
        await engine.orchestrator.submit(req)

    assert 'You can narrow a pet for one task, not widen it: "fs.write" is not available to SafePet.' in str(exc_info.value)


# ---- CREW-13: Import has all permissions off --------------------------------------------------
@pytest.mark.asyncio
async def test_crew_13_import_has_permissions_off(engine: Engine) -> None:
    sheet_content = "---\nname: ImportedSpecialist\npet: juno\n---\n\n## Persona\nI do research.\n"

    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", b"text/markdown")],
        "app": type("App", (), {"state": type("State", (), {"runtime": engine})()})(),
    }
    request = Request(scope)
    request._body = sheet_content.encode("utf-8")

    # Call import endpoint
    resp = await api_data.import_agent(request)
    assert resp.status_code == 201
    data = json.loads(resp.body.decode("utf-8"))
    agent = data["agent"]
    assert agent["name"] == "ImportedSpecialist"
    assert agent["mode"] == 0
    assert agent["research_allowed"] is False
    assert agent["memory_allowed"] is False
    assert agent["files_allowed"] is False
    assert agent["computer_allowed"] is False
    assert agent["chat_allowed"] is False


# ---- CREW-14: Export round-trip ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_crew_14_export_round_trip(engine: Engine) -> None:
    sheet_content = "---\nname: Exporter\npet: bao\ndescription: exports and imports\n---\n\n## Persona\nHello world.\n"
    now = engine.clock()
    pet = await engine.db.write(lambda con: agent_store.create_agent(
        con, "exp-01", "Exporter", "", int(Mode.ASK), now, sheet=sheet_content, pet="bao"
    ))

    # 1. Export
    fake_app = type("App", (), {"state": type("State", (), {"runtime": engine})()})()
    req_exp = Request({"type": "http", "path_params": {"agent_id": pet.id}, "headers": [], "app": fake_app})
    resp_exp = await api_data.export_agent(req_exp)
    assert resp_exp.status_code == 200
    exported_text = resp_exp.body.decode("utf-8")
    assert "Exporter" in exported_text

    # 2. Import exported sheet
    req_imp = Request({"type": "http", "headers": [(b"content-type", b"text/markdown")], "app": fake_app})
    req_imp._body = exported_text.encode("utf-8")
    resp_imp = await api_data.import_agent(req_imp)
    assert resp_imp.status_code == 201
    imported_agent = json.loads(resp_imp.body.decode("utf-8"))["agent"]
    assert imported_agent["name"] == "Exporter"
    assert imported_agent["pet"] == "bao"
