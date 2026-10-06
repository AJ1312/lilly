"""The optional Laya model: whether it is installed, installing it, and turning it on or off."""
from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lilly.app.runtime import Runtime
from lilly.domain.decisions import ASSIST_KINDS, laya_kinds, with_assist, with_laya
from lilly.domain.errors import ConflictError, ValidationFailed
from lilly.ui.support import json_body, runtime


def _view(rt: Runtime) -> dict[str, Any]:
    return {**rt.laya.status(), "enabled_for": list(laya_kinds(rt.settings.decisions))}


async def _switch(rt: Runtime, on: bool) -> None:
    await rt.apply_settings(replace(rt.settings, decisions=with_laya(rt.settings.decisions, on)))


async def status(request: Request) -> Response:
    return JSONResponse(_view(runtime(request)))


async def check(request: Request) -> Response:
    """Whether this computer can run Laya, found out without downloading anything."""
    checks = await runtime(request).laya.check()
    return JSONResponse({"checks": [asdict(c) for c in checks], "ok": all(c.ok for c in checks)})


async def test(request: Request) -> Response:
    """Load Laya and ask it three questions with known answers. Does not turn it on."""
    report = await runtime(request).laya.test()
    return JSONResponse(asdict(report))


async def install(request: Request) -> Response:
    rt = runtime(request)
    rt.laya.install()
    return JSONResponse(_view(rt), status_code=202)


async def set_enabled(request: Request) -> Response:
    rt = runtime(request)
    on = (await json_body(request)).get("enabled")
    if not isinstance(on, bool):
        raise ValidationFailed("enabled must be true or false")
    if on and not rt.laya.status()["installed"]:
        raise ConflictError("Laya is not installed yet")
    await _switch(rt, on)
    return JSONResponse(_view(rt))


async def set_assist(request: Request) -> Response:
    """Switch one of the Laya assist questions on (watch only, or acting) or off."""
    rt = runtime(request)
    body = await json_body(request)
    kind = next((k for k in ASSIST_KINDS if k.value == body.get("kind")), None)
    on, act = body.get("enabled"), body.get("act", False)
    if kind is None or not isinstance(on, bool) or not isinstance(act, bool):
        raise ValidationFailed("kind must be plan, reply or route, and enabled and act must be true or false")
    if on and not rt.laya.status()["installed"]:
        raise ConflictError("Laya is not installed yet")
    if on and act:
        kind_settings = rt.settings.decisions.for_kind(kind)
        if kind_settings.min_samples > 0:
            from lilly.store import decisions as dec_store
            summaries = dec_store.summary(rt.db.reader)
            matching = [s for s in summaries if s.kind == kind.value and s.decider == "laya"]
            accepted = sum(s.accepted for s in matching)
            corrected = sum(s.corrected for s in matching)
            n = accepted + corrected
            precision = (accepted / n) if n > 0 else 0.0
            if n < kind_settings.min_samples or precision < kind_settings.min_precision:
                p = round(precision * 100, 1)
                p_val = int(p) if p.is_integer() else p
                raise ConflictError(
                    f"Laya's answers on this question have not been checked enough yet "
                    f"({n} of {kind_settings.min_samples} marked, {p_val} % right). Keep it on watch only."
                )
    await rt.apply_settings(replace(rt.settings, decisions=with_assist(rt.settings.decisions, kind, on, act)))
    return JSONResponse(_view(rt))


async def remove(request: Request) -> Response:
    rt = runtime(request)
    await rt.laya.remove()          # refuses while an install is running
    await _switch(rt, False)
    return JSONResponse(_view(rt))
