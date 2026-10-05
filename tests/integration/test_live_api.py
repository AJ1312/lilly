"""Watching the agent's browser from the interface: signed-in only, read-only, nothing when there is no tab."""
from __future__ import annotations

import pytest

from tests.integration.conftest import Api

pytestmark = pytest.mark.asyncio


class StubBrowser:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def watched(self) -> list[str]:
        return ["t1"]

    def host_of(self, task_id: str) -> str:
        return "example.com"

    async def close_all(self) -> None:
        return None

    async def screenshot(self, task_id: str) -> bytes | None:
        self.asked.append(task_id)
        return b"\xff\xd8\xffpicture" if task_id == "t1" else None


async def test_live_endpoints_need_a_session(api: Api) -> None:
    assert (await api.get("/api/live")).status_code == 401
    assert (await api.get("/api/live/t1/frame")).status_code == 401


async def test_the_list_and_a_frame(api: Api) -> None:
    api.runtime.browser = StubBrowser()  # type: ignore[assignment]
    await api.sign_in()
    assert (await api.get("/api/live")).json() == {"tasks": [{"task_id": "t1", "host": "example.com"}]}
    shot = await api.get("/api/live/t1/frame")
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/jpeg"
    assert shot.headers["cache-control"] == "no-store" and shot.content.startswith(b"\xff\xd8\xff")
    assert (await api.get("/api/live/none/frame")).status_code == 404


async def test_live_is_read_only(api: Api) -> None:
    await api.sign_in()
    assert (await api.send("POST", "/api/live/t1/frame")).status_code in (404, 405)
