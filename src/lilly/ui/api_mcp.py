"""MCP servers: add, review what they offer, approve exactly that, and turn them off."""
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lilly.app.runtime import Runtime
from lilly.domain.errors import ToolError, ValidationFailed
from lilly.domain.labels import Label, Risk
from lilly.domain.mcp import (
    ENV_NAME,
    IDLE_STOP_S,
    MAX_ARGS,
    MAX_ENV,
    McpApproval,
    McpServerConfig,
    fingerprint,
)
from lilly.store import mcp as store
from lilly.tools.mcp import ServerStatus
from lilly.ui.support import flag, json_body, ok, runtime, text

APPROVABLE = {"R0": Risk.R0, "R1": Risk.R1, "R2": Risk.R2}   # R3 (irreversible or outside) is never allowed here
LABELS = {"PUBLIC": Label.PUBLIC, "PERSONAL": Label.PERSONAL}
MAX_ERROR_CHARS = 300


def secret_ref(server: str, var: str) -> str:
    """The key-store name of one secret variable. Lilly makes it; a request can never choose another."""
    return f"mcp.{server}.{var}"


def _strings(data: dict[str, Any], key: str, limit: int) -> list[str]:
    raw = data.get(key, [])
    if not isinstance(raw, list) or len(raw) > limit or not all(isinstance(x, str) for x in raw):
        raise ValidationFailed(f"{key} must be a short list of text")
    return list(raw)


def _env(data: dict[str, Any]) -> dict[str, str]:
    raw = data.get("env", {})
    if not isinstance(raw, dict) or len(raw) > MAX_ENV or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in raw.items()):
        raise ValidationFailed("env must be a short set of text values")
    return dict(raw)


def _config(data: dict[str, Any], name: str) -> McpServerConfig:
    secret_vars = _strings(data, "secret_vars", MAX_ENV)
    if any(not ENV_NAME.fullmatch(v) for v in secret_vars):
        raise ValidationFailed("a secret variable name is not valid")
    label = str(data.get("data_label", "PERSONAL")).upper()
    if label not in LABELS:
        raise ValidationFailed("data_label must be PUBLIC or PERSONAL")
    idle = data.get("idle_stop_s", IDLE_STOP_S)
    if not isinstance(idle, int | float) or isinstance(idle, bool):
        raise ValidationFailed("idle_stop_s must be a number")
    enabled = flag(data, "enabled")
    return McpServerConfig(
        name=name, command=(text(data, "command", max_len=1000) or "").strip(),
        args=tuple(_strings(data, "args", MAX_ARGS)), env=_env(data),
        secret_env={v: secret_ref(name, v) for v in secret_vars}, enabled=True if enabled is None else enabled,
        data_label=LABELS[label], idle_stop_s=float(idle))


def secret_refs(rt: Runtime) -> set[str]:
    """Every key-store name that belongs to a stored server."""
    return {ref for c in store.list_servers(rt.db.reader) for ref in c.secret_env.values()}


def _server_json(cfg: McpServerConfig, approval: McpApproval | None, status: ServerStatus | None,
                 present: dict[str, bool], now: float) -> dict[str, Any]:
    return {
        "name": cfg.name, "command": cfg.command, "args": list(cfg.args), "env": dict(cfg.env),
        "secret_vars": [{"var": v, "ref": r, "present": present.get(r, False)} for v, r in cfg.secret_env.items()],
        "enabled": cfg.enabled, "data_label": cfg.data_label.name, "idle_stop_s": cfg.idle_stop_s,
        "approved_tools": [{"name": t.name, "description": t.description, "risk": f"R{int(approval.risks[t.name])}"}
                           for t in approval.tools if t.name in approval.risks] if approval else [],
        "approved": approval is not None,
        "state": status.state if status else "stopped", "error": status.error if status else "",
        "last_used": now - status.idle_s if status and status.idle_s is not None else None}


