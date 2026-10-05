"""The browser.* tools. Each is a thin step over a Page; the rules about when an action asks live in
domain/browser_policy.py and are applied through `review`, on the exact target the step will act on."""
from __future__ import annotations

from collections.abc import Callable, Mapping

from lilly.domain.browser_policy import Action, BrowserSettings, judge, parse_target
from lilly.domain.errors import ValidationFailed
from lilly.domain.labels import Label, Verdict
from lilly.domain.ports import ToolContext, ToolResult
from lilly.tools.base import Tool, str_arg
from lilly.tools.browser.manager import BrowserManager


class BrowserTool(Tool):
    """Common parts: the manager, the settings, and one result shape (page content is untrusted text)."""

    action = Action.READ

    def __init__(self, manager: BrowserManager, settings: Callable[[], BrowserSettings]) -> None:
        self._m, self._settings = manager, settings

    def review(self, args: Mapping[str, object], task_id: str) -> tuple[Verdict, str]:
        cfg = self._settings()
        target = parse_target(args.get("target"))
        if target is not None:
            return judge(self.action, target.role, target.name, target.host, cfg)
        if self.action is Action.READ:
            return Verdict.ALLOW, "ok"
        return judge(self.action, "", str(args.get("key", "")), self._m.host_of(task_id), cfg)

    @staticmethod
    def _out(text: str) -> ToolResult:
        return ToolResult(text, Label.PUBLIC, True)   # whatever a page says is outside text


class OpenTool(BrowserTool):
    name = "browser.open"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        tab = await self._m.tab(ctx.task_id)
        async with tab.lock:
            snap = await tab.page.open(str_arg(args, "url", max_len=2000).strip())
            self._m.touch(tab)
        return self._out(snap.render())


class ReadTool(BrowserTool):
    name = "browser.read"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        tab = await self._m.tab(ctx.task_id)
        async with tab.lock:
            snap = await tab.page.snapshot(fresh=True)
            self._m.touch(tab)
        return self._out(snap.render())


class FindTool(BrowserTool):
    name = "browser.find"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        tab = await self._m.tab(ctx.task_id)
        async with tab.lock:
            line = await tab.page.find(str_arg(args, "query", max_len=200))
            self._m.touch(tab)
        return self._out(line)


class _Acting(BrowserTool):
    """A tool that acts on the page; each use counts against the task's action budget."""

    async def _tab(self, ctx: ToolContext):  # type: ignore[no-untyped-def]
        tab = await self._m.tab(ctx.task_id)
        self._m.spend(ctx.task_id)
        return tab


class ClickTool(_Acting):
    name = "browser.click"
    action = Action.INTERACT

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        tab = await self._tab(ctx)
        async with tab.lock:
            done = await tab.page.click(args.get("target"))
            self._m.touch(tab)
        return self._out(done)


class SubmitTool(_Acting):
    name = "browser.submit"
    action = Action.SUBMIT

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        tab = await self._tab(ctx)
        async with tab.lock:
            done = await tab.page.submit(args.get("target"))
            self._m.touch(tab)
        return self._out(done)


class TypeTool(_Acting):
    name = "browser.type"
    action = Action.TYPE

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        text = args.get("text")
        if not isinstance(text, str):
            raise ValidationFailed("'text' must be text")
        tab = await self._tab(ctx)
        async with tab.lock:
            done = await tab.page.type(args.get("target"), text, str(args.get("clear", "")).lower() == "true")
            self._m.touch(tab)
        return self._out(done)


class SelectTool(_Acting):
    name = "browser.select"
    action = Action.INTERACT

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        tab = await self._tab(ctx)
        async with tab.lock:
            done = await tab.page.select(args.get("target"), str_arg(args, "value", max_len=200))
            self._m.touch(tab)
        return self._out(done)


class PressTool(_Acting):
    name = "browser.press"
    action = Action.PRESS

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        tab = await self._tab(ctx)
        async with tab.lock:
            done = await tab.page.press(str_arg(args, "key", max_len=20))
            self._m.touch(tab)
        return self._out(done)


class ScrollTool(BrowserTool):
    name = "browser.scroll"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        tab = await self._m.tab(ctx.task_id)
        async with tab.lock:
            done = await tab.page.scroll(str_arg(args, "direction", max_len=10))
            self._m.touch(tab)
        return self._out(done)


class BackTool(BrowserTool):
    name = "browser.back"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        tab = await self._m.tab(ctx.task_id)
        async with tab.lock:
            done = await tab.page.back()
            self._m.touch(tab)
        return self._out(done)


class CloseTool(BrowserTool):
    name = "browser.close"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        await self._m.close_task(ctx.task_id)
        return self._out("Closed the browser tab.")


def browser_tools(manager: BrowserManager, settings: Callable[[], BrowserSettings]) -> list[Tool]:
    kinds = (OpenTool, ReadTool, FindTool, ClickTool, TypeTool, SelectTool, PressTool, SubmitTool, ScrollTool,
             BackTool, CloseTool)
    return [k(manager, settings) for k in kinds]
