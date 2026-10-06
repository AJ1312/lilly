"""Read-only computer state for the task workspace."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lilly.domain.errors import NotFound
from lilly.ui.support import runtime


async def state(request: Request) -> Response:  # pragma: no cover - exercised through the ASGI app
    frame = runtime(request).computer.latest(request.path_params["task_id"])
    if frame is None:
        raise NotFound("no computer observation")
    return JSONResponse(json.loads(runtime(request).computer.render(frame)))


async def screenshot(request: Request) -> Response:  # pragma: no cover - exercised through the ASGI app
    frame = runtime(request).computer.latest(request.path_params["task_id"])
    if frame is None or not frame.screenshot:
        raise NotFound("no computer screenshot")
    try:
        data = await asyncio.to_thread(Path(frame.screenshot).read_bytes)
    except OSError as exc:
        raise NotFound("the computer screenshot is no longer available") from exc
    return Response(data, media_type="image/png", headers={"Cache-Control": "no-store"})
