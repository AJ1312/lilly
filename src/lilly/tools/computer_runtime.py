"""Persistent, observation-first desktop control.

The runtime owns frame identity and action receipts. Backends may be replaced in
tests or by a platform integration, but every action follows the same contract:
the caller supplies a fresh frame id, the runtime rejects stale state, performs
one action, captures a fresh frame, and verifies an optional expectation.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess  # nosec B404 - fixed osascript/screencapture invocations only
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from lilly.domain.errors import ToolError, ValidationFailed

_KEY_CODES = {
    "enter": 36, "return": 36, "tab": 48, "escape": 53, "esc": 53,
    "backspace": 51, "delete": 51, "space": 49, "left": 123, "right": 124,
    "down": 125, "up": 126, "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
}
_COORDINATE = re.compile(r"^@?\s*x\s*=\s*(\d+)\s*,\s*y\s*=\s*(\d+)\s*$", re.I)


@dataclass(frozen=True, slots=True)
class A11yElement:
    role: str
    name: str
    description: str = ""
    x: int | None = None
    y: int | None = None
    width: int | None = None
    height: int | None = None

    @property
    def text(self) -> str:
        return " ".join(x for x in (self.role, self.name, self.description) if x).strip()


@dataclass(frozen=True, slots=True)
class ComputerFrame:
    frame_id: str
    created_at: float
    app: str | None
    window: str | None
    screenshot: str | None
    elements: tuple[A11yElement, ...] = ()
    dom: Mapping[str, Any] | None = None
    devbox: Mapping[str, Any] | None = None

    def contains(self, expected: str) -> bool:
        needle = expected.casefold().strip()
        return not needle or any(needle in item.text.casefold() for item in self.elements) \
            or needle in (self.app or "").casefold() or needle in (self.window or "").casefold()


class ComputerBackend(Protocol):
    async def observe(self, screenshot_path: Path | None) -> tuple[str | None, str | None, Sequence[A11yElement]]: ...
    async def click(self, x: int, y: int) -> None: ...
    async def type_text(self, text: str) -> None: ...
    async def press(self, key: str) -> None: ...


class VisionGrounder(Protocol):
    async def __call__(self, frame: ComputerFrame, target: str) -> tuple[int, int] | None: ...


class MacComputerBackend:  # pragma: no cover - exercised by the macOS desktop smoke test
    """Small native backend using macOS accessibility and event primitives."""

    def __init__(self) -> None:
        self._screencapture = shutil.which("screencapture")
        self._osascript = shutil.which("osascript")

    async def observe(self, screenshot_path: Path | None) -> tuple[str | None, str | None, Sequence[A11yElement]]:
        if sys.platform != "darwin" or self._osascript is None:
            raise ToolError("desktop computer control is unavailable on this platform")
        if screenshot_path is not None:
            if self._screencapture is None:
                raise ToolError("macOS screenshot capture is unavailable")
            try:
                await asyncio.to_thread(self._run, [self._screencapture, "-x", str(screenshot_path)])
            except (OSError, subprocess.SubprocessError) as exc:
                raise ToolError(f"could not capture the screen: {exc}") from exc
        script = '''tell application "System Events"
set p to first application process whose frontmost is true
set n to name of p
set w to ""
set elements_text to ""
try
set front_window to front window of p
set w to name of front_window
repeat with element_ref in UI elements of front_window
try
set element_role to role of element_ref
set element_name to ""
try
set element_name to name of element_ref
end try
set element_description to ""
try
set element_description to description of element_ref
end try
set element_position to position of element_ref
set element_size to size of element_ref
set elements_text to elements_text & (element_role & tab & element_name & tab & element_description & tab & (item 1 of element_position) & tab & (item 2 of element_position) & tab & (item 1 of element_size) & tab & (item 2 of element_size)) & linefeed
end try
try
repeat with child_ref in UI elements of element_ref
try
set element_role to role of child_ref
set element_name to ""
try
set element_name to name of child_ref
end try
set element_description to ""
try
set element_description to description of child_ref
end try
set element_position to position of child_ref
set element_size to size of child_ref
set elements_text to elements_text & (element_role & tab & element_name & tab & element_description & tab & (item 1 of element_position) & tab & (item 2 of element_position) & tab & (item 1 of element_size) & tab & (item 2 of element_size)) & linefeed
end try
end repeat
end try
end repeat
end try
return n & tab & w & linefeed & elements_text
end tell'''
        try:
            result = await asyncio.to_thread(self._run, [self._osascript, "-e", script])
        except (OSError, subprocess.SubprocessError) as exc:
            raise ToolError("macOS accessibility permission is required to inspect the frontmost app") from exc
        header, _, body = result.partition("\n")
        app, _, window = header.partition("\t")
        elements: list[A11yElement] = []
        for row in body.splitlines():
            fields = row.split("\t")
            if len(fields) != 7:
                continue
            try:
                elements.append(A11yElement(fields[0], fields[1], fields[2], *(int(value) for value in fields[3:])))
            except ValueError:
                continue
        return app or None, window or None, elements

    async def click(self, x: int, y: int) -> None:
        await self._script(f'tell application "System Events" to click at {{{x}, {y}}}')

    async def type_text(self, text: str) -> None:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        await self._script(f'tell application "System Events" to keystroke "{escaped}"')

    async def press(self, key: str) -> None:
        normalized = key.casefold().replace(" ", "")
        if normalized not in _KEY_CODES:
            raise ValidationFailed(f"unsupported key: {key}")
        await self._script(f'tell application "System Events" to key code {_KEY_CODES[normalized]}')

    async def _script(self, script: str) -> None:
        if self._osascript is None or sys.platform != "darwin":
            raise ToolError("desktop computer control is unavailable on this platform")
        await asyncio.to_thread(self._run, [self._osascript, "-e", script])

    @staticmethod
    def _run(argv: list[str]) -> str:
        done = subprocess.run(argv, check=True, capture_output=True, text=True, timeout=15)  # nosec B603
        return done.stdout.strip()


@dataclass(slots=True)
class ComputerRuntime:
    root: Path
    backend: ComputerBackend | None = None
    vision_grounder: VisionGrounder | None = None
    devbox: Any | None = None
    clock: Any = time.time
    _frames: dict[str, ComputerFrame] = field(default_factory=dict)
    _latest: dict[str, str] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _state_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._state_path = self.root / "state.json"
        self._load_state()
        if self.backend is None:
            self.backend = MacComputerBackend()

    def _load_state(self) -> None:
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        self._latest = {str(k): str(v) for k, v in (raw.get("latest") or {}).items()}
        for item in raw.get("frames") or []:
            try:
                frame = ComputerFrame(
                    str(item["frame_id"]), float(item["created_at"]), item.get("app"), item.get("window"),
                    item.get("screenshot"), tuple(A11yElement(**element) for element in item.get("elements", [])),
                    devbox=item.get("devbox"),
                )
                self._frames[frame.frame_id] = frame
            except (KeyError, TypeError, ValueError):
                continue

    def _persist_state(self) -> None:
        frames = list(self._frames.values())[-64:]
        payload = {
            "latest": self._latest,
            "frames": [{
                "frame_id": frame.frame_id, "created_at": frame.created_at, "app": frame.app,
                "window": frame.window, "screenshot": frame.screenshot,
                "elements": [{"role": e.role, "name": e.name, "description": e.description,
                              "x": e.x, "y": e.y, "width": e.width, "height": e.height}
                             for e in frame.elements], "devbox": frame.devbox,
            } for frame in frames],
        }
        temporary = self._state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
        temporary.replace(self._state_path)

    async def observe(self, task_id: str, *, capture: bool = True) -> ComputerFrame:
        async with self._lock:
            frame_id = f"frame-{uuid.uuid4().hex[:16]}"
            screenshot = self.root / task_id / f"{frame_id}.png" if capture else None
            if screenshot is not None:
                screenshot.parent.mkdir(parents=True, exist_ok=True)
            assert self.backend is not None
            app, window, elements = await self.backend.observe(screenshot)
            environment = await self._environment()
            frame = ComputerFrame(frame_id, float(self.clock()), app, window,
                                  str(screenshot) if screenshot and screenshot.is_file() else None,
                                  tuple(elements), devbox=environment)
            self._frames[frame_id] = frame
            self._latest[task_id] = frame_id
            self._persist_state()
            return frame

    def current(self, frame_id: str, task_id: str | None = None) -> ComputerFrame:
        frame = self._frames.get(frame_id)
        if frame is None:
            raise ToolError("that observation is unknown; observe the computer again")
        if task_id is not None and self._latest.get(task_id) != frame_id:
            raise ToolError("that observation is stale; observe the computer again")
        return frame

    async def _target(self, frame: ComputerFrame, target: str) -> tuple[int, int]:
        needle = target.casefold().strip()
        matches = [item for item in frame.elements if needle and needle in item.text.casefold()]
        if len(matches) == 1:
            item = matches[0]
            if item.x is not None and item.y is not None:
                return item.x + (item.width or 0) // 2, item.y + (item.height or 0) // 2
        if len(matches) > 1:
            raise ToolError("target is ambiguous in this observation; use a more specific target")
        if self.vision_grounder is not None:
            point = await self.vision_grounder(frame, target)
            if point is not None:
                return point
        match = _COORDINATE.match(target.strip())
        if match:
            return int(match.group(1)), int(match.group(2))
        if matches:
            raise ToolError("target has no usable accessibility bounds")
        raise ToolError("target was not found in this observation")

    async def click(self, task_id: str, frame_id: str, target: str, expected: str = "") -> ComputerFrame:
        async with self._lock:
            frame = self.current(frame_id, task_id)
            x, y = await self._target(frame, target)
            assert self.backend is not None
            await self.backend.click(x, y)
            fresh = await self._observe_locked(task_id)
            self._verify(fresh, expected)
            return fresh

    async def type_text(self, task_id: str, frame_id: str, target: str, text: str,
                        expected: str = "") -> ComputerFrame:
        async with self._lock:
            frame = self.current(frame_id, task_id)
            x, y = await self._target(frame, target)
            assert self.backend is not None
            await self.backend.click(x, y)
            await self.backend.type_text(text)
            fresh = await self._observe_locked(task_id)
            self._verify(fresh, expected)
            return fresh

    async def press(self, task_id: str, frame_id: str, key: str, expected: str = "") -> ComputerFrame:
        async with self._lock:
            self.current(frame_id, task_id)
            assert self.backend is not None
            await self.backend.press(key)
            fresh = await self._observe_locked(task_id)
            self._verify(fresh, expected)
            return fresh

    async def _observe_locked(self, task_id: str) -> ComputerFrame:
        frame_id = f"frame-{uuid.uuid4().hex[:16]}"
        screenshot = self.root / task_id / f"{frame_id}.png"
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        assert self.backend is not None
        app, window, elements = await self.backend.observe(screenshot)
        environment = await self._environment()
        frame = ComputerFrame(frame_id, float(self.clock()), app, window,
                              str(screenshot) if screenshot.is_file() else None, tuple(elements), devbox=environment)
        self._frames[frame_id] = frame
        self._latest[task_id] = frame_id
        self._persist_state()
        return frame

    @staticmethod
    def _verify(frame: ComputerFrame, expected: str) -> None:
        if expected and not frame.contains(expected):
            raise ToolError("action completed but verification did not find the expected state")

    @staticmethod
    def render(frame: ComputerFrame) -> str:
        payload = {
            "frame_id": frame.frame_id, "app": frame.app, "window": frame.window,
            "screenshot": frame.screenshot,
            "elements": [item.__dict__ if hasattr(item, "__dict__") else {
                "role": item.role, "name": item.name, "description": item.description,
                "x": item.x, "y": item.y, "width": item.width, "height": item.height,
            } for item in frame.elements],
            "devbox": frame.devbox,
        }
        return json.dumps(payload, ensure_ascii=True)

    async def _environment(self) -> Mapping[str, Any] | None:
        if self.devbox is None:
            return None
        status = getattr(self.devbox, "status", None)
        if status is None:
            return None
        result = await status()
        return result if isinstance(result, Mapping) else None
