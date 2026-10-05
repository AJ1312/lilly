"""The devbox settings endpoints: signed-in only, status, background download, reset."""
from __future__ import annotations

import asyncio

import pytest

from lilly.tools.devbox.manager import DevboxManager
from tests.fake_engine import FakeEngine
from tests.integration.conftest import Api
from tests.unit.test_web_contract import _fields

pytestmark = pytest.mark.asyncio


def with_engine(api: Api, engine: FakeEngine | None, folder: str) -> None:
    from dataclasses import replace
    api.runtime.settings = replace(api.runtime.settings, devbox=replace(api.runtime.settings.devbox, shared_folder=folder))
    api.runtime.devbox = DevboxManager(lambda: api.runtime.settings.devbox, lambda: api.runtime.scope,
                                       lambda c: engine, api.runtime.clock, ids=(1, 1))


async def test_every_endpoint_needs_a_session(api: Api) -> None:
    for method, path in (("GET", "/api/devbox"), ("POST", "/api/devbox/prepare"), ("DELETE", "/api/devbox")):
        assert (await api.http.request(method, path)).status_code == 401, path


async def test_status_prepare_and_reset(api: Api, tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = FakeEngine(image_ready=False)
    with_engine(api, engine, str(tmp_path))
    await api.sign_in()
    first = (await api.get("/api/devbox")).json()
    assert first["engine"] == "fake" and first["image_ready"] is False and first["preparing"] is False
    assert (await api.send("POST", "/api/devbox/prepare")).status_code == 202
    await asyncio.sleep(0.05)
    after = (await api.get("/api/devbox")).json()
    assert after["image_ready"] is True and after["prepare_error"] is None
    assert _fields("DevboxStatus") == set(after)
    engine.box = "running"
    assert (await api.send("DELETE", "/api/devbox")).status_code == 200 and engine.box == "missing"


async def test_without_an_engine_prepare_says_what_is_missing(api: Api) -> None:
    with_engine(api, None, "")
    await api.sign_in()
    r = await api.send("POST", "/api/devbox/prepare")
    assert r.status_code == 409 and "not installed" in r.json()["error"]
    assert (await api.get("/api/devbox")).json()["state"] == "unavailable"
