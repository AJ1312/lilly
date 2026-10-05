"""The decision log: what the cheap deciders were asked and what they answered."""
from __future__ import annotations

from dataclasses import asdict

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lilly.domain.decisions import OUTCOMES, Kind
from lilly.domain.errors import NotFound, ValidationFailed
from lilly.store import decisions
from lilly.ui.support import json_body, limit_param, runtime


async def list_decisions(request: Request) -> Response:
    raw = request.query_params.get("kind")
    try:
        kind = Kind(raw) if raw else None
    except ValueError:
        raise ValidationFailed("kind must be one of " + ", ".join(k.value for k in Kind)) from None
    con = runtime(request).db.reader
    return JSONResponse({"decisions": [asdict(r) for r in decisions.recent(con, limit_param(request), kind)],
                         "summary": [asdict(s) for s in decisions.summary(con)]})


async def mark_outcome(request: Request) -> Response:
    """The owner says whether a decision was right: it becomes the ground truth that `calibrate` learns from."""
    try:
        log_id = int(request.path_params["log_id"])
    except ValueError:
        raise ValidationFailed("that is not a decision id") from None
    body = await json_body(request)
    outcome = body.get("outcome")
    if outcome not in OUTCOMES:
        raise ValidationFailed("outcome must be one of " + ", ".join(OUTCOMES))
    if not await runtime(request).db.write(lambda con: decisions.set_outcome(con, log_id, str(outcome))):
        raise NotFound("that decision is no longer in the log")
    return JSONResponse({"ok": True})
