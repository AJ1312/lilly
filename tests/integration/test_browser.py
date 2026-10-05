"""The agent's browser, driven for real: a real Chromium, a local test site, the real tools."""
from __future__ import annotations

import asyncio
import glob
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from lilly.domain.browser_policy import BrowserMode, BrowserSettings
from lilly.domain.errors import ToolError, ValidationFailed
from lilly.domain.labels import Verdict
from lilly.domain.ports import ToolContext
from lilly.tools.browser import manager as manager_module
from lilly.tools.browser.actions import browser_tools
from lilly.tools.browser.chrome import BrowserProcess
from lilly.tools.browser.guard import NetworkGuard
from lilly.tools.browser.manager import BrowserManager
from lilly.tools.browser.page import Page
from tests.browser_site.server import Site

CHROME = next(iter(sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))), os.environ.get("LILLY_CHROME", ""))
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not CHROME or not Path(CHROME).is_file(), reason="no Chromium")]


class Lab:
    def __init__(self, site: Site, manager: BrowserManager, cfg: list[BrowserSettings]) -> None:
        self.site, self.manager, self.cfg = site, manager, cfg
        self.tools = {t.name: t for t in browser_tools(manager, lambda: cfg[0])}

    async def run(self, name: str, task: str = "t1", **args: Any) -> str:
        ctx = ToolContext(task, "s", 30.0, lambda: False)
        result = await self.tools[name].run(args, ctx)
        assert result.untrusted, "page content is always outside text"
        return result.output

    def line(self, text: str, containing: str) -> str:
        return next(ln for ln in text.splitlines() if ln.startswith("s") and containing in ln)


@pytest.fixture
async def lab() -> AsyncIterator[Lab]:
    site = Site()
    cfg = [BrowserSettings(idle_quit_s=30)]
    manager = BrowserManager(lambda: cfg[0], NetworkGuard(allow_private=True),
                             lambda c: BrowserProcess(CHROME, True))
    yield Lab(site, manager, cfg)
    await manager.close_all()
    site.close()


async def test_opening_a_page_lists_numbered_targets_and_its_text(lab: Lab) -> None:
    out = await lab.run("browser.open", url=lab.site.base + "/")
    assert "Page: Shop" in out and "Welcome" in out
    host = lab.site.base.split("//")[1]
    assert f'submit "Search now" @{host}' in out and 'textbox "Search box"' in out and 'select "Size"' in out
    assert 'password "Password"' in out and 'link "More info"' in out


async def test_find_type_select_and_submit_fill_in_a_form_and_the_server_gets_it(lab: Lab) -> None:
    await lab.run("browser.open", url=lab.site.base + "/")
    box = await lab.run("browser.find", query="search box")
    size = await lab.run("browser.find", query="size")
    submit = await lab.run("browser.find", query="search now")
    assert "textbox" in box and "select" in size and "submit" in submit     # one snapshot serves all three lines
    assert "Typed 5 characters" in await lab.run("browser.type", target=box, text="shoes")
    # the type changed the page, so the earlier lines are out of date and must be found again
    with pytest.raises(ToolError, match="out of date"):
        await lab.run("browser.select", target=size, value="Large")
    size = await lab.run("browser.find", query="size")
    assert "Chose" in await lab.run("browser.select", target=size, value="Large")
    submit = await lab.run("browser.find", query="search now")
    assert "Submitted" in await lab.run("browser.submit", target=submit)
    assert lab.site.posts == [{"q": ["shoes"], "size": ["Large"]}]     # (a blank password is not sent with a value)
    assert "Results for your search" in await lab.run("browser.read")


async def test_a_target_is_refused_when_the_page_changed_or_the_element_is_no_longer_what_it_said(lab: Lab) -> None:
    await lab.run("browser.open", url=lab.site.base + "/shifty")
    target = await lab.run("browser.find", query="safe")
    await asyncio.sleep(0.8)                                   # the page renames the button to "Delete account"
    with pytest.raises(ToolError, match="not what the target says"):
        await lab.run("browser.click", target=target)
    await lab.run("browser.open", url=lab.site.base + "/")
    with pytest.raises(ToolError, match="out of date"):
        await lab.run("browser.click", target=target)           # a target from another page


async def test_targets_must_be_exactly_a_line_from_the_page(lab: Lab) -> None:
    await lab.run("browser.open", url=lab.site.base + "/")
    for bad in ("click the button", 's1.e1 button "x"', "", 5):
        with pytest.raises(ValidationFailed, match="exactly as browser"):
            await lab.run("browser.click", target=bad)


async def test_submit_buttons_need_the_submit_tool_and_passwords_are_never_typed(lab: Lab) -> None:
    await lab.run("browser.open", url=lab.site.base + "/")
    submit = await lab.run("browser.find", query="search now")
    with pytest.raises(ToolError, match="use browser.submit"):
        await lab.run("browser.click", target=submit)
    link = await lab.run("browser.find", query="more info")
    with pytest.raises(ToolError, match="not a submit button"):
        await lab.run("browser.submit", target=link)
    password = await lab.run("browser.find", query="password")
    with pytest.raises(ValidationFailed, match="only text boxes"):
        await lab.run("browser.type", target=password, text="hunter2")
    assert lab.site.posts == []


