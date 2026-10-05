"""Chat apps: the Telegram bot token, pairing a phone, and who is linked. Settings (on/off, which agent, limits)
travel with the rest of the settings."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lilly.domain.bridges import BridgeControl
from lilly.domain.errors import ConflictError, NotFound, ValidationFailed
from lilly.ui.support import json_body, ok

MAX_TOKEN_CHARS = 200


def _control(request: Request) -> BridgeControl:
    control: BridgeControl | None = request.app.state.bridges
    if control is None:
        raise ConflictError("chat apps are not available in this run of Lilly")
    return control


async def status(request: Request) -> Response:
    return JSONResponse({"telegram": _control(request).status()})


async def set_token(request: Request) -> Response:
    token = (await json_body(request)).get("token")
    if not isinstance(token, str) or not token.strip() or len(token) > MAX_TOKEN_CHARS:
        raise ValidationFailed("paste the bot token from @BotFather")
    bot = await _control(request).set_token(token)
    return JSONResponse({"bot": bot})


async def clear_token(request: Request) -> Response:
    await _control(request).clear_token()
    return ok()


async def new_pairing(request: Request) -> Response:
    return JSONResponse(await _control(request).new_pairing())


async def unpair(request: Request) -> Response:
    try:
        user_id = int(request.path_params["user_id"])
    except ValueError:
        raise ValidationFailed("that is not an account id") from None
    if not await _control(request).unpair(user_id):
        raise NotFound("that account is not linked")
    return ok()
