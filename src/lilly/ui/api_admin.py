"""Signing in, settings, models and keys, security controls, and the user's data (backup, export)."""
from __future__ import annotations

import asyncio
import contextlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

import psutil
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from lilly import __version__
from lilly.app.runtime import Runtime
from lilly.domain.errors import NotFound, ValidationFailed
from lilly.domain.ports import Secret
from lilly.domain.presets import PRESETS
from lilly.domain.settings import parse_settings, settings_to_dict
from lilly.domain.tasks import TERMINAL, TaskState
from lilly.store import tasks
from lilly.tools.system import collect_stats
from lilly.ui.api_mcp import secret_refs
from lilly.ui.security import Auth, clear_session, session_cookie, set_session
from lilly.ui.support import json_body, ok, runtime, text

MAX_KEY_CHARS = 512


def _auth(request: Request) -> Auth:
    auth: Auth = request.app.state.auth
    return auth


def _signed_in(request: Request, **extra: Any) -> Response:
    """The reply to a successful sign-in: a new session cookie and the CSRF token that goes with it."""
    auth = _auth(request)
    cookie = auth.issue_session()
    response = JSONResponse({"ok": True, "csrf": auth.csrf_token(cookie), **extra})
    set_session(response, request, cookie)
    return response


# ---- sessions (public: they establish who you are) ------------------------------------------------
async def session_info(request: Request) -> Response:
    auth, cookie = _auth(request), session_cookie(request)
    if cookie is None or not auth.valid_session(cookie):
        return JSONResponse({"signed_in": False})
    return JSONResponse({"signed_in": True, "csrf": auth.csrf_token(cookie), "version": __version__})


async def login(request: Request) -> Response:
    auth = _auth(request)
    if auth.limiter.blocked():
        return JSONResponse({"error": "too many attempts; wait a minute"}, 429)
    token = text(await json_body(request), "token", max_len=200) or ""
    if not auth.check_token(token.strip()):
        auth.limiter.failed()
        return JSONResponse({"error": "that is not the access token"}, 401)
    return _signed_in(request)


async def login_link(request: Request) -> Response:
    """`lilly open` uses this so a click signs you in. The token is only accepted here, then redirected away."""
    auth = _auth(request)
    if auth.limiter.blocked():
        return Response("Too many attempts. Wait a minute.", 429)
    if not auth.check_token(request.query_params.get("token", "").strip()):
        auth.limiter.failed()
        return RedirectResponse("/", 303)
    response = RedirectResponse("/", 303)
    set_session(response, request, auth.issue_session())
    return response


async def logout(request: Request) -> Response:
    response = ok()
    clear_session(response)
    return response


async def sign_out_everywhere(request: Request) -> Response:
    _auth(request).sign_out_everywhere()
    return _signed_in(request)  # this browser stays signed in; every other session stops working


async def replace_token(request: Request) -> Response:
    """A new access token, shown once. Every other browser is signed out."""
    return _signed_in(request, token=_auth(request).replace_token())


# ---- settings -------------------------------------------------------------------------------------
def _key_refs(rt: Runtime) -> list[str]:
    refs = {s.key_ref or s.provider for s in rt.settings.models if not s.local}
    if rt.settings.search.engine == "brave":
        refs.add("brave")
    return sorted(refs | secret_refs(rt))


async def get_settings(request: Request) -> Response:
    rt = runtime(request)
    return JSONResponse({"settings": settings_to_dict(rt.settings), "problems": rt.settings_problems})


async def put_settings(request: Request) -> Response:
    rt = runtime(request)
    new, problems = parse_settings(await json_body(request))
    if new is None:
        raise ValidationFailed("; ".join(problems))
    await rt.apply_settings(new)
    return JSONResponse({"settings": settings_to_dict(rt.settings), "problems": []})


async def list_presets(request: Request) -> Response:
    return JSONResponse({"presets": [{"name": p.name, "summary": p.summary} for p in PRESETS.values()]})


async def apply_preset(request: Request) -> Response:
    """Set the resource limits of a preset. Nothing but limits and idle times changes."""
    rt = runtime(request)
    name = (await json_body(request)).get("name")
    preset = PRESETS.get(name) if isinstance(name, str) else None
    if preset is None:
        raise ValidationFailed("choose one of: " + ", ".join(PRESETS))
    await rt.apply_settings(preset.apply(rt.settings))
    return JSONResponse({"settings": settings_to_dict(rt.settings), "problems": []})


