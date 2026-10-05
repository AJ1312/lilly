"""Routines: requests that run on a schedule."""
from __future__ import annotations

import sqlite3

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lilly.domain.errors import NotFound
from lilly.domain.ids import new_id
from lilly.domain.schedule import parse_schedule
from lilly.store import agents, routines
from lilly.ui.support import flag, json_body, ok, routine_json, runtime, task_json, text


def _must_exist(con: sqlite3.Connection, agent_id: str | None) -> None:
    if agent_id is not None and agents.get_agent(con, agent_id) is None:
        raise NotFound(f"agent {agent_id}")


async def list_routines(request: Request) -> Response:
    rows = routines.list_routines(runtime(request).db.reader)
    return JSONResponse({"routines": [routine_json(r) for r in rows]})


async def create_routine(request: Request) -> Response:
    rt = runtime(request)
    data = await json_body(request)
    name, goal = text(data, "name", max_len=80) or "", text(data, "goal", max_len=4000) or ""
    agent_id = text(data, "agent_id", required=False, max_len=64) or None
    schedule, routine_id, now = parse_schedule(data.get("schedule")), new_id(), rt.clock()

    def create(con: sqlite3.Connection) -> routines.RoutineRow:
        _must_exist(con, agent_id)
        return routines.create_routine(con, routine_id, name, goal, agent_id, schedule, now)

    made = await rt.db.write(create)
    rt.routines_changed()
    return JSONResponse({"routine": routine_json(made)}, 201)


async def update_routine(request: Request) -> Response:
    rt = runtime(request)
    routine_id, data = request.path_params["routine_id"], await json_body(request)
    name, goal = text(data, "name", required=False, max_len=80), text(data, "goal", required=False, max_len=4000)
    enabled = flag(data, "enabled")
    schedule = parse_schedule(data["schedule"]) if "schedule" in data else None
    has_agent = "agent_id" in data
    agent_id = text(data, "agent_id", required=False, max_len=64) or None
    now = rt.clock()

    def update(con: sqlite3.Connection) -> routines.RoutineRow:
        if has_agent:
            _must_exist(con, agent_id)
        row = routines.update_routine(con, routine_id, now, name=name, goal=goal, agent_id=agent_id,
                                      clear_agent=has_agent and agent_id is None, schedule=schedule)
        if enabled is not None and enabled != row.enabled:
            row = routines.set_enabled(con, routine_id, enabled, now)
        return row

    changed = await rt.db.write(update)
    rt.routines_changed()
    return JSONResponse({"routine": routine_json(changed)})


async def delete_routine(request: Request) -> Response:
    routine_id = request.path_params["routine_id"]
    rt = runtime(request)
    await rt.db.write(lambda con: routines.delete_routine(con, routine_id))
    rt.routines_changed()
    return ok()


async def run_routine(request: Request) -> Response:
    task = await runtime(request).scheduler.run_now(request.path_params["routine_id"])
    return JSONResponse({"task": task_json(task)}, 202)
