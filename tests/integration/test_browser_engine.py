"""Browser tools inside a real task: approvals follow the chosen mode, a page taints the task, Stop all closes it."""
from __future__ import annotations

import asyncio
import glob
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from lilly.domain.browser_policy import BrowserMode, BrowserSettings
from lilly.domain.labels import Mode
from lilly.domain.tasks import TaskState
from lilly.store import tasks
from lilly.tools.browser.actions import browser_tools
from lilly.tools.browser.chrome import BrowserProcess
from lilly.tools.browser.guard import NetworkGuard
from lilly.tools.browser.manager import BrowserManager
from tests.browser_site.server import Site
from tests.helpers import plan, step
from tests.integration.lab import Lab

CHROME = next(iter(sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))), os.environ.get("LILLY_CHROME", ""))
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not CHROME or not Path(CHROME).is_file(), reason="no Chromium")]


GOAL = "use the browser to open a page, find an element on it, click or type into it, and write a file"


class Web:
    def __init__(self, lab: Lab, site: Site, manager: BrowserManager, cfg: list[BrowserSettings]) -> None:
        self.lab, self.site, self.manager, self.cfg = lab, site, manager, cfg

    async def run_plain_click(self) -> object:
        self.lab.engine.completer.replies = ["done"]
        return await self.lab.submit(
            step("s1", "browser.open", url=self.site.base + "/"),
            step("s2", "browser.find", query="plain button"),
            step("s3", "browser.click", target="$s2.output"),
            step("s4", "llm.work", task="x", input="$s3.output"), mode=Mode.ASK, goal=GOAL)


@pytest.fixture
async def web(lab: Lab) -> AsyncIterator[Web]:
    site, cfg = Site(), [BrowserSettings(idle_quit_s=30)]
    manager = BrowserManager(lambda: cfg[0], NetworkGuard(allow_private=True), lambda c: BrowserProcess(CHROME, True))
    lab.engine.tools.update({t.name: t for t in browser_tools(manager, lambda: cfg[0])})
    yield Web(lab, site, manager, cfg)
    await manager.close_all()
    site.close()


async def test_in_ask_every_mode_a_click_waits_for_the_exact_target_to_be_approved(web: Web) -> None:
    row = await web.run_plain_click()
    pending = await web.lab.engine.wait_for_approval(timeout=30)
    assert "browser.click" in pending.summary and "every action asks" in pending.summary
    await web.lab.engine.approvals.decide(pending.id, approve=True, payload_hash=pending.payload_hash)
    done = await web.lab.engine.wait(row.id, timeout=30)
    assert done.state is TaskState.DONE, done.error
    assert done.tainted                                    # a page was read, so the task counts as having read outside text
    assert [s.status for s in tasks.list_steps(web.lab.engine.db.reader, row.id)] == ["done"] * 4


async def test_in_ask_risky_mode_a_plain_click_goes_ahead_without_asking(web: Web) -> None:
    web.cfg[0] = BrowserSettings(mode=BrowserMode.ASK_RISKY, idle_quit_s=30)
    row = await web.run_plain_click()
    done = await web.lab.engine.wait(row.id, timeout=30)
    assert done.state is TaskState.DONE, done.error
    assert web.lab.engine.approvals.pending() == []


async def test_in_allowlist_mode_the_listed_site_is_automatic_and_another_is_not(web: Web) -> None:
    web.cfg[0] = BrowserSettings(mode=BrowserMode.ALLOWLIST, allow_hosts=("127.0.0.1",), idle_quit_s=30)
    done = await web.lab.engine.wait((await web.run_plain_click()).id, timeout=30)   # type: ignore[attr-defined]
    assert done.state is TaskState.DONE and web.lab.engine.approvals.pending() == []
    web.cfg[0] = BrowserSettings(mode=BrowserMode.ALLOWLIST, allow_hosts=("example.org",), idle_quit_s=30)
    row = await web.run_plain_click()
    pending = await web.lab.engine.wait_for_approval(timeout=30)
    assert "not on your list" in pending.summary
    await web.lab.engine.approvals.decide(pending.id, approve=False, payload_hash=pending.payload_hash)
    assert (await web.lab.engine.wait(row.id, timeout=30)).state is TaskState.CANCELLED


async def test_a_password_cannot_be_typed_even_when_everything_is_auto_approved(web: Web) -> None:
    web.cfg[0] = BrowserSettings(mode=BrowserMode.ALLOWLIST, allow_hosts=("127.0.0.1",), idle_quit_s=30)
    web.lab.engine.completer.replies = [plan(answer="I cannot type a password for you.")]    # the replan
    row = await web.lab.submit(step("s1", "browser.open", url=web.site.base + "/"),
                               step("s2", "browser.find", query="password"),
                               step("s3", "browser.type", target="$s2.output", text="hunter2"),
                               step("s4", "llm.work", task="x", input="$s3.output"), goal=GOAL)
    done = await web.lab.engine.wait(row.id, timeout=30)
    assert done.state is TaskState.DONE and "cannot type a password" in (done.answer or "")
    failed = next(s for s in tasks.list_steps(web.lab.engine.db.reader, row.id) if s.step_id == "s3")
    assert failed.status == "failed" and "password or card" in (failed.error or "")
    assert web.site.posts == [] and web.lab.engine.approvals.pending() == []


async def test_a_page_taints_the_task_so_a_later_file_write_still_asks(web: Web, tmp_path: Path) -> None:
    web.cfg[0] = BrowserSettings(mode=BrowserMode.ALLOWLIST, allow_hosts=("127.0.0.1",), idle_quit_s=30)
    target = web.lab.engine.root / "note.txt"
    web.lab.engine.completer.replies = ["ok"]
    row = await web.lab.submit(step("s1", "browser.open", url=web.site.base + "/injected"),
                               step("s2", "fs.write", path=str(target), content="from the page"),
                               step("s3", "llm.work", task="x", input="$s1.output"), mode=Mode.OPEN, goal=GOAL)
    pending = await web.lab.engine.wait_for_approval(timeout=30)
    assert "fs.write" in pending.summary and not target.exists()
    await web.lab.engine.approvals.decide(pending.id, approve=False, payload_hash=pending.payload_hash)
    await web.lab.engine.wait(row.id, timeout=30)
    assert not target.exists()


async def test_stop_all_closes_the_browser(web: Web) -> None:
    web.cfg[0] = BrowserSettings(mode=BrowserMode.ALLOWLIST, allow_hosts=("127.0.0.1",), idle_quit_s=30)
    await web.run_plain_click()
    async with asyncio.timeout(30):
        while web.manager._proc is None:
            await asyncio.sleep(0.05)
    proc = web.manager._proc
    await web.lab.engine.orchestrator.stop_all()
    await web.manager.close_all()
    assert not proc.alive and web.manager._cdp is None


async def test_the_stop_all_endpoint_closes_the_browser(api) -> None:  # type: ignore[no-untyped-def]
    await api.sign_in()
    closed: list[bool] = []

    async def close_all() -> None:
        closed.append(True)

    api.runtime.browser.close_all = close_all
    assert (await api.send("POST", "/api/stop")).status_code == 200
    assert closed == [True]