# ---- models and keys ------------------------------------------------------------------------------
async def list_models(request: Request) -> Response:
    rt = runtime(request)
    specs = {s.name: s for s in rt.settings.models}
    rows = []
    for row in rt.router.status():
        s = specs[str(row["name"])]
        rows.append({**row, "caps": [c.name for c in type(s.caps) if c and c in s.caps],
                     "max_label": s.max_label.name, "private_access": s.private_access, "trains": s.trains})
    return JSONResponse({"models": rows, "permissions": len(rt.grants)})


async def test_model(request: Request) -> Response:
    return JSONResponse(await runtime(request).router.test(request.path_params["name"]))


async def discover_ollama(request: Request) -> Response:
    """What the Ollama server behind this model has installed, or a plain explanation of why it cannot be reached."""
    status = await runtime(request).router.discover_ollama(request.path_params["name"])
    if status is None:
        raise NotFound(request.path_params["name"])
    return JSONResponse({"reachable": status.reachable, "version": status.version, "models": list(status.models),
                         "model_ready": status.model_ready, "message": status.message})


async def revoke_permissions(request: Request) -> Response:
    return ok(revoked=runtime(request).grants.revoke_all())


async def list_keys(request: Request) -> Response:
    rt = runtime(request)
    refs = _key_refs(rt)
    present = await asyncio.to_thread(lambda: [rt.keys.get(r) is not None for r in refs])
    return JSONResponse({"store": {"kind": getattr(rt.keys, "kind", "unknown"),
                                   "secure": bool(getattr(rt.keys, "secure", False))},
                         "keys": [{"ref": r, "present": p} for r, p in zip(refs, present, strict=True)]})


def _known_ref(request: Request) -> str:
    ref = request.path_params["ref"]
    if ref not in _key_refs(runtime(request)):
        raise NotFound(ref)
    return str(ref)


async def put_key(request: Request) -> Response:
    rt = runtime(request)
    ref = _known_ref(request)
    value = (text(await json_body(request), "value", max_len=MAX_KEY_CHARS) or "").strip()
    if not value:
        raise ValidationFailed("paste the key")
    if not (value.isascii() and value.isprintable()):
        raise ValidationFailed("a key uses only plain letters, digits and symbols: check it was copied correctly")
    await asyncio.to_thread(rt.keys.put, ref, Secret(value))
    await rt.refresh_keys()
    return ok()


async def delete_key(request: Request) -> Response:
    rt = runtime(request)
    await asyncio.to_thread(rt.keys.delete, _known_ref(request))
    await rt.refresh_keys()
    return ok()


# ---- system and data ------------------------------------------------------------------------------
async def system_info(request: Request) -> Response:
    rt = runtime(request)
    stats: dict[str, Any] = await asyncio.to_thread(collect_stats, 5)
    m = rt.maintenance
    return JSONResponse({
        "version": __version__, "python": sys.version.split()[0], "platform": platform.platform(),
        "home": str(rt.paths.root), "uptime_s": round(rt.clock() - rt.started_at),
        "running_tasks": rt.orchestrator.active_count, "pending_approvals": len(rt.approvals.pending()),
        "stay_awake_active": rt.power.holding, "settings_problems": rt.settings_problems,
        "key_store": {"kind": getattr(rt.keys, "kind", "unknown"), "secure": bool(getattr(rt.keys, "secure", False))},
        "maintenance": {"last_backup": m.last_backup or None, "last_backup_file": m.last_backup_file,
                        "integrity_ok": m.integrity_ok},
        "stats": stats})


_SELF = psutil.Process()


