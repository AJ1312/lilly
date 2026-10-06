"""Conversations, tasks, approvals, the kill switch and the live event stream."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from lilly.domain.decisions import DRIFTS, FOLLOWS
from lilly.domain.errors import NotFound, ValidationFailed
from lilly.domain.sheet import TaskProfile
from lilly.domain.skills import BUILTIN_SKILLS
from lilly.domain.tasks import TaskState
from lilly.engine.bus import EventBus
from lilly.engine.orchestrator import SubmitRequest
from lilly.engine.receipt import ReceiptBuilder
from lilly.store import approvals as approval_store
from lilly.store import conversations, routines, tasks
from lilly.store.events import latest, list_events, verify_chain
from lilly.ui.support import (
    approval_json,
    conversation_json,
    event_json,
    flag,
    json_body,
    limit_param,
    message_json,
    ok,
    runtime,
    step_json,
    task_json,
    text,
)

KEEPALIVE_S = 15.0


# ---- conversations --------------------------------------------------------------------------
async def list_threads(request: Request) -> Response:
    con = runtime(request).db.reader
    query = request.query_params.get("q", "").strip()
    rows = (conversations.search_conversations(con, query) if query else
            conversations.list_conversations(con, include_archived=request.query_params.get("archived") == "1",
                                             limit=limit_param(request, 100)))
    return JSONResponse({"threads": [conversation_json(c) for c in rows]})


async def get_thread(request: Request) -> Response:
    rt = runtime(request)
    thread_id = request.path_params["thread_id"]
    conv = conversations.get_conversation(rt.db.reader, thread_id)
    if conv is None:
        raise NotFound(thread_id)
    msgs = conversations.list_messages(rt.db.reader, thread_id, limit=1000)
    runs = tasks.list_tasks(rt.db.reader, conversation_id=thread_id, limit=50)
    thread_tasks = []
    for task in reversed(runs):
        checked = latest(rt.db.reader, task.id, "reply_check")
        verdict = checked.payload.get("choice") if checked else None
        item = task_json(task)
        item["reply_check"] = verdict if verdict in (FOLLOWS, DRIFTS) else None
        thread_tasks.append(item)
    return JSONResponse({"thread": conversation_json(conv), "messages": [message_json(m) for m in msgs],
                         "tasks": thread_tasks})


async def update_thread(request: Request) -> Response:
    rt = runtime(request)
    data = await json_body(request)
    title, archived = text(data, "title", required=False, max_len=200), flag(data, "archived")
    now = rt.clock()
    row = await rt.db.write(lambda con: conversations.update_conversation(
        con, request.path_params["thread_id"], now, title=title, archived=archived))
    return JSONResponse({"thread": conversation_json(row)})


async def delete_thread(request: Request) -> Response:
    rt = runtime(request)
    thread_id = request.path_params["thread_id"]
    for t in tasks.list_tasks(rt.db.reader, conversation_id=thread_id, limit=200):
        if t.state not in (TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED, TaskState.EXPIRED):
            raise ValidationFailed("stop the running task before deleting this conversation")
    await rt.db.write(lambda con: conversations.delete_conversation(con, thread_id))
    return ok()


# ---- tasks -----------------------------------------------------------------------------------
async def submit_task(request: Request) -> Response:
    rt = runtime(request)
    data = await json_body(request)
    params = data.get("params", {})
    if not isinstance(params, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in params.items()):
        raise ValidationFailed("params must be an object of text values")
    profile_data = data.get("profile")
    profile: TaskProfile | None = None
    if profile_data is not None:
        if not isinstance(profile_data, dict):
            raise ValidationFailed("profile must be an object")
        profile = TaskProfile.from_dict(profile_data)
    row = await rt.orchestrator.submit(SubmitRequest(
        goal=text(data, "goal", max_len=4000) or "",
        conversation_id=text(data, "conversation_id", required=False, max_len=64),
        agent_id=text(data, "agent_id", required=False, max_len=64),
        skill=text(data, "skill", required=False, max_len=64),
        params=params,
        pin_model=text(data, "pin_model", required=False, max_len=64),
        profile=profile))
    return JSONResponse({"task": task_json(row)}, 202)


async def list_tasks(request: Request) -> Response:
    states: tuple[TaskState, ...] | None = None
    if raw := request.query_params.get("state"):
        try:
            states = tuple(TaskState(s) for s in raw.split(","))
        except ValueError:
            raise ValidationFailed("unknown task state") from None
    rows = tasks.list_tasks(runtime(request).db.reader, states=states, limit=limit_param(request))
    return JSONResponse({"tasks": [task_json(t) for t in rows]})


async def get_task(request: Request) -> Response:
    rt = runtime(request)
    task_id = request.path_params["task_id"]
    row = tasks.get_task(rt.db.reader, task_id)
    if row is None:
        raise NotFound(task_id)
    pending = [approval_json(a) for a in rt.approvals.pending() if a.task_id == task_id]
    announced = latest(rt.db.reader, task_id, "plan")
    checked = latest(rt.db.reader, task_id, "reply_check")
    verdict = checked.payload.get("choice") if checked else None
    return JSONResponse({"task": task_json(row), "steps": [step_json(s) for s in tasks.list_steps(rt.db.reader, task_id)],
                         "approvals": pending,
                         # the newest plan as announced: tool, expectation, dependencies and the predicted verdict
                         "plan_steps": announced.payload["steps"] if announced else [],
                         # Laya's advice on the finished reply, when it was asked and answered; it never changed the reply
                         "reply_check": verdict if verdict in (FOLLOWS, DRIFTS) else None})


async def task_events(request: Request) -> Response:
    rt = runtime(request)
    task_id = request.path_params["task_id"]
    if tasks.get_task(rt.db.reader, task_id) is None:
        raise NotFound(task_id)
    after = request.query_params.get("after", "0")
    rows = list_events(rt.db.reader, task_id, int(after) if after.isdigit() else 0, limit_param(request, 500, 1000))
    return JSONResponse({"events": [event_json(e) for e in rows]})


async def verify_task(request: Request) -> Response:
    rt = runtime(request)
    task_id = request.path_params["task_id"]
    if tasks.get_task(rt.db.reader, task_id) is None:
        raise NotFound(task_id)
    return JSONResponse({"intact": verify_chain(rt.db.reader, task_id)})


async def cancel_task(request: Request) -> Response:
    await runtime(request).orchestrator.cancel(request.path_params["task_id"])
    return ok()


async def get_receipt(request: Request) -> Response:
    rt = runtime(request)
    task_id = request.path_params.get("task_id") or request.path_params.get("id") or ""
    if tasks.get_task(rt.db.reader, task_id) is None:
        raise NotFound(task_id)
    globs = rt.settings.grounding.protected_globs
    receipt = ReceiptBuilder.build(rt.db, task_id, protected_globs=globs)
    return JSONResponse({"receipt": receipt.to_dict()})


async def stop_everything(request: Request) -> Response:
    """The kill switch: cancel every task and pause routines so nothing starts again by itself."""
    rt = runtime(request)
    stopped = await rt.orchestrator.stop_all()
    await rt.browser.close_all()
    await rt.devbox.close_all()
    paused = await rt.db.write(lambda con: routines.pause_all(con, "paused by Stop all"))
    return ok(stopped=stopped, routines_paused=paused)


async def list_skills(request: Request) -> Response:
    return JSONResponse({"skills": [
        {"name": s.name, "summary": s.summary, "params": list(s.params), "risk": s.max_risk.name}
        for s in BUILTIN_SKILLS.values()]})


# ---- approvals -------------------------------------------------------------------------------
async def list_approvals(request: Request) -> Response:
    rt = runtime(request)
    if request.query_params.get("status") == "pending":
        rows = rt.approvals.pending()
    else:
        rows = approval_store.list_approvals(rt.db.reader, limit=limit_param(request, 50))
    return JSONResponse({"approvals": [approval_json(a) for a in rows]})


async def decide_approval(request: Request) -> Response:
    rt = runtime(request)
    data = await json_body(request)
    approve = flag(data, "approve")
    if approve is None:
        raise ValidationFailed("approve must be true or false")
    row = await rt.approvals.decide(
        request.path_params["approval_id"], approve=approve,
        payload_hash=text(data, "payload_hash", max_len=64) or "",
        choice=text(data, "choice", required=False, max_len=64))
    return JSONResponse({"approval": approval_json(row)})


# ---- live events -----------------------------------------------------------------------------
async def _frames(bus: EventBus) -> AsyncIterator[str]:
    yield "retry: 3000\n\n"
    stream = bus.subscribe()
    waiting: asyncio.Future[dict[str, Any]] = asyncio.ensure_future(anext(stream))
    try:
        while True:
            done, _ = await asyncio.wait({waiting}, timeout=KEEPALIVE_S)
            if not done:
                yield ": keep-alive\n\n"
                continue
            try:
                message = waiting.result()
            except StopAsyncIteration:
                return
            waiting = asyncio.ensure_future(anext(stream))
            yield f"data: {json.dumps(message)}\n\n"
    finally:
        waiting.cancel()
        await stream.aclose()


async def live_events(request: Request) -> Response:
    return StreamingResponse(_frames(runtime(request).bus), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
