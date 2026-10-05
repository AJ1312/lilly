"""The devbox settings screen: what is ready, downloading the image, and resetting the box."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lilly.ui.support import ok, runtime


async def status(request: Request) -> Response:
    return JSONResponse(await runtime(request).devbox.status())


async def prepare(request: Request) -> Response:
    runtime(request).devbox.begin_prepare()
    return JSONResponse({"ok": True}, 202)


async def reset(request: Request) -> Response:
    await runtime(request).devbox.reset()
    return ok()
