"""What Lilly remembers and what the user writes: memory, spaces and notes, agents."""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lilly.app.runtime import Runtime
from lilly.domain.errors import NotFound, ValidationFailed
from lilly.domain.ids import new_id
from lilly.domain.labels import Label
from lilly.domain.pets import DEFAULT_LOOK, Look, look_to_dict, parse_look
from lilly.domain.sheet import parse_sheet
from lilly.engine.crew import choose_pet
from lilly.engine.orchestrator import AGENT_CHANGED, AGENT_DELETED
from lilly.store import agents, memory, spaces
from lilly.ui.support import (
    flag,
    json_body,
    limit_param,
    memory_json,
    ok,
    page_json,
    runtime,
    space_json,
    text,
    whole,
)


def _memory_id(request: Request) -> int:
    raw = request.path_params["memory_id"]
    if not raw.isdigit():
        raise NotFound(raw)
    return int(raw)


def _label(data: dict[str, Any]) -> Label | None:
    raw = data.get("label")
    if raw is None:
        return None
    if raw not in ("PUBLIC", "PERSONAL"):
        raise ValidationFailed("label must be PUBLIC or PERSONAL")
    return Label[raw]


# ---- memory ------------------------------------------------------------------------------------
async def list_memory(request: Request) -> Response:
    rt = runtime(request)
    query = request.query_params.get("q", "").strip()
    rows = (memory.search_memory(rt.db.reader, query, limit=limit_param(request, 50)) if query
            else memory.list_memory(rt.db.reader, limit_param(request, 200, 1000)))
    return JSONResponse({"memory": [memory_json(m) for m in rows]})


async def add_memory(request: Request) -> Response:
    rt = runtime(request)
    data = await json_body(request)
    body, label, now = text(data, "text") or "", _label(data) or Label.PERSONAL, rt.clock()
    row = await rt.db.write(lambda con: memory.add_memory(con, body, now, label=label, source="user"))
    return JSONResponse({"memory": memory_json(row)}, 201)


async def update_memory(request: Request) -> Response:
    rt = runtime(request)
    data = await json_body(request)
    memory_id, body, label = _memory_id(request), text(data, "text", required=False), _label(data)
    row = await rt.db.write(lambda con: memory.update_memory(con, memory_id, text=body, label=label))
    return JSONResponse({"memory": memory_json(row)})


async def delete_memory(request: Request) -> Response:
    rt = runtime(request)
    memory_id = _memory_id(request)
    await rt.db.write(lambda con: memory.delete_memory(con, memory_id))
    return ok()


async def clear_memory(request: Request) -> Response:
    """Forget everything Lilly remembers. The request must say so explicitly."""
    rt = runtime(request)
    if (await json_body(request)).get("confirm") != "forget everything":
        raise ValidationFailed('send {"confirm": "forget everything"} to clear all memory')

    def wipe(con: Any) -> int:
        return int(con.execute("DELETE FROM memory").rowcount)

    return ok(removed=await rt.db.write(wipe))


# ---- spaces and notes --------------------------------------------------------------------------
async def list_spaces(request: Request) -> Response:
    return JSONResponse({"spaces": [space_json(s) for s in spaces.list_spaces(runtime(request).db.reader)]})


async def create_space(request: Request) -> Response:
    rt = runtime(request)
    data = await json_body(request)
    name, description, now, space_id = text(data, "name", max_len=80) or "", text(
        data, "description", required=False, max_len=1000) or "", rt.clock(), new_id()
    row = await rt.db.write(lambda con: spaces.create_space(con, space_id, name, description, now))
    return JSONResponse({"space": space_json(row)}, 201)


async def update_space(request: Request) -> Response:
    rt = runtime(request)
    data = await json_body(request)
    space_id, name, description = (request.path_params["space_id"], text(data, "name", required=False, max_len=80),
                                   text(data, "description", required=False, max_len=1000))
    row = await rt.db.write(lambda con: spaces.update_space(con, space_id, name=name, description=description))
    return JSONResponse({"space": space_json(row)})


async def delete_space(request: Request) -> Response:
    rt = runtime(request)
    space_id = request.path_params["space_id"]
    await rt.db.write(lambda con: spaces.delete_space(con, space_id))
    return ok()


async def list_pages(request: Request) -> Response:
    rt = runtime(request)
    space_id = request.path_params["space_id"]
    if spaces.get_space(rt.db.reader, space_id) is None:
        raise NotFound(space_id)
    query = request.query_params.get("q", "").strip()
    rows = (spaces.search_pages(rt.db.reader, query, space_id=space_id) if query
            else spaces.list_pages(rt.db.reader, space_id))
    return JSONResponse({"pages": [page_json(p, with_content=False) for p in rows]})


