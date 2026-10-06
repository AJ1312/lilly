"""BrowserManager: one browser for Lilly, started when first needed, one tab per task, quit when idle.

The browser starts with a throwaway profile, is told to refuse downloads and to close any pop-up window, and every
request any page makes is checked by the NetworkGuard first. Tabs close after two quiet minutes and the browser quits
after the idle time in Settings. `close_all` is what Stop all and shutdown call."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from lilly.domain.browser_policy import BrowserSettings
from lilly.domain.errors import ToolError
from lilly.tools.browser.cdp import Cdp
from lilly.tools.browser.chrome import BrowserProcess, find_browser
from lilly.tools.browser.guard import NetworkGuard
from lilly.tools.browser.page import Page

log = logging.getLogger("lilly.browser")
TAB_IDLE_S = 120.0
REAP_EVERY_S = 15.0
SHOT_TIMEOUT_S = 5.0
MAX_COUNTED_TASKS = 1024


class _Tab:
    def __init__(self, page: Page, session: str) -> None:
        self.page, self.session = page, session
        self.used = time.monotonic()
        self.lock = asyncio.Lock()


class BrowserManager:
    def __init__(self, settings: Callable[[], BrowserSettings], guard: NetworkGuard | None = None,
                 start: Callable[[BrowserSettings], BrowserProcess] | None = None) -> None:
        self._settings, self._guard = settings, guard or NetworkGuard()
        self._start = start or (lambda cfg: BrowserProcess(find_browser(cfg.chrome_path), cfg.headless))
        self._proc: BrowserProcess | None = None
        self._cdp: Cdp | None = None
        self._tabs: dict[str, _Tab] = {}
        self._by_session: dict[str, _Tab] = {}
        self._spent: OrderedDict[str, int] = OrderedDict()      # task id -> acting steps used, oldest task dropped first
        self._lock = asyncio.Lock()
        self._reaper: asyncio.Task[None] | None = None
        self._last_use = time.monotonic()

    # ---- tabs -----------------------------------------------------------------------------------
    async def tab(self, task_id: str) -> _Tab:
        async with self._lock:
            self._last_use = time.monotonic()
            if (tab := self._tabs.get(task_id)) is not None and self._alive():
                return tab
            await self._ensure_browser()
            assert self._cdp is not None
            made = await self._cdp.call("Target.createTarget", {"url": "about:blank"})
            target_id = str(made["targetId"])
            attached = await self._cdp.call("Target.attachToTarget", {"targetId": target_id, "flatten": True})
            session = str(attached["sessionId"])
            page = Page(self._cdp, session, target_id, self._guard, lambda: None)
            try:
                await page.prepare()                    # until the tab is guarded it must not be reachable
            except BaseException:
                await page.close()
                raise
            tab = _Tab(page, session)
            self._tabs[task_id], self._by_session[session] = tab, tab
            return tab

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.alive and self._cdp is not None and not self._cdp.closed

    def watched(self) -> list[str]:
        """The tasks that have a tab open right now."""
        return [task_id for task_id in self._tabs] if self._alive() else []

    async def screenshot(self, task_id: str) -> bytes | None:
        """A picture of the task's tab, or None when it has none. Never opens a tab or keeps the browser awake."""
        tab = self._tabs.get(task_id)
        if tab is None or not self._alive():
            return None
        try:        # reading a picture does not disturb an action in progress, so it does not wait for the tab's lock
            async with asyncio.timeout(SHOT_TIMEOUT_S):
                return await tab.page.screenshot()
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError("the page could not be shown right now") from exc

    async def dom_snapshot(self, task_id: str) -> dict[str, Any] | None:
        """Return the current browser DOM snapshot when this task already owns a tab."""
        tab = self._tabs.get(task_id)
        if tab is None or not self._alive():
            return None
        snap = await tab.page.snapshot()
        return {"url": snap.url, "title": snap.title, "text": snap.text, "elements": list(snap.elements)}

    def host_of(self, task_id: str) -> str:
        tab = self._tabs.get(task_id)
        return tab.page.host if tab else ""

    def spend(self, task_id: str) -> None:
        """Count one acting step against the task's budget. The count outlives the tab: closing or reaping a tab, or
        a browser restart, does not give a task a fresh budget. Only Stop all and shutdown do."""
        used = self._spent.get(task_id, 0)
        if used >= self._settings().max_actions:
            raise ToolError(f"this task used its {self._settings().max_actions} browser actions; ask for more in Settings")
        self._spent[task_id] = used + 1
        self._spent.move_to_end(task_id)
        while len(self._spent) > MAX_COUNTED_TASKS:
            self._spent.popitem(last=False)

    def touch(self, tab: _Tab) -> None:
        tab.used = self._last_use = time.monotonic()

    # ---- the browser ------------------------------------------------------------------------------
    async def _ensure_browser(self) -> None:
        if self._alive():
            return
        await self._shutdown()
        cfg = self._settings()
        proc = self._start(cfg)
        try:
            endpoint = await proc.start()
            cdp = await Cdp.connect(endpoint)
        except BaseException:
            await proc.stop()
            raise
        self._proc, self._cdp = proc, cdp
        for method, handler in (("Fetch.requestPaused", self._on_request), ("Page.frameNavigated", self._on_navigated),
                                ("Page.frameStartedLoading", self._on_loading), ("Page.loadEventFired", self._on_loaded),
                                ("Page.frameStoppedLoading", self._on_loaded),
                                ("Page.javascriptDialogOpening", self._on_dialog),
                                ("Target.targetCreated", self._on_target)):
            cdp.on(method, handler)
        await cdp.call("Target.setDiscoverTargets", {"discover": True})
        await cdp.call("Browser.setDownloadBehavior", {"behavior": "deny"})
        self._reaper = asyncio.create_task(self._reap(), name="lilly-browser-reaper")

    async def _shutdown(self) -> None:
        reaper, self._reaper = self._reaper, None
        if reaper is not None and reaper is not asyncio.current_task():
            reaper.cancel()
            await asyncio.gather(reaper, return_exceptions=True)
        cdp, proc, self._cdp, self._proc = self._cdp, self._proc, None, None
        self._tabs.clear()
        self._by_session.clear()
        if cdp is not None:
            await cdp.close()
        if proc is not None:
            await proc.stop()

    async def close_task(self, task_id: str) -> None:
        async with self._lock:
            tab = self._tabs.pop(task_id, None)
            if tab is not None:
                self._by_session.pop(tab.session, None)
                await tab.page.close()

    async def close_all(self) -> None:
        """Close every tab and quit the browser: Stop all, and shutting Lilly down."""
        async with self._lock:
            await self._shutdown()
            self._spent.clear()

    async def _reap(self) -> None:
        while True:
            await asyncio.sleep(REAP_EVERY_S)
            now = time.monotonic()
            for task_id, tab in list(self._tabs.items()):
                if now - tab.used > TAB_IDLE_S and not tab.lock.locked():
                    await self.close_task(task_id)
            if not self._tabs and now - self._last_use > self._settings().idle_quit_s:
                async with self._lock:
                    if not self._tabs:
                        await self._shutdown()
                return
            if not self._alive():
                async with self._lock:
                    await self._shutdown()
                return

    # ---- browser events -------------------------------------------------------------------------------
    async def _on_request(self, params: dict[str, Any], session: str | None) -> None:
        assert self._cdp is not None
        url, kind = str(params["request"]["url"]), str(params.get("resourceType", ""))
        reason = await self._guard.refusal(url, kind)
        rid = params["requestId"]
        with contextlib.suppress(ToolError):
            if reason is None:
                await self._cdp.call("Fetch.continueRequest", {"requestId": rid}, session)
            else:
                await self._cdp.call("Fetch.failRequest", {"requestId": rid, "errorReason": "BlockedByClient"}, session)

    async def _on_navigated(self, params: dict[str, Any], session: str | None) -> None:
        if session in self._by_session and "parentId" not in params.get("frame", {}):
            self._by_session[session].page.navigated()

    async def _on_loading(self, params: dict[str, Any], session: str | None) -> None:
        if session in self._by_session:
            self._by_session[session].page.loading(True)

    async def _on_loaded(self, params: dict[str, Any], session: str | None) -> None:
        if session in self._by_session:
            self._by_session[session].page.loading(False)

    async def _on_dialog(self, params: dict[str, Any], session: str | None) -> None:
        assert self._cdp is not None
        if session in self._by_session:
            self._by_session[session].page.dialogs.append(str(params.get("message", ""))[:200])
        with contextlib.suppress(ToolError):
            await self._cdp.call("Page.handleJavaScriptDialog", {"accept": False}, session)

    async def _on_target(self, params: dict[str, Any], session: str | None) -> None:
        info = params.get("targetInfo", {})
        if info.get("type") == "page" and info.get("openerId") and self._cdp is not None:   # a pop-up
            with contextlib.suppress(ToolError):
                await self._cdp.call("Target.closeTarget", {"targetId": info["targetId"]})
