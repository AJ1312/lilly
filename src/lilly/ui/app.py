"""The web app: a JSON API plus the single-page interface, behind the security layer."""
from __future__ import annotations

import functools
from pathlib import Path

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from lilly.app.runtime import Runtime
from lilly.domain.bridges import BridgeControl
from lilly.ui import (
    api_admin,
    api_bridges,
    api_chat,
    api_computer,
    api_data,
    api_decisions,
    api_devbox,
    api_laya,
    api_live,
    api_mcp,
    api_routines,
)
from lilly.ui.security import SAFE_METHODS, Auth, Handler, Shield, guarded
from lilly.ui.support import error_response

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
_IMMUTABLE = "public, max-age=31536000, immutable"


def _safe(fn: Handler) -> Handler:
    """Turn any error raised by an endpoint into a JSON response that is safe to show."""

    @functools.wraps(fn)
    async def wrapper(request: Request) -> Response:
        try:
            return await fn(request)
        except HTTPException:
            raise  # status errors raised by the framework or the body limit are already well formed
        except Exception as exc:
            return error_response(exc)

    return wrapper


def _route(path: str, fn: Handler, methods: list[str], *, public: bool = False) -> Route:
    return Route(path, guarded(_safe(fn), public=public), methods=methods)


def api_routes() -> list[Route]:
    chat, data, admin = api_chat, api_data, api_admin
    return [
        # signing in: public, because these are how you become signed in
        _route("/healthz", admin.health, ["GET"], public=True),
        _route("/login", admin.login_link, ["GET"], public=True),
        _route("/api/session", admin.session_info, ["GET"], public=True),
        _route("/api/login", admin.login, ["POST"], public=True),
        _route("/api/logout", admin.logout, ["POST"]),
        _route("/api/session/revoke-all", admin.sign_out_everywhere, ["POST"]),
        _route("/api/session/token", admin.replace_token, ["POST"]),
        # chat
        _route("/api/threads", chat.list_threads, ["GET"]),
        _route("/api/threads/{thread_id}", chat.get_thread, ["GET"]),
        _route("/api/threads/{thread_id}", chat.update_thread, ["PATCH"]),
        _route("/api/threads/{thread_id}", chat.delete_thread, ["DELETE"]),
        _route("/api/tasks", chat.submit_task, ["POST"]),
        _route("/api/tasks", chat.list_tasks, ["GET"]),
        _route("/api/tasks/{task_id}", chat.get_task, ["GET"]),
        _route("/api/tasks/{task_id}/events", chat.task_events, ["GET"]),
        _route("/api/tasks/{task_id}/verify", chat.verify_task, ["GET"]),
        _route("/api/tasks/{task_id}/cancel", chat.cancel_task, ["POST"]),
        _route("/api/tasks/{task_id}/resume", chat.resume_task, ["POST"]),
        _route("/api/tasks/{task_id}/receipt", chat.get_receipt, ["GET"]),
        _route("/api/tasks/{id}/receipt", chat.get_receipt, ["GET"]),
        _route("/api/tasks/{task_id}/undo/{step_id}", data.undo_step, ["POST"]),
        _route("/api/tasks/{id}/undo/{step}", data.undo_step, ["POST"]),
        _route("/api/stop", chat.stop_everything, ["POST"]),
        _route("/api/skills", chat.list_skills, ["GET"]),
        _route("/api/approvals", chat.list_approvals, ["GET"]),
        _route("/api/approvals/{approval_id}/decide", chat.decide_approval, ["POST"]),
        _route("/api/events", chat.live_events, ["GET"]),
        # memory, notes, agents
        _route("/api/memory", data.list_memory, ["GET"]),
        _route("/api/memory", data.add_memory, ["POST"]),
        _route("/api/memory/clear", data.clear_memory, ["POST"]),
        _route("/api/memory/{memory_id}", data.update_memory, ["PATCH"]),
        _route("/api/memory/{memory_id}", data.delete_memory, ["DELETE"]),
        _route("/api/spaces", data.list_spaces, ["GET"]),
        _route("/api/spaces", data.create_space, ["POST"]),
        _route("/api/spaces/{space_id}", data.update_space, ["PATCH"]),
        _route("/api/spaces/{space_id}", data.delete_space, ["DELETE"]),
        _route("/api/spaces/{space_id}/pages", data.list_pages, ["GET"]),
        _route("/api/spaces/{space_id}/pages", data.create_page, ["POST"]),
        _route("/api/spaces/{space_id}/pages/{page_id}", data.get_page, ["GET"]),
        _route("/api/spaces/{space_id}/pages/{page_id}", data.update_page, ["PUT"]),
        _route("/api/spaces/{space_id}/pages/{page_id}", data.delete_page, ["DELETE"]),
        _route("/api/pages", data.search_all_pages, ["GET"]),
        _route("/api/agents", data.list_agents, ["GET"]),
        _route("/api/agents", data.create_agent, ["POST"]),
        _route("/api/agents/validate-sheet", data.validate_sheet, ["POST"]),
        _route("/api/agents/import", data.import_agent, ["POST"]),
        _route("/api/agents/{agent_id}/prompt-preview", data.prompt_preview, ["GET"]),
        _route("/api/agents/{agent_id}/export", data.export_agent, ["GET"]),
        _route("/api/agents/{agent_id}", data.update_agent, ["PATCH"]),
        _route("/api/agents/{agent_id}", data.delete_agent, ["DELETE"]),
        _route("/api/crew/route", data.crew_route, ["POST"]),
        # settings, models, keys, system, data
        _route("/api/routines", api_routines.list_routines, ["GET"]),
        _route("/api/routines", api_routines.create_routine, ["POST"]),
        _route("/api/routines/{routine_id}", api_routines.update_routine, ["PATCH"]),
        _route("/api/routines/{routine_id}", api_routines.delete_routine, ["DELETE"]),
        _route("/api/routines/{routine_id}/run", api_routines.run_routine, ["POST"]),
        _route("/api/mcp", api_mcp.list_servers, ["GET"]),
        _route("/api/mcp", api_mcp.put_server, ["POST"]),
        _route("/api/mcp/{name}", api_mcp.set_enabled, ["PATCH"]),
        _route("/api/mcp/{name}", api_mcp.delete_server, ["DELETE"]),
        _route("/api/mcp/{name}/review", api_mcp.review, ["POST"]),
        _route("/api/mcp/{name}/approve", api_mcp.approve, ["POST"]),
        _route("/api/mcp/{name}/approval", api_mcp.revoke, ["DELETE"]),
        _route("/api/decisions", api_decisions.list_decisions, ["GET"]),
        _route("/api/decisions/{log_id}/outcome", api_decisions.mark_outcome, ["POST"]),
        _route("/api/bridges", api_bridges.status, ["GET"]),
        _route("/api/bridges/telegram/token", api_bridges.set_token, ["PUT"]),
        _route("/api/bridges/telegram/token", api_bridges.clear_token, ["DELETE"]),
        _route("/api/bridges/telegram/pairing", api_bridges.new_pairing, ["POST"]),
        _route("/api/bridges/telegram/identities/{user_id}", api_bridges.unpair, ["DELETE"]),
        _route("/api/devbox", api_devbox.status, ["GET"]),
        _route("/api/devbox", api_devbox.reset, ["DELETE"]),
        _route("/api/devbox/prepare", api_devbox.prepare, ["POST"]),
        _route("/api/live", api_live.watched, ["GET"]),
        _route("/api/live/{task_id}/frame", api_live.frame, ["GET"]),
        _route("/api/computer/{task_id}", api_computer.state, ["GET"]),
        _route("/api/computer/{task_id}/screenshot", api_computer.screenshot, ["GET"]),
        _route("/api/laya", api_laya.status, ["GET"]),
        _route("/api/laya", api_laya.remove, ["DELETE"]),
        _route("/api/laya/check", api_laya.check, ["GET"]),
        _route("/api/laya/test", api_laya.test, ["POST"]),
        _route("/api/laya/install", api_laya.install, ["POST"]),
        _route("/api/laya/enabled", api_laya.set_enabled, ["PUT"]),
        _route("/api/laya/assist", api_laya.set_assist, ["PUT"]),
        _route("/api/settings", admin.get_settings, ["GET"]),
        _route("/api/settings", admin.put_settings, ["PUT"]),
        _route("/api/presets", admin.list_presets, ["GET"]),
        _route("/api/presets", admin.apply_preset, ["POST"]),
        _route("/api/models", admin.list_models, ["GET"]),
        _route("/api/models/{name}/test", admin.test_model, ["POST"]),
        _route("/api/models/{name}/ollama", admin.discover_ollama, ["GET"]),
        _route("/api/permissions/revoke-all", admin.revoke_permissions, ["POST"]),
        _route("/api/keys", admin.list_keys, ["GET"]),
        _route("/api/keys/{ref}", admin.put_key, ["PUT"]),
        _route("/api/keys/{ref}", admin.delete_key, ["DELETE"]),
        _route("/api/system", admin.system_info, ["GET"]),
        _route("/api/resources", admin.resources, ["GET"]),
        _route("/api/data/backup", admin.backup_now, ["POST"]),
        _route("/api/data/prune", admin.prune_now, ["POST"]),
        _route("/api/data/export", admin.export_data, ["GET"]),
        _route("/api/capacity", admin.get_capacity, ["GET"]),
        _route("/api/providers/catalog", admin.get_catalog, ["GET"]),
    ]