async def search_all_pages(request: Request) -> Response:
    query = request.query_params.get("q", "").strip()
    rows = spaces.search_pages(runtime(request).db.reader, query) if query else []
    return JSONResponse({"pages": [page_json(p, with_content=False) for p in rows]})


async def create_page(request: Request) -> Response:
    rt = runtime(request)
    data = await json_body(request)
    space_id, title, content = (request.path_params["space_id"], text(data, "title", max_len=200) or "",
                                text(data, "content", required=False, max_len=spaces.MAX_CONTENT) or "")
    now, page_id = rt.clock(), new_id()
    row = await rt.db.write(lambda con: spaces.create_page(con, page_id, space_id, title, content, now))
    return JSONResponse({"page": page_json(row)}, 201)


async def get_page(request: Request) -> Response:
    row = spaces.get_page(runtime(request).db.reader, request.path_params["space_id"], request.path_params["page_id"])
    if row is None:
        raise NotFound(request.path_params["page_id"])
    return JSONResponse({"page": page_json(row)})


async def update_page(request: Request) -> Response:
    rt = runtime(request)
    data = await json_body(request)
    space_id, page_id = request.path_params["space_id"], request.path_params["page_id"]
    revision = whole(data, "revision")
    if revision is None:
        raise ValidationFailed("revision is required, so a stale edit cannot overwrite a newer one")
    title, content, now = (text(data, "title", required=False, max_len=200),
                           text(data, "content", required=False, max_len=spaces.MAX_CONTENT), rt.clock())
    row = await rt.db.write(lambda con: spaces.update_page(con, space_id, page_id, revision, now,
                                                           title=title, content=content))
    return JSONResponse({"page": page_json(row)})


async def delete_page(request: Request) -> Response:
    rt = runtime(request)
    space_id, page_id = request.path_params["space_id"], request.path_params["page_id"]
    await rt.db.write(lambda con: spaces.delete_page(con, space_id, page_id))
    return ok()


# ---- agents ------------------------------------------------------------------------------------
def _agent_json(a: agents.AgentRow) -> dict[str, Any]:
    return {
        "id": a.id, "name": a.name, "instructions": a.instructions, "mode": a.mode,
        "research_allowed": a.research_allowed, "memory_allowed": a.memory_allowed,
        "files_allowed": a.files_allowed, "computer_allowed": a.computer_allowed, "pet": a.pet,
        "chat_allowed": a.chat_allowed, "look": look_to_dict(a.look), "skills": a.skills, "model": a.model,
        "space_id": a.space_id, "created_at": a.created_at,
        "sheet": a.sheet, "sheet_json": a.sheet_json, "parent_template": a.parent_template,
    }


def _look(data: dict[str, Any]) -> Look | None:
    """The look in a request, or None when it carries none. A look sent on an update replaces the whole look."""
    raw = data.get("look")
    return None if raw is None else parse_look(raw)


def _model(rt: Runtime, data: dict[str, Any]) -> str | None:
    """A model the pet always uses: "" (automatic routing) or the name of a configured model."""
    name = text(data, "model", required=False, max_len=agents.MAX_MODEL)
    if name and name not in {m.name for m in rt.settings.models}:
        raise ValidationFailed("model must be empty or one of the configured models")
    return name


async def list_agents(request: Request) -> Response:
    return JSONResponse({"agents": [_agent_json(a) for a in agents.list_agents(runtime(request).db.reader)]})


async def create_agent(request: Request) -> Response:
    rt = runtime(request)
    data = await json_body(request)
    name, instructions, mode = (text(data, "name", max_len=80) or "",
                                text(data, "instructions", required=False) or "", whole(data, "mode"))
    research, mem, files = flag(data, "research_allowed"), flag(data, "memory_allowed"), flag(data, "files_allowed")
    skills, model, look = text(data, "skills", required=False, max_len=agents.MAX_SKILLS), _model(rt, data), _look(data)
    sheet = text(data, "sheet", required=False) or ""
    parent_template = text(data, "parent_template", required=False, max_len=40) or ""
    now, agent_id = rt.clock(), new_id()
    row = await rt.db.write(lambda con: agents.create_agent(
        con, agent_id, name, instructions, 1 if mode is None else mode, now,
        research_allowed=True if research is None else research,
        memory_allowed=True if mem is None else mem, files_allowed=bool(files),
        computer_allowed=bool(flag(data, "computer_allowed")), chat_allowed=bool(flag(data, "chat_allowed")), pet=text(data, "pet", required=False, max_len=20) or "lily",
        skills=skills or "", model=model or "", look=look or DEFAULT_LOOK,
        sheet=sheet, parent_template=parent_template))
    return JSONResponse({"agent": _agent_json(row)}, 201)


