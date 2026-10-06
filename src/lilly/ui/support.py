"""Small helpers shared by the API handlers: typed access to the runtime, request parsing, serialising rows."""
from __future__ import annotations

import json
import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lilly.app.runtime import Runtime
from lilly.domain.errors import (
    ApprovalExpired,
    ConflictError,
    LillyError,
    NotFound,
    PolicyDenied,
    ValidationFailed,
    WriterBusy,
)
from lilly.domain.schedule import describe, schedule_to_dict
from lilly.store import approvals as approval_store
from lilly.store import conversations, memory, routines, spaces, tasks
from lilly.store.events import EventRow

log = logging.getLogger("lilly.ui")


def runtime(request: Request) -> Runtime:
    rt: Runtime = request.app.state.runtime
    return rt


async def json_body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise ValidationFailed("the request body must be JSON") from None
    if not isinstance(data, dict):
        raise ValidationFailed("the request body must be a JSON object")
    return data


def text(data: dict[str, Any], key: str, *, required: bool = True, max_len: int = 8000) -> str | None:
    value = data.get(key)
    if value is None:
        if required:
            raise ValidationFailed(f"{key} is required")
        return None
    if not isinstance(value, str) or len(value) > max_len or (required and not value.strip()):
        raise ValidationFailed(f"{key} must be text of up to {max_len} characters")
    return value


def flag(data: dict[str, Any], key: str) -> bool | None:
    value = data.get(key)
    if value is not None and not isinstance(value, bool):
        raise ValidationFailed(f"{key} must be true or false")
    return value


def whole(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
        raise ValidationFailed(f"{key} must be a whole number")
    return value


def limit_param(request: Request, default: int = 50, hi: int = 200) -> int:
    raw = request.query_params.get("limit", "")
    return max(1, min(int(raw), hi)) if raw.isdigit() else default


def ok(**fields: Any) -> JSONResponse:
    return JSONResponse({"ok": True, **fields})


def error_response(exc: Exception) -> Response:
    """Turn an error into a status and a message that is safe to show. Details go to the log only."""
    if isinstance(exc, NotFound):
        return JSONResponse({"error": "not found"}, 404)
    if isinstance(exc, ValidationFailed):
        return JSONResponse({"error": str(exc.args[0]) if exc.args else exc.public}, 400)
    if isinstance(exc, ApprovalExpired):
        return JSONResponse({"error": "that approval has expired"}, 410)
    if isinstance(exc, ConflictError):
        return JSONResponse({"error": str(exc.args[0]) if exc.args else exc.public}, 409)
    if isinstance(exc, PolicyDenied):
        return JSONResponse({"error": exc.public}, 403)
    if isinstance(exc, WriterBusy):
        return JSONResponse({"error": "Lilly is busy; try again in a moment"}, 503)
    if isinstance(exc, LillyError):
        log.warning("request failed: %r", exc)
        return JSONResponse({"error": exc.public}, 500)
    log.exception("unexpected error", exc_info=exc)
    return JSONResponse({"error": "something went wrong; the details are in the log"}, 500)


# ---- serialising --------------------------------------------------------------------------
def _loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def task_json(t: tasks.TaskRow) -> dict[str, Any]:
    return {"id": t.id, "conversation_id": t.conversation_id, "agent_id": t.agent_id, "state": t.state.value,
            "goal": t.goal, "mode": t.mode, "label": t.label.name, "tainted": t.tainted, "skill": t.skill,
            "plan": _loads(t.plan_json), "pinned_model": t.pinned_model, "answer": t.answer, "error": t.error,
            "created_at": t.created_at, "updated_at": t.updated_at, "finished_at": t.finished_at}


def step_json(s: tasks.StepRow) -> dict[str, Any]:
    return {"id": s.step_id, "position": s.position, "tool": s.tool, "status": s.status,
            "args": _loads(s.args_json), "output": s.output, "label": s.label.name, "untrusted": s.untrusted,
            "error": s.error, "started_at": s.started_at, "finished_at": s.finished_at}


def approval_json(a: approval_store.ApprovalRow) -> dict[str, Any]:
    return {"id": a.id, "task_id": a.task_id, "step_id": a.step_id, "kind": a.kind, "summary": a.summary,
            "payload": _loads(a.payload_json), "payload_hash": a.payload_hash, "status": a.status,
            "created_at": a.created_at, "expires_at": a.expires_at, "decided_at": a.decided_at}


def event_json(e: EventRow) -> dict[str, Any]:
    return {"seq": e.seq, "kind": e.kind, "payload": e.payload, "by": e.prov, "at": e.ts}


def conversation_json(c: conversations.ConversationRow) -> dict[str, Any]:
    return {"id": c.id, "space_id": c.space_id, "title": c.title, "archived": c.archived,
            "created_at": c.created_at, "updated_at": c.updated_at}


def message_json(m: conversations.MessageRow) -> dict[str, Any]:
    return {"id": m.id, "task_id": m.task_id, "role": m.role, "content": m.content, "label": m.label.name,
            "untrusted": m.untrusted, "at": m.created_at}


def memory_json(m: memory.MemoryRow) -> dict[str, Any]:
    return {"id": m.id, "text": m.text, "label": m.label.name, "source": m.source, "at": m.created_at,
            "tags": list(m.tags)}


def space_json(s: spaces.SpaceRow) -> dict[str, Any]:
    return {"id": s.id, "name": s.name, "description": s.description, "created_at": s.created_at}


def page_json(p: spaces.PageRow, *, with_content: bool = True) -> dict[str, Any]:
    out = {"id": p.id, "space_id": p.space_id, "title": p.title, "revision": p.revision,
           "created_at": p.created_at, "updated_at": p.updated_at}
    if with_content:
        out["content"] = p.content
    return out


def routine_json(r: routines.RoutineRow) -> dict[str, Any]:
    return {"id": r.id, "name": r.name, "goal": r.goal, "agent_id": r.agent_id,
            "schedule": schedule_to_dict(r.schedule), "when": describe(r.schedule), "enabled": r.enabled,
            "next_run": r.next_run, "last_run": r.last_run, "last_task_id": r.last_task_id,
            "last_state": r.last_state, "last_error": r.last_error, "pause_reason": r.pause_reason,
            "created_at": r.created_at}
