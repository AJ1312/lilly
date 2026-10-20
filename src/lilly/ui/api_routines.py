"""Routines: requests that run on a schedule."""

from __future__ import annotations

import sqlite3

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lilly.domain.errors import NotFound, ValidationFailed
from lilly.domain.ids import new_id
from lilly.domain.schedule import parse_schedule
from lilly.domain.tasks import ExecutionTarget
from lilly.store import agents, routines
from lilly.ui.support import flag, json_body, ok, routine_json, runtime, task_json, text, whole


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
    playbook_id = text(data, "playbook_id", required=False, max_len=64) or None
    playbook_version = whole(data, "playbook_version")
    target_raw = data.get("target")
    target = ExecutionTarget.HOST
    if target_raw is not None:
        try:
            target = ExecutionTarget(target_raw.lower() if isinstance(target_raw, str) else target_raw)
        except ValueError:
            raise ValidationFailed(f"unknown execution target: {target_raw}") from None
    sched_raw = data.get("schedule")
    if sched_raw is None and "interval_s" in data:
        sched_raw = {"kind": "every", "every_minutes": max(5, int(data["interval_s"] // 60))}
    schedule, routine_id, now = parse_schedule(sched_raw), new_id(), rt.clock()

    def create(con: sqlite3.Connection) -> routines.RoutineRow:
        _must_exist(con, agent_id)
        return routines.create_routine(
            con,
            routine_id,
            name,
            goal,
            agent_id,
            schedule,
            now,
            playbook_id=playbook_id,
            playbook_version=playbook_version,
            target=target,
        )

    made = await rt.db.write(create)
    rt.routines_changed()
    return JSONResponse({"routine": routine_json(made)}, 201)


async def update_routine(request: Request) -> Response:
    rt = runtime(request)
    routine_id, data = request.path_params["routine_id"], await json_body(request)
    name, goal = text(data, "name", required=False, max_len=80), text(data, "goal", required=False, max_len=4000)
    enabled = flag(data, "enabled")
    sched_raw = data.get("schedule")
    if sched_raw is None and "interval_s" in data:
        sched_raw = {"kind": "every", "every_minutes": max(5, int(data["interval_s"] // 60))}
    schedule = parse_schedule(sched_raw) if ("schedule" in data or "interval_s" in data) else None
    has_agent = "agent_id" in data
    agent_id = text(data, "agent_id", required=False, max_len=64) or None
    playbook_id = text(data, "playbook_id", required=False, max_len=64)
    playbook_version = whole(data, "playbook_version")
    target_raw = data.get("target")
    target = None
    if target_raw is not None:
        try:
            target = ExecutionTarget(target_raw.lower() if isinstance(target_raw, str) else target_raw)
        except ValueError:
            raise ValidationFailed(f"unknown execution target: {target_raw}") from None
    now = rt.clock()

    def update(con: sqlite3.Connection) -> routines.RoutineRow:
        if has_agent:
            _must_exist(con, agent_id)
        row = routines.update_routine(
            con,
            routine_id,
            now,
            name=name,
            goal=goal,
            agent_id=agent_id,
            clear_agent=has_agent and agent_id is None,
            schedule=schedule,
            playbook_id=playbook_id,
            playbook_version=playbook_version,
            target=target,
        )
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
