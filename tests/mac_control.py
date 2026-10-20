"""macOS automated test harness control module.

Combines native macOS Accessibility API (PyObjC) with cliclick / Quartz
event dispatching for reliable automated desktop testing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any

_HAS_PYOBJC = False
try:
    import AppKit
    import ApplicationServices

    _HAS_PYOBJC = True
except ImportError:
    pass


class MacTestHarnessControl:
    """Automated control module for macOS desktop integration and testing."""

    def __init__(self, cliclick_path: str | None = None) -> None:
        self.cliclick_path = cliclick_path or shutil.which("cliclick") or "/usr/local/bin/cliclick"
        self._has_cliclick = os.path.exists(self.cliclick_path) if self.cliclick_path else False

    @property
    def has_cliclick(self) -> bool:
        if not self._has_cliclick and self.cliclick_path:
            self._has_cliclick = os.path.exists(self.cliclick_path) or bool(shutil.which("cliclick"))
        return self._has_cliclick

    def take_screenshot(self, output_path: str = "screenshot.png") -> str:
        """Captures the current screen for harness assertion steps."""
        subprocess.run(["/usr/sbin/screencapture", "-x", output_path], check=True)
        return output_path

    def click(self, x: int, y: int) -> None:
        """Executes a hardware-level mouse click."""
        if self.has_cliclick:
            bin_path = shutil.which("cliclick") or self.cliclick_path
            subprocess.run([bin_path, f"c:{x},{y}"], check=True)
            return

        if _HAS_PYOBJC:
            pt = ApplicationServices.CGPoint(x=x, y=y)
            press = ApplicationServices.CGEventCreateMouseEvent(
                None, ApplicationServices.kCGEventLeftMouseDown, pt, ApplicationServices.kCGMouseButtonLeft
            )
            release = ApplicationServices.CGEventCreateMouseEvent(
                None, ApplicationServices.kCGEventLeftMouseUp, pt, ApplicationServices.kCGMouseButtonLeft
            )
            ApplicationServices.CGEventPost(ApplicationServices.kCGHIDEventTap, press)
            time.sleep(0.02)
            ApplicationServices.CGEventPost(ApplicationServices.kCGHIDEventTap, release)
            return

        raise RuntimeError("Neither cliclick nor PyObjC Quartz is available for mouse click")

    def type_text(self, text: str) -> None:
        """Types literal text via the keyboard buffer."""
        if not text:
            return
        if self.has_cliclick:
            bin_path = shutil.which("cliclick") or self.cliclick_path
            subprocess.run([bin_path, f"t:{text}"], check=True)
            return

        if _HAS_PYOBJC:
            for ch in text:
                event_down = ApplicationServices.CGEventCreateKeyboardEvent(None, 0, True)
                ApplicationServices.CGEventKeyboardSetUnicodeString(event_down, len(ch), ch)
                ApplicationServices.CGEventPost(ApplicationServices.kCGHIDEventTap, event_down)
                time.sleep(0.005)
                event_up = ApplicationServices.CGEventCreateKeyboardEvent(None, 0, False)
                ApplicationServices.CGEventKeyboardSetUnicodeString(event_up, len(ch), ch)
                ApplicationServices.CGEventPost(ApplicationServices.kCGHIDEventTap, event_up)
                time.sleep(0.005)
            return

        raise RuntimeError("Neither cliclick nor PyObjC Quartz is available for keyboard input")

    def press_key(self, key_shortcut: str) -> None:
        """Simulates special keys (e.g., return, enter, esc, tab, space)."""
        cliclick_map = {
            "down": "arrow-down",
            "up": "arrow-up",
            "left": "arrow-left",
            "right": "arrow-right",
            "escape": "esc",
            "backspace": "delete",
        }
        normalized = key_shortcut.lower().strip()
        mapped = cliclick_map.get(normalized, normalized)

        if self.has_cliclick:
            bin_path = shutil.which("cliclick") or self.cliclick_path
            shortcut = mapped if ":" in mapped else f"kp:{mapped}"
            subprocess.run([bin_path, shortcut], check=True)
            return

        key_map = {
            "return": 36,
            "enter": 36,
            "tab": 48,
            "space": 49,
            "esc": 53,
            "escape": 53,
            "delete": 51,
            "backspace": 51,
            "down": 125,
            "up": 126,
            "left": 123,
            "right": 124,
        }
        code = key_map.get(key_shortcut.lower())
        if code is not None and _HAS_PYOBJC:
            down = ApplicationServices.CGEventCreateKeyboardEvent(None, code, True)
            up = ApplicationServices.CGEventCreateKeyboardEvent(None, code, False)
            ApplicationServices.CGEventPost(ApplicationServices.kCGHIDEventTap, down)
            time.sleep(0.01)
            ApplicationServices.CGEventPost(ApplicationServices.kCGHIDEventTap, up)
            return

        raise RuntimeError(f"Cannot press key {key_shortcut!r} without cliclick or PyObjC mapping")

    def get_active_window_title(self) -> str:
        """Returns the name of the application currently in focus."""
        if not _HAS_PYOBJC:
            return ""
        active_app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        return str(active_app.localizedName() or "") if active_app else ""

    def get_ui_tree(self) -> list[Any]:
        """Scans windows for UI elements, titles, and positions via macOS AX."""
        if not _HAS_PYOBJC:
            return []
        system_wide = ApplicationServices.AXUIElementCreateSystemWide()
        error, children = ApplicationServices.AXUIElementCopyAttributeValue(
            system_wide, ApplicationServices.kAXChildrenAttribute, None
        )
        return list(children) if (error == 0 and children) else []

    def find_element_by_name(self, name: str) -> tuple[int, int] | None:
        """Helper to find center (x, y) coordinates of an accessible UI element by name."""
        if not _HAS_PYOBJC:
            return None

        def search_node(element: Any, depth: int = 0) -> tuple[int, int] | None:
            if depth > 7:
                return None
            err_t, title = ApplicationServices.AXUIElementCopyAttributeValue(
                element, ApplicationServices.kAXTitleAttribute, None
            )
            if err_t == 0 and title and name.casefold() in str(title).casefold():
                err_p, pos = ApplicationServices.AXUIElementCopyAttributeValue(
                    element, ApplicationServices.kAXPositionAttribute, None
                )
                err_s, size = ApplicationServices.AXUIElementCopyAttributeValue(
                    element, ApplicationServices.kAXSizeAttribute, None
                )
                if err_p == 0 and err_s == 0 and pos and size:
                    pt = ApplicationServices.CGPoint()
                    sz = ApplicationServices.CGSize()
                    if ApplicationServices.AXValueGetValue(pos, 1, pt) and ApplicationServices.AXValueGetValue(size, 2, sz):
                        return int(pt.x + sz.width / 2), int(pt.y + sz.height / 2)

            err_c, children = ApplicationServices.AXUIElementCopyAttributeValue(
                element, ApplicationServices.kAXChildrenAttribute, None
            )
            if err_c == 0 and children:
                for child in children:
                    res = search_node(child, depth + 1)
                    if res is not None:
                        return res
            return None

        system_wide = ApplicationServices.AXUIElementCreateSystemWide()
        err, windows = ApplicationServices.AXUIElementCopyAttributeValue(
            system_wide, ApplicationServices.kAXWindowsAttribute, None
        )
        if err == 0 and windows:
            for w in windows:
                res = search_node(w)
                if res is not None:
                    return res
        return None