async def update_agent(request: Request) -> Response:
    rt = runtime(request)
    data = await json_body(request)
    agent_id = request.path_params["agent_id"]
    name, instructions, mode = (text(data, "name", required=False, max_len=80),
                                text(data, "instructions", required=False), whole(data, "mode"))
    research, mem, files = flag(data, "research_allowed"), flag(data, "memory_allowed"), flag(data, "files_allowed")
    skills, model, look = text(data, "skills", required=False, max_len=agents.MAX_SKILLS), _model(rt, data), _look(data)
    sheet = text(data, "sheet", required=False)
    parent_template = text(data, "parent_template", required=False, max_len=40)

    def change(con: Any) -> tuple[agents.AgentRow | None, agents.AgentRow]:
        before = agents.get_agent(con, agent_id)
        return before, agents.update_agent(
            con, agent_id, name=name, instructions=instructions, mode=mode, research_allowed=research,
            memory_allowed=mem, files_allowed=files, computer_allowed=flag(data, "computer_allowed"), chat_allowed=flag(data, "chat_allowed"),
            pet=text(data, "pet", required=False, max_len=20),
            skills=skills, model=model, look=look,
            sheet=sheet, parent_template=parent_template)

    before, row = await rt.db.write(change)
    if before is not None and agents.narrows(before, row):   # what a running task was started with no longer holds
        await rt.orchestrator.cancel_agent_tasks(agent_id, AGENT_CHANGED)
    return JSONResponse({"agent": _agent_json(row)})


async def delete_agent(request: Request) -> Response:
    rt = runtime(request)
    agent_id = request.path_params["agent_id"]
    await rt.db.write(lambda con: agents.delete_agent(con, agent_id))
    await rt.orchestrator.cancel_agent_tasks(agent_id, AGENT_DELETED)
    return ok()


async def validate_sheet(request: Request) -> Response:
    data = await json_body(request)
    sheet_text = text(data, "sheet", required=False) or ""
    parsed, diags = parse_sheet(sheet_text)
    is_ok = not any(d.severity == "error" for d in diags)
    return JSONResponse({
        "ok": is_ok,
        "diagnostics": [d.to_dict() for d in diags],
        "parsed": parsed.to_dict() if parsed else None,
    })


async def prompt_preview(request: Request) -> Response:
    rt = runtime(request)
    agent_id = request.path_params["agent_id"]
    agent = agents.get_agent(rt.db.reader, agent_id)
    if agent is None:
        raise NotFound(f"agent {agent_id}")
    return JSONResponse({
        "persona": agents.owner_text_for(agent, role=None),
        "plan": agents.owner_text_for(agent, role="plan"),
        "act": agents.owner_text_for(agent, role="act"),
        "write": agents.owner_text_for(agent, role="write"),
        "check": agents.owner_text_for(agent, role="check"),
    })


async def export_agent(request: Request) -> Response:
    rt = runtime(request)
    agent_id = request.path_params["agent_id"]
    agent = agents.get_agent(rt.db.reader, agent_id)
    if agent is None:
        raise NotFound(f"agent {agent_id}")
    sheet_text = agent.sheet
    if not sheet_text:
        sheet_text = f"---\nname: {agent.name}\npet: {agent.pet}\n---\n\n## Persona\n{agent.instructions}"

    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/markdown" not in accept:
        return JSONResponse({"sheet": sheet_text, "agent": _agent_json(agent)})
    return Response(
        content=sheet_text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{agent.name}.md"'},
    )


async def import_agent(request: Request) -> Response:
    rt = runtime(request)
    content_type = request.headers.get("content-type", "")
    sheet_text = ""
    if "application/json" in content_type:
        data = await json_body(request)
        sheet_text = text(data, "sheet", required=False) or ""
    else:
        raw_body = await request.body()
        sheet_text = raw_body.decode("utf-8")

    if not sheet_text.strip():
        raise ValidationFailed("sheet is required for import")

    parsed, diags = parse_sheet(sheet_text)
    if any(d.severity == "error" for d in diags):
        first_err = next(d for d in diags if d.severity == "error")
        raise ValidationFailed(f"invalid sheet: {first_err.message}")

    assert parsed is not None
    now, agent_id = rt.clock(), new_id()
    # Import rule (CREW-13): create pet with EVERY permission off
    row = await rt.db.write(lambda con: agents.create_agent(
        con,
        agent_id,
        parsed.name,
        "",
        0,
        now,
        research_allowed=False,
        memory_allowed=False,
        files_allowed=False,
        computer_allowed=False,
        chat_allowed=False,
        pet=parsed.pet,
        skills="",
        model="",
        look=DEFAULT_LOOK,
        sheet=sheet_text,
    ))
    return JSONResponse({"agent": _agent_json(row)}, 201)


async def crew_route(request: Request) -> Response:
    rt = runtime(request)
    data = await json_body(request)
    goal = text(data, "goal", max_len=4000) or ""
    all_pets = agents.list_agents(rt.db.reader)
    route_res = await choose_pet(goal, all_pets, rt.decisions)
    return JSONResponse(route_res.to_dict())
