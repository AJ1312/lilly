"""The chat-app endpoints: signed-in only, and they drive the bridge without ever returning the bot token."""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from lilly.bridges.service import TOKEN_REF, BridgeService
from lilly.bridges.telegram import TelegramApi
from lilly.ui.app import create_app
from tests.fake_telegram import BASE, TOKEN, FakeTelegram
from tests.integration.conftest import Api
from tests.unit.test_web_contract import _fields

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def wired(api: Api, tmp_path: Path) -> AsyncIterator[tuple[Api, FakeTelegram]]:
    tg = FakeTelegram()
    tgc = tg.client()
    service = BridgeService(api.runtime, lambda token: TelegramApi(tgc, token, BASE), poll_s=1, backoff_s=0.05)
    await service.start()
    app = create_app(api.runtime, api.auth, web_dir=tmp_path / "no-web", bridges=service)
    await api.http.aclose()
    api.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8787")
    yield api, tg
    await service.aclose()
    await tgc.aclose()


async def test_every_chat_endpoint_needs_a_session(wired: tuple[Api, FakeTelegram]) -> None:
    api, _ = wired
    for method, path in (("GET", "/api/bridges"), ("PUT", "/api/bridges/telegram/token"),
                         ("DELETE", "/api/bridges/telegram/token"), ("POST", "/api/bridges/telegram/pairing"),
                         ("DELETE", "/api/bridges/telegram/identities/1")):
        assert (await api.http.request(method, path)).status_code == 401, path


async def test_the_token_is_checked_kept_and_never_sent_back(wired: tuple[Api, FakeTelegram]) -> None:
    api, _ = wired
    await api.sign_in()
    bad = await api.send("PUT", "/api/bridges/telegram/token", {"token": "1:WRONG"})
    assert bad.status_code == 409 and "did not work" in bad.json()["error"] and TOKEN not in bad.text
    assert (await api.send("PUT", "/api/bridges/telegram/token", {"token": ""})).status_code == 400
    good = await api.send("PUT", "/api/bridges/telegram/token", {"token": TOKEN})
    assert good.json() == {"bot": "lilly_test_bot"}
    status = (await api.get("/api/bridges")).json()["telegram"]
    assert status["token_set"] is True and status["bot"] == "lilly_test_bot" and TOKEN not in str(status)
    assert api.runtime.keys.get(TOKEN_REF) is not None
    assert (await api.send("DELETE", "/api/bridges/telegram/token")).status_code == 200
    assert (await api.get("/api/bridges")).json()["telegram"]["token_set"] is False


async def test_pairing_gives_a_code_only_when_a_token_is_set(wired: tuple[Api, FakeTelegram]) -> None:
    api, _ = wired
    await api.sign_in()
    assert (await api.send("POST", "/api/bridges/telegram/pairing")).status_code == 409
    await api.send("PUT", "/api/bridges/telegram/token", {"token": TOKEN})
    made = (await api.send("POST", "/api/bridges/telegram/pairing")).json()
    assert len(made["code"]) == 8 and made["pairing_until"] > 0
    assert (await api.get("/api/bridges")).json()["telegram"]["pairing_until"] == made["pairing_until"]


async def test_unpairing_an_unknown_or_bad_id(wired: tuple[Api, FakeTelegram]) -> None:
    api, _ = wired
    await api.sign_in()
    assert (await api.send("DELETE", "/api/bridges/telegram/identities/5")).status_code == 404
    assert (await api.send("DELETE", "/api/bridges/telegram/identities/abc")).status_code == 400


async def test_without_a_running_bridge_the_endpoints_say_so(api: Api) -> None:
    await api.sign_in()
    r = await api.get("/api/bridges")
    assert r.status_code == 409 and "not available" in r.json()["error"]


async def test_the_interface_types_match_what_the_server_sends(wired: tuple[Api, FakeTelegram]) -> None:
    api, _ = wired
    await api.sign_in()
    await api.send("PUT", "/api/bridges/telegram/token", {"token": TOKEN})
    sent = (await api.get("/api/bridges")).json()["telegram"]
    assert _fields("BridgeStatus") == set(sent)
    assert _fields("BridgeIdentity") == {"user_id", "label", "paired_at"}