async def _no_such_api(request: Request) -> Response:
    return JSONResponse({"error": "not found"}, 404)


def _spa(web_dir: Path) -> Handler:
    """Serve the built interface. Only files inside the web folder are reachable."""
    root = web_dir.resolve()

    async def serve(request: Request) -> Response:
        rel = request.path_params.get("path", "")
        candidate = (root / rel).resolve()
        if rel and candidate.is_file() and root in candidate.parents:
            immutable = rel.startswith("assets/")
            return FileResponse(candidate, headers={"Cache-Control": _IMMUTABLE if immutable else "no-cache"})
        index = root / "index.html"
        if rel.startswith("assets/") or not index.is_file():
            return JSONResponse({"error": "not found"}, 404)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return serve


def create_app(runtime: Runtime, auth: Auth, web_dir: Path = WEB_DIR, bridges: BridgeControl | None = None) -> Starlette:
    routes: list[Route] = [
        *api_routes(),
        Route("/api/{rest:path}", guarded(_no_such_api, public=True), methods=["GET", "POST", "PUT", "PATCH", "DELETE"]),
        Route("/{path:path}", guarded(_spa(web_dir), public=True), methods=sorted(SAFE_METHODS - {"OPTIONS"})),
    ]
    app = Starlette(
        routes=routes,
        middleware=[Middleware(Shield, extra_hosts=lambda: runtime.settings.network.allowed_hosts)])
    app.state.runtime = runtime
    app.state.auth = auth
    app.state.bridges = bridges           # the running chat bridge, handed in by the daemon (None: not running)
    return app