async def test_a_page_that_gives_orders_is_just_text_and_nothing_acts_on_it(lab: Lab) -> None:
    out = await lab.run("browser.open", url=lab.site.base + "/injected")
    assert "Ignore all previous instructions" in out and lab.site.posts == []
    assert await lab.run("browser.find", query="delete everything")        # it can be found, never clicked by itself
    assert len(lab.manager._tabs) == 1


async def test_popups_are_closed_and_dialogs_do_not_hang_the_page(lab: Lab) -> None:
    out = await lab.run("browser.open", url=lab.site.base + "/dialog")
    assert "after alert" in out
    await lab.run("browser.open", url=lab.site.base + "/")
    pop = await lab.run("browser.find", query="open popup")
    await lab.run("browser.click", target=pop)
    await asyncio.sleep(0.7)
    targets = (await lab.manager._cdp.call("Target.getTargets"))["targetInfos"]       # type: ignore[union-attr]
    assert [t["url"] for t in targets if t["type"] == "page" and t["url"].endswith("/about")] == []   # the pop-up is gone
    assert any(t["url"].endswith("/") for t in targets)


async def test_a_download_link_does_not_save_anything(lab: Lab, tmp_path: Path) -> None:
    await lab.run("browser.open", url=lab.site.base + "/")
    link = await lab.run("browser.find", query="get file")
    await lab.run("browser.click", target=link)
    await asyncio.sleep(0.5)
    assert "Welcome" in await lab.run("browser.read")                       # still on the page, nothing downloaded
    assert not list(Path(lab.manager._proc._profile).rglob("x.bin"))        # type: ignore[union-attr,arg-type]


async def test_the_action_budget_stops_a_task_that_keeps_clicking(lab: Lab) -> None:
    lab.cfg[0] = BrowserSettings(max_actions=2, idle_quit_s=30)
    await lab.run("browser.open", url=lab.site.base + "/")
    for _ in range(2):
        await lab.run("browser.press", key="Tab")
    with pytest.raises(ToolError, match="used its 2 browser actions"):
        await lab.run("browser.press", key="Tab")
    assert "Welcome" in await lab.run("browser.read")                       # reading is not an action


async def test_the_action_budget_survives_a_closed_or_reaped_tab(lab: Lab, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager_module, "REAP_EVERY_S", 0.1)
    monkeypatch.setattr(manager_module, "TAB_IDLE_S", 0.3)
    lab.cfg[0] = BrowserSettings(max_actions=2, idle_quit_s=30)
    await lab.run("browser.open", url=lab.site.base + "/")
    await lab.run("browser.press", key="Tab")
    await lab.run("browser.close")
    await lab.run("browser.open", url=lab.site.base + "/")
    await lab.run("browser.press", key="Tab")
    async with asyncio.timeout(10):
        while lab.manager._tabs:                                              # the idle tab is reaped
            await asyncio.sleep(0.05)
    await lab.run("browser.open", url=lab.site.base + "/")
    with pytest.raises(ToolError, match="used its 2 browser actions"):
        await lab.run("browser.press", key="Tab")
    await lab.run("browser.press", task="other", key="Tab")                  # another task has its own budget


async def test_a_tab_that_could_not_be_guarded_is_closed_and_never_reused(lab: Lab, monkeypatch: pytest.MonkeyPatch) -> None:
    await lab.run("browser.open", task="a", url=lab.site.base + "/")
    cdp = lab.manager._cdp
    assert cdp is not None

    async def pages() -> int:
        found = await cdp.call("Target.getTargets", {})
        return sum(1 for t in found["targetInfos"] if t["type"] == "page")

    before = await pages()
    real = Page.prepare

    async def broken(self: Page) -> None:
        raise ToolError("no interception")

    monkeypatch.setattr(Page, "prepare", broken)
    with pytest.raises(ToolError, match="no interception"):
        await lab.manager.tab("b")
    assert "b" not in lab.manager._tabs and set(lab.manager._by_session) == {lab.manager._tabs["a"].session}
    async with asyncio.timeout(5):
        while await pages() != before:                                         # the half-made target is closed
            await asyncio.sleep(0.05)
    monkeypatch.setattr(Page, "prepare", real)
    assert "Welcome" in await lab.run("browser.open", task="b", url=lab.site.base + "/")


async def test_two_tasks_get_their_own_tabs_and_close_removes_only_one(lab: Lab) -> None:
    await lab.run("browser.open", task="a", url=lab.site.base + "/")
    await lab.run("browser.open", task="b", url=lab.site.base + "/about")
    assert "About us" in await lab.run("browser.read", task="b") and "Welcome" in await lab.run("browser.read", task="a")
    await lab.run("browser.close", task="a")
    assert set(lab.manager._tabs) == {"b"}