async def list_servers(request: Request) -> Response:
    rt = runtime(request)
    servers, approvals = store.list_servers(rt.db.reader), store.get_approvals(rt.db.reader)
    states = {s.name: s for s in rt.mcp.status()}
    refs = [r for c in servers for r in c.secret_env.values()]
    found = await asyncio.to_thread(lambda: {r: rt.keys.get(r) is not None for r in refs})
    return JSONResponse({"servers": [_server_json(c, approvals.get(c.name), states.get(c.name), found, rt.clock())
                                     for c in servers]})


async def put_server(request: Request) -> Response:
    """Add a server, or replace one with the same name. Changing how it starts withdraws its approval."""
    rt = runtime(request)
    data = await json_body(request)
    cfg = _config(data, (text(data, "name", max_len=32) or "").strip())
    now = rt.clock()

    def save(con: sqlite3.Connection) -> set[str]:
        old = {r for c in store.list_servers(con) if c.name == cfg.name for r in c.secret_env.values()}
        store.put_server(con, cfg, now)
        return old - set(cfg.secret_env.values())

    dropped = await rt.db.write(save)
    for ref in dropped:   # a variable that is no longer secret must not leave its value behind
        await asyncio.to_thread(rt.keys.delete, ref)
    await rt.reload_mcp()
    return ok()


async def set_enabled(request: Request) -> Response:
    rt = runtime(request)
    on = flag(await json_body(request), "enabled")
    if on is None:
        raise ValidationFailed("enabled is required")
    name = request.path_params["name"]
    await rt.db.write(lambda con: store.set_enabled(con, name, on))
    await rt.reload_mcp()
    return ok()


async def delete_server(request: Request) -> Response:
    rt = runtime(request)
    name = request.path_params["name"]

    def remove(con: sqlite3.Connection) -> list[str]:
        refs = [r for c in store.list_servers(con) if c.name == name for r in c.secret_env.values()]
        store.delete_server(con, name)
        return refs

    for ref in await rt.db.write(remove):
        await asyncio.to_thread(rt.keys.delete, ref)
    await rt.reload_mcp()
    return ok()


def _unavailable(exc: ToolError) -> ValidationFailed:
    return ValidationFailed(str(exc.args[0] if exc.args else exc.public)[:MAX_ERROR_CHARS])


async def review(request: Request) -> Response:
    """Start the server and list what it offers. Nothing is approved by looking."""
    rt = runtime(request)
    try:
        found = await rt.mcp.discover(request.path_params["name"])
    except ToolError as exc:
        raise _unavailable(exc) from None
    return JSONResponse({"fingerprint": found.fingerprint, "tools": [
        {"name": t.name, "description": t.description, "input_schema": dict(t.input_schema)} for t in found.tools]})


async def approve(request: Request) -> Response:
    """Approve exactly the tools the owner reviewed. The server is asked again and must still offer that list."""
    rt = runtime(request)
    name = request.path_params["name"]
    data = await json_body(request)
    reviewed = text(data, "fingerprint", max_len=64) or ""
    raw = data.get("risks")
    if not isinstance(raw, dict) or not raw:
        raise ValidationFailed("choose at least one tool and its risk level")
    risks: dict[str, Risk] = {}
    for tool, level in raw.items():
        if not isinstance(level, str) or level not in APPROVABLE:
            raise ValidationFailed("a tool's risk must be R0, R1 or R2")
        risks[str(tool)] = APPROVABLE[level]
    try:
        found = await rt.mcp.discover(name)
    except ToolError as exc:
        raise _unavailable(exc) from None
    if found.fingerprint != reviewed or fingerprint(found.tools) != reviewed:
        raise ValidationFailed("the server's tools changed since you reviewed them; review them again")
    now = rt.clock()
    await rt.db.write(lambda con: store.put_approval(con, McpApproval(name, found.tools, risks), now))
    await rt.reload_mcp()
    return ok()


async def revoke(request: Request) -> Response:
    rt = runtime(request)
    name = request.path_params["name"]
    await rt.db.write(lambda con: store.revoke_approval(con, name))
    await rt.reload_mcp()
    return ok()