def _folder_bytes(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        with contextlib.suppress(OSError):
            if f.is_file():
                total += f.stat().st_size
    return total


def _footprint(rt: Runtime) -> dict[str, Any]:
    """What Lilly itself uses: its own process and the files it keeps."""
    with _SELF.oneshot():
        mem, threads, cpu = _SELF.memory_info().rss, _SELF.num_threads(), _SELF.cpu_percent(interval=None)
    db_bytes = sum(f.stat().st_size for f in rt.paths.db.parent.glob(rt.paths.db.name + "*") if f.is_file())
    return {"pid": _SELF.pid, "cpu_percent": round(cpu, 1), "memory_bytes": mem, "threads": threads,
            "database_bytes": db_bytes, "backups_bytes": _folder_bytes(rt.paths.backups),
            "logs_bytes": _folder_bytes(rt.paths.log)}


async def resources(request: Request) -> Response:
    """Everything the Resources screen shows, in one call: the machine, Lilly's own use, the work in flight,
    the limits, and each model's quota and state."""
    rt = runtime(request)
    machine, footprint = await asyncio.gather(asyncio.to_thread(collect_stats, 8), asyncio.to_thread(_footprint, rt))
    live = tasks.list_tasks(rt.db.reader, states=tuple(s for s in TaskState if s not in TERMINAL), limit=50)
    lim = rt.settings.limits
    return JSONResponse({
        "machine": machine, "lilly": footprint,
        "tasks": {"running": rt.orchestrator.running_count, "queued": rt.orchestrator.queued_count,
                  "waiting_approval": len(rt.approvals.pending()),
                  "live": [{"id": t.id, "goal": t.goal[:120], "state": t.state.value, "created_at": t.created_at}
                           for t in live]},
        "limits": {"max_running": lim.max_running, "step_timeout_s": lim.step_timeout_s, "task_minutes": lim.task_minutes,
                   "lanes": lim.lanes, "local_unload_s": lim.local_unload_s},
        "models": rt.router.status(),
        "stay_awake_active": rt.power.holding})


async def backup_now(request: Request) -> Response:
    path = await runtime(request).backup()
    return ok(file=path.name)


async def prune_now(request: Request) -> Response:
    return ok(removed=await runtime(request).prune())


async def export_data(request: Request) -> Response:
    rt = runtime(request)
    body = json.dumps(rt.export_all(), indent=1)
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="lilly-export.json"'})


async def health(request: Request) -> Response:
    """Public and tiny: lets `lilly status`, launchd and the installer ask whether Lilly is up."""
    return JSONResponse({"ok": True, "app": "lilly", "version": __version__})


async def get_capacity(request: Request) -> Response:
    """Live capacity status across models and queue."""
    rt = runtime(request)
    rows = rt.router.capacity.snapshot()
    q_len = len(rt.router.capacity._waiters)
    models = [
        {
            "name": r.name,
            "lane": r.lane,
            "tags": list(r.tags),
            "rpm": r.rpm,
            "rpm_used": r.rpm_used,
            "rpd": r.rpd,
            "rpd_used": r.rpd_used,
            "tpm": r.tpm,
            "tpm_used": r.tpm_used,
            "tpd": r.tpd,
            "tpd_used": r.tpd_used,
            "breaker": r.breaker,
            "ready_in_s": r.ready_in_s,
            "resets_in_s": r.resets_in_s,
        }
        for r in rows
    ]
    est_tasks = min((r.estimated_tasks_left for r in rows if r.estimated_tasks_left is not None), default=None)
    return JSONResponse({
        "models": models,
        "queue_length": q_len,
        "estimated_tasks_left_today": est_tasks,
    })


async def get_catalog(request: Request) -> Response:
    """Serve provider catalog entries."""
    from lilly.providers.catalog import load_catalog
    entries = load_catalog()
    return JSONResponse([
        {
            "id": e.id,
            "name": e.name,
            "provider": e.provider,
            "model_id": e.model_id,
            "base_url": e.base_url,
            "openai_compatible": e.openai_compatible,
            "starter": e.starter,
            "enabled": e.enabled,
            "local": e.local,
            "lane": e.lane,
            "tags": list(e.tags),
            "caps": list(e.caps),
            "key_ref": e.key_ref,
            "free_tier": {
                "rpm": e.free_tier.rpm,
                "rpd": e.free_tier.rpd,
                "tpm": e.free_tier.tpm,
                "tpd": e.free_tier.tpd,
                "notes": e.free_tier.notes,
            },
            "tools": e.tools,
            "max_context_tokens": e.max_context_tokens,
            "source_url": e.source_url,
            "verified_on": e.verified_on,
            "confidence": e.confidence,
        }
        for e in entries
    ])
