"""Watching the agent's browser: a read-only picture of a task's tab, only when asked for.

Nothing here can click, type or open anything, and asking for a picture never starts the browser or keeps it awake."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lilly.domain.errors import NotFound
from lilly.ui.support import runtime


async def watched(request: Request) -> Response:
    browser = runtime(request).browser
    return JSONResponse({"tasks": [{"task_id": t, "host": browser.host_of(t)} for t in browser.watched()]})


async def frame(request: Request) -> Response:
    picture = await runtime(request).browser.screenshot(request.path_params["task_id"])
    if picture is None:
        raise NotFound("no tab")
    return Response(picture, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