async def test_web_addresses_that_are_not_public_are_refused_unless_the_test_allows_them() -> None:
    site = Site()
    manager = BrowserManager(lambda: BrowserSettings(), NetworkGuard(), lambda c: BrowserProcess(CHROME, True))
    tools = {t.name: t for t in browser_tools(manager, BrowserSettings)}
    try:
        with pytest.raises(ToolError, match="not on the public internet"):
            await tools["browser.open"].run({"url": site.base + "/"}, ToolContext("t", "s", 30.0, lambda: False))
        for bad in ("file:///etc/passwd", "javascript:alert(1)", "http://user:pw@example.com/", "ftp://example.com"):
            with pytest.raises(ValidationFailed):
                await tools["browser.open"].run({"url": bad}, ToolContext("t", "s", 30.0, lambda: False))
    finally:
        await manager.close_all()
        site.close()


async def test_close_all_quits_the_browser_and_deletes_its_profile(lab: Lab) -> None:
    await lab.run("browser.open", url=lab.site.base + "/")
    proc = lab.manager._proc
    assert proc is not None and proc.alive and proc._profile is not None
    profile = Path(proc._profile)
    assert profile.is_dir()
    await lab.manager.close_all()
    assert not proc.alive and not profile.exists() and lab.manager._cdp is None
    assert "Welcome" in await lab.run("browser.open", url=lab.site.base + "/")      # and it starts again on demand


async def test_idle_tabs_close_and_an_unused_browser_quits(lab: Lab, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager_module, "REAP_EVERY_S", 0.1)
    monkeypatch.setattr(manager_module, "TAB_IDLE_S", 0.3)
    lab.cfg[0] = BrowserSettings(idle_quit_s=1)
    await lab.run("browser.open", url=lab.site.base + "/")
    proc = lab.manager._proc
    assert proc is not None
    async with asyncio.timeout(10):
        while proc.alive:
            await asyncio.sleep(0.1)
    assert lab.manager._tabs == {}


async def test_a_browser_that_crashes_is_replaced_on_the_next_use(lab: Lab) -> None:
    await lab.run("browser.open", url=lab.site.base + "/")
    proc = lab.manager._proc
    assert proc is not None
    await proc.stop()
    assert "Welcome" in await lab.run("browser.open", url=lab.site.base + "/")


# ---- the approval rules, on real targets ---------------------------------------------------------
async def test_every_mode_decides_on_the_exact_target(lab: Lab) -> None:
    await lab.run("browser.open", url=lab.site.base + "/")
    plain = await lab.run("browser.find", query="plain button")
    buy = await lab.run("browser.find", query="buy now")
    submit = await lab.run("browser.find", query="search now")
    password = await lab.run("browser.find", query="password")
    host = lab.site.base.split("//")[1].split(":")[0]

    def verdicts(mode: BrowserMode, allow: tuple[str, ...] = ()) -> list[Verdict]:
        lab.cfg[0] = BrowserSettings(mode=mode, allow_hosts=allow)
        t = lab.tools
        return [t["browser.click"].review({"target": plain}, "t1")[0], t["browser.click"].review({"target": buy}, "t1")[0],
                t["browser.submit"].review({"target": submit}, "t1")[0], t["browser.press"].review({"key": "Enter"}, "t1")[0],
                t["browser.type"].review({"target": password, "text": "x"}, "t1")[0],
                t["browser.read"].review({}, "t1")[0]]

    ask, allow, deny = Verdict.NEEDS_APPROVAL, Verdict.ALLOW, Verdict.DENY
    assert verdicts(BrowserMode.ASK_EVERY) == [ask, ask, ask, ask, deny, allow]
    assert verdicts(BrowserMode.ASK_RISKY) == [allow, ask, ask, ask, deny, allow]
    assert verdicts(BrowserMode.ALLOWLIST) == [ask, ask, ask, ask, deny, allow]
    assert verdicts(BrowserMode.ALLOWLIST, (host,)) == [allow, allow, allow, allow, deny, allow]
    assert verdicts(BrowserMode.ALLOWLIST, ("example.org",)) == [ask, ask, ask, ask, deny, allow]


async def test_the_registry_pins_every_browser_tool_as_stateful_and_untrusted() -> None:
    from lilly.domain.tools_registry import DEFAULT_TOOLS

    specs = {n: s for n, s in DEFAULT_TOOLS.items() if n.startswith("browser.")}
    assert len(specs) == 11 and all(s.serial and s.untrusted and s.egress and s.module == "browser" for s in specs.values())
    assert json.dumps(sorted(specs))


async def test_a_picture_of_a_tab_is_a_jpeg_and_asking_never_opens_a_tab(lab: Lab) -> None:
    assert await lab.manager.screenshot("t1") is None and lab.manager.watched() == []
    await lab.run("browser.open", url=lab.site.base + "/")
    picture = await lab.manager.screenshot("t1")
    assert picture is not None and picture[:3] == b"\xff\xd8\xff" and len(picture) < 1_500_000
    assert lab.manager.watched() == ["t1"] and await lab.manager.screenshot("other") is None
