"""Watching the agent's browser: a read-only picture of a task's tab, only when asked for.

Nothing here can click, type or open anything, and asking for a picture never starts the browser or keeps it awake."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lilly.domain.errors import NotFound
from lilly.ui.support import runtime


async def watched(request: Request) -> Response:
    rt = runtime(request)
    browser = rt.browser
    tasks_list: list[dict[str, str]] = [{"task_id": t, "host": browser.host_of(t)} for t in browser.watched()]
    if rt.computer is not None and hasattr(rt.computer, "watched_tasks"):
        for ct in rt.computer.watched_tasks():
            if not any(item["task_id"] == ct for item in tasks_list):
                tasks_list.append({"task_id": ct, "host": "desktop"})
    return JSONResponse({"tasks": tasks_list})


async def frame(request: Request) -> Response:
    task_id = request.path_params["task_id"]
    rt = runtime(request)
    # 1. Try browser screenshot
    picture = await rt.browser.screenshot(task_id)
    if picture is not None:
        return Response(picture, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    # 2. Try desktop / ComputerRuntime screenshot
    if rt.computer is not None and hasattr(rt.computer, "screenshot_bytes"):
        comp_pic = await rt.computer.screenshot_bytes(task_id)
        if comp_pic is not None:
            return Response(comp_pic, media_type="image/png", headers={"Cache-Control": "no-store"})

    raise NotFound("no active tab or desktop screen")

