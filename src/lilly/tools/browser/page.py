"""One browser tab: opens pages, lists their clickable parts as numbered targets, and acts on a target.

A target names a snapshot (`s3`) and an element (`e7`) and repeats the element's role, name and site. An action is
refused when the snapshot is out of date (the page changed, or something else was done since) or when the element is
no longer what the target says, so an old plan can never click something the person did not see."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from lilly.core.lexical import score
from lilly.domain.browser_policy import KEYS, Target, check_url, parse_target
from lilly.domain.errors import ToolError, ValidationFailed
from lilly.tools.browser.cdp import Cdp
from lilly.tools.browser.guard import NetworkGuard

log = logging.getLogger("lilly.browser")

MAX_TEXT = 8000
MAX_ELEMENTS = 150
LOAD_TIMEOUT_S = 25.0
SETTLE_S = 0.35
SHOT_QUALITY = 55          # small on purpose: this is for watching, not for reading
SHOT_MAX_BYTES = 1_500_000
WORLD = "lilly"        # an isolated JavaScript world: the page's own scripts cannot see or change our helpers
_KEY_CODES = {"Enter": (13, "Enter"), "Tab": (9, "Tab"), "Escape": (27, "Escape"), "ArrowDown": (40, "ArrowDown"),
              "ArrowUp": (38, "ArrowUp"), "ArrowLeft": (37, "ArrowLeft"), "ArrowRight": (39, "ArrowRight"),
              "PageDown": (34, "PageDown"), "PageUp": (33, "PageUp"), "Home": (36, "Home"), "End": (35, "End"),
              "Backspace": (8, "Backspace"), "Space": (32, "Space")}

_SNAPSHOT_JS = r"""(() => {
  const clean = t => (t || '').replace(/\s+/g, ' ').replace(/"/g, "'").trim().slice(0, 80);
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const nameOf = e => clean(e.getAttribute('aria-label') || (e.labels && e.labels[0] && e.labels[0].innerText)
    || e.placeholder || (e.tagName === 'INPUT' && ['submit', 'button'].includes(e.type) ? e.value : '')
    || e.innerText || e.title || e.alt || e.name || e.id);
  const roleOf = e => { const t = e.tagName.toLowerCase();
    if (t === 'a') return 'link'; if (t === 'select') return 'select'; if (t === 'textarea') return 'textbox';
    if (t === 'input') { const y = (e.type || 'text').toLowerCase();
      if (y === 'password') return 'password'; if (/(^|\s)cc-/.test(e.autocomplete || '')) return 'card';
      if (y === 'submit' || y === 'image') return 'submit'; if (y === 'button' || y === 'reset') return 'button';
      if (y === 'checkbox' || y === 'radio') return y; if (y === 'file') return 'file'; if (y === 'hidden') return '';
      return 'textbox'; }
    if (t === 'button') return ((e.getAttribute('type') || 'submit') === 'submit' && e.form) ? 'submit' : 'button';
    const r = (e.getAttribute('role') || '').toLowerCase().replace(/[^a-z]/g, '').slice(0, 20); return r || 'button'; };
  globalThis.__fns = {nameOf, roleOf};
  const sel = 'a[href],button,input,select,textarea,summary,[role=button],[role=link],[role=checkbox],[role=menuitem],[role=tab],[role=textbox],[onclick]';
  const found = [];
  for (const e of document.querySelectorAll(sel)) {
    if (found.length >= %(max)d) break; if (!vis(e)) continue;
    const role = roleOf(e); if (role) found.push([e, role, nameOf(e)]);
  }
  globalThis.__els = found.map(f => f[0]);
  const body = document.body ? document.body.innerText : '';
  return JSON.stringify({url: location.href, title: clean(document.title),
    text: body.replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').slice(0, %(text)d),
    els: found.map(f => [f[1], f[2]])});
})()""" % {"max": MAX_ELEMENTS, "text": MAX_TEXT}

_LOCATE_JS = r"""((i) => {
  const e = (globalThis.__els || [])[i]; if (!e || !e.isConnected || !globalThis.__fns) return null;
  e.scrollIntoView({block: 'center', inline: 'center'});
  const r = e.getBoundingClientRect();
  return JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height,
    role: globalThis.__fns.roleOf(e), name: globalThis.__fns.nameOf(e)});
})(%d)"""

_FOCUS_JS = r"""((i, clear) => {
  const e = (globalThis.__els || [])[i]; if (!e || !e.isConnected) return false;
  e.focus(); if (clear && e.select) e.select(); return document.activeElement === e;
})(%d, %s)"""

_SELECT_JS = r"""((i, want) => {
  const e = (globalThis.__els || [])[i]; if (!e || e.tagName !== 'SELECT') return false;
  const w = want.toLowerCase().trim();
  const o = [...e.options].find(o => o.text.trim().toLowerCase() === w || o.value.toLowerCase() === w);
  if (!o) return false; e.value = o.value;
  e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true}));
  return true;
})(%d, %s)"""


@dataclass(frozen=True, slots=True)
class Snapshot:
    ident: int
    url: str
    host: str
    title: str
    text: str
    elements: tuple[tuple[str, str], ...]     # (role, name) by element number

    def token(self, ref: int) -> str:
        role, name = self.elements[ref]
        return f's{self.ident}.e{ref} {role} "{name}" @{self.host}'

    def render(self) -> str:
        lines = [f"Page: {self.title or '(no title)'} — {self.url}", "Elements you can act on:"]
        lines += [self.token(i) for i in range(len(self.elements))] or ["(none)"]
        return "\n".join([*lines, "", "Text on the page:", self.text or "(empty)"])


class Page:
    """A tab. All access is through one lock-free sequence of awaits driven by a single tool call at a time."""

    def __init__(self, cdp: Cdp, session: str, target_id: str, guard: NetworkGuard, on_navigated: Callable[[], None]) -> None:
        self._cdp, self._session, self.target_id, self._guard = cdp, session, target_id, guard
        self._on_navigated = on_navigated
        self._world: int | None = None
        self._current: Snapshot | None = None
        self._counter = 0
        self._loading = False
        self.dialogs: list[str] = []
        self.host = ""                   # the site of the page last read, for the policy

    async def prepare(self) -> None:
        await self._send("Page.enable")
        await self._send("Runtime.enable")
        await self._send("Fetch.enable", {"patterns": [{"urlPattern": "*"}]})

    async def screenshot(self) -> bytes:
        """What the tab shows now, as a small JPEG. Looking changes nothing on the page."""
        shot = await self._send("Page.captureScreenshot", {"format": "jpeg", "quality": SHOT_QUALITY})
        data = base64.b64decode(str(shot["data"]), validate=True)
        if len(data) > SHOT_MAX_BYTES:
            raise ToolError("the page is too big to show")
        return data

    async def _send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._cdp.call(method, params, self._session)

    # ---- events (routed here by the manager) -----------------------------------------------------
    def navigated(self) -> None:
        self._world = None
        self._current = None      # a new page: every earlier target is out of date
        self._on_navigated()

    def loading(self, on: bool) -> None:
        self._loading = on

    # ---- reading --------------------------------------------------------------------------------
    async def open(self, url: str) -> Snapshot:
        if (why := check_url(url)) is not None:
            raise ValidationFailed(why)
        reason = await self._guard.refusal(url, "Document")
        if reason is not None:
            raise ToolError(reason)
        self._loading = True
        result = await self._send("Page.navigate", {"url": url})
        if result.get("errorText"):
            raise ToolError(f"the page could not be opened ({str(result['errorText'])[:60]})")
        await self._settle(initial=True)
        return await self.snapshot(fresh=True)

    async def back(self) -> str:
        history = await self._send("Page.getNavigationHistory")
        index = int(history.get("currentIndex", 0))
        if index <= 0:
            raise ToolError("there is no earlier page")
        self._loading = True
        await self._send("Page.navigateToHistoryEntry", {"entryId": history["entries"][index - 1]["id"]})
        await self._settle(initial=True)
        return "Went back."

    async def _context(self) -> int:
        if self._world is None:
            tree = await self._send("Page.getFrameTree")
            made = await self._send("Page.createIsolatedWorld", {"frameId": tree["frameTree"]["frame"]["id"],
                                                                 "worldName": WORLD})
            self._world = int(made["executionContextId"])
        return self._world

    async def _eval(self, expression: str) -> Any:
        out = await self._send("Runtime.evaluate", {"expression": expression, "contextId": await self._context(),
                                                    "returnByValue": True, "awaitPromise": False})
        if out.get("exceptionDetails"):
            raise ToolError("the page could not be read")
        return out.get("result", {}).get("value")

    async def snapshot(self, fresh: bool = False) -> Snapshot:
        """The current snapshot, or a new one when the page changed (or `fresh`)."""
        if self._current is not None and not fresh:
            return self._current
        raw = await self._eval(_SNAPSHOT_JS)
        try:
            data = json.loads(raw)
            els = tuple((str(r)[:20], str(n)[:80]) for r, n in data["els"])
            url, title, text = str(data["url"]), str(data["title"]), str(data["text"])
        except (TypeError, ValueError, KeyError):
            raise ToolError("the page could not be read") from None
        self._counter += 1
        self._current = Snapshot(self._counter, url, urlparse(url).netloc.lower() or "page", title, text, els)
        self.host = self._current.host
        return self._current

    async def find(self, query: str) -> str:
        """The target line that best matches the words, from the current snapshot."""
        snap = await self.snapshot()
        if not snap.elements:
            raise ToolError("there is nothing to act on on this page")
        scored = score(query, {str(i): f"{r} {n}" for i, (r, n) in enumerate(snap.elements)})
        best = max(scored.scores.items(), key=lambda kv: (kv[1], -int(kv[0])))
        if best[1] <= 0:
            raise ToolError("nothing on the page matches those words; use browser.read to see the page")
        return snap.token(int(best[0]))

    # ---- acting ------------------------------------------------------------------------------------
    async def _locate(self, text: object) -> tuple[Target, dict[str, Any]]:
        target = parse_target(text)
        if target is None:
            raise ValidationFailed("target must be one line exactly as browser.read or browser.find gave it")
        snap = self._current
        if snap is None or target.snapshot != snap.ident:
            raise ToolError("that target is out of date because the page changed; use browser.find again")
        if target.ref >= len(snap.elements):
            raise ToolError("that target is not on the page")
        found = await self._eval(_LOCATE_JS % target.ref)
        try:
            where = json.loads(found)
        except (TypeError, ValueError):
            raise ToolError("that element is no longer on the page; use browser.find again") from None
        if (where["role"], where["name"]) != (target.role, target.name) or snap.host != target.host:
            raise ToolError("the element is not what the target says any more; use browser.find again")
        if target.role == "file":
            raise ToolError("choosing files is not allowed")
        return target, where

    async def click(self, text: object) -> str:
        target, where = await self._locate(text)
        if target.role == "submit":
            raise ToolError("that is a submit button; use browser.submit so it is reviewed as sending a form")
        await self._press_at(where)
        return f'Clicked {target.role} "{target.name}".'

    async def submit(self, text: object) -> str:
        target, where = await self._locate(text)
        if target.role != "submit":
            raise ToolError("that is not a submit button; use browser.click")
        await self._press_at(where)
        return f'Submitted with "{target.name}".'

    async def _press_at(self, where: dict[str, Any]) -> None:
        x, y = float(where["x"]), float(where["y"])
        self._current = None      # whatever happens next, every earlier target is out of date
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            await self._send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left",
                                                          "clickCount": 1})
        await self._settle()

    async def type(self, text: object, value: str, clear: bool) -> str:
        target, _ = await self._locate(text)
        if target.role not in ("textbox", "select") or not value or len(value) > 2000 or "\x00" in value:
            raise ValidationFailed("only text boxes can be typed into, with 1 to 2000 characters")
        if not await self._eval(_FOCUS_JS % (target.ref, "true" if clear else "false")):
            raise ToolError("that element could not be focused")
        self._current = None      # whatever happens next, every earlier target is out of date
        await self._send("Input.insertText", {"text": value})
        await self._settle()
        return f'Typed {len(value)} characters into "{target.name}".'

    async def select(self, text: object, value: str) -> str:
        target, _ = await self._locate(text)
        if target.role != "select" or not value or len(value) > 200:
            raise ValidationFailed("that is not a drop-down, or the option is missing")
        if not await self._eval(_SELECT_JS % (target.ref, json.dumps(value))):
            raise ToolError("that option is not in the drop-down")
        self._current = None      # whatever happens next, every earlier target is out of date
        await self._settle()
        return f'Chose "{value}" in "{target.name}".'

    async def press(self, key: str) -> str:
        if key not in KEYS:
            raise ValidationFailed("key must be one of " + ", ".join(sorted(KEYS)))
        code, name = _KEY_CODES[key]
        self._current = None      # whatever happens next, every earlier target is out of date
        extra = {"text": "\r"} if key == "Enter" else {}
        for kind in ("keyDown", "keyUp"):
            await self._send("Input.dispatchKeyEvent", {"type": kind, "key": key if key != "Space" else " ",
                                                        "code": name, "windowsVirtualKeyCode": code, **extra})
        await self._settle()
        return f"Pressed {key}."

    async def scroll(self, direction: str) -> str:
        if direction not in ("down", "up"):
            raise ValidationFailed("direction must be down or up")
        await self._eval(f"window.scrollBy(0, {'' if direction == 'down' else '-'}Math.round(innerHeight * 0.8))")
        self._current = None      # whatever happens next, every earlier target is out of date
        return f"Scrolled {direction}."

    async def _settle(self, initial: bool = False) -> None:
        """Wait for a started navigation to finish, bounded; actions that navigate are given a moment to begin."""
        await asyncio.sleep(SETTLE_S)
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(LOAD_TIMEOUT_S):
                while self._loading:
                    await asyncio.sleep(0.05)
        if initial and self._loading:
            raise ToolError("the page took too long to load")

    async def close(self) -> None:
        with contextlib.suppress(ToolError):
            await self._cdp.call("Target.closeTarget", {"targetId": self.target_id}, timeout=5)
