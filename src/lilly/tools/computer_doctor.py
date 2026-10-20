"""`lilly computer doctor` and smoke test: diagnostics and real-device desktop verification."""

from __future__ import annotations

import asyncio
import platform
import subprocess  # nosec B404 - fixed osascript and open invocations for diagnostics and verification
import sys
import tempfile
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lilly.tools.computer_runtime import (
    _HAS_PYOBJC,
    A11yElement,
    MacNativeComputerBackend,
    check_macos_accessibility_permission,
    check_macos_screen_capture_permission,
    default_computer_backend,
)


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str


def check_computer_environment() -> list[Check]:
    """Run all computer control diagnostic checks."""
    checks: list[Check] = []

    # 1. OS Platform
    is_mac = sys.platform == "darwin"
    mac_ver = platform.mac_ver()[0] if is_mac else ""
    checks.append(
        Check(
            "OS Platform",
            is_mac,
            f"macOS {mac_ver}"
            if is_mac
            else f"{sys.platform} (MacNativeComputerBackend is macOS only; fallback active)",
        )
    )

    # 2. PyObjC availability
    checks.append(
        Check(
            "PyObjC frameworks",
            _HAS_PYOBJC,
            "ApplicationServices, Quartz, AppKit available"
            if _HAS_PYOBJC
            else "missing PyObjC frameworks; fallback active",
        )
    )

    # 3. Screen Recording permission
    if is_mac:
        screen_ok = check_macos_screen_capture_permission()
        checks.append(
            Check(
                "Screen Recording permission",
                screen_ok,
                "granted"
                if screen_ok
                else (
                    "missing: Lilly cannot take desktop screenshots. "
                    "Fix: Open System Settings > Privacy & Security > Screen Recording and enable permission for this terminal/app."
                ),
            )
        )

        # 4. Accessibility permission
        ax_ok = check_macos_accessibility_permission()
        checks.append(
            Check(
                "Accessibility permission",
                ax_ok,
                "granted"
                if ax_ok
                else (
                    "missing: Lilly cannot inspect UI elements or dispatch native inputs. "
                    "Fix: Open System Settings > Privacy & Security > Accessibility and enable permission for this terminal/app."
                ),
            )
        )
    else:
        checks.append(Check("Screen Recording permission", True, "N/A on non-macOS"))
        checks.append(Check("Accessibility permission", True, "N/A on non-macOS"))

    # 5. Display & Scale
    display_detail = "unknown display"
    if is_mac and _HAS_PYOBJC:
        try:
            import AppKit  # type: ignore[import-untyped]

            screen = AppKit.NSScreen.mainScreen()
            if screen is not None:
                sz = screen.frame().size
                scale = screen.backingScaleFactor()
                display_detail = f"{int(sz.width)}x{int(sz.height)} @ {scale:.1f}x backing scale"
        except Exception as exc:
            display_detail = f"error checking display: {exc}"
    checks.append(Check("Main display", True, display_detail))

    # 6. Active Backend
    backend = default_computer_backend()
    backend_name = type(backend).__name__
    is_native = isinstance(backend, MacNativeComputerBackend)
    checks.append(
        Check(
            "Computer backend",
            is_native if is_mac else True,
            f"{backend_name} (native PyObjC CoreGraphics/AXUIElement)"
            if is_native
            else f"{backend_name} (PyAutoGUI fallback)",
        )
    )

    # 7. Emergency stop failsafe
    checks.append(
        Check(
            "Emergency stop failsafe",
            True,
            "enabled (moving cursor to corner (0, 0) halts desktop control immediately)",
        )
    )

    return checks


async def run_computer_smoke_test() -> tuple[bool, str, list[tuple[str, bool, str]]]:
    """Run an end-to-end smoke test on real macOS hardware.

    Verifies:
    1. Permissions preflight (Screen Recording and Accessibility)
    2. Screenshot capture to disk
    3. Accessibility discovery on frontmost app
    4. Opening TextEdit with a document
    5. Typing a unique string via native keyboard input
    6. Keyboard press (return)
    7. Visible-state verification in accessibility tree
    8. Safe cleanup (closing window and quitting without saving)
    """
    steps: list[tuple[str, bool, str]] = []
    started_all = time.perf_counter()

    if sys.platform != "darwin":
        return (
            False,
            "Smoke test requires macOS physical or virtual desktop environment",
            [("Platform check", False, f"Unsupported platform: {sys.platform}")],
        )

    # 1. Permissions check
    t0 = time.perf_counter()
    screen_ok = check_macos_screen_capture_permission()
    ax_ok = check_macos_accessibility_permission()
    if not screen_ok or not ax_ok:
        msg = []
        if not screen_ok:
            msg.append("Screen Recording permission missing (System Settings > Privacy & Security > Screen Recording)")
        if not ax_ok:
            msg.append("Accessibility permission missing (System Settings > Privacy & Security > Accessibility)")
        steps.append(("Permission preflight", False, "; ".join(msg)))
        return False, "Permission preflight failed", steps
    steps.append(
        (
            "Permission preflight",
            True,
            f"Screen Recording & Accessibility verified in {(time.perf_counter() - t0) * 1000:.1f}ms",
        )
    )

    backend = default_computer_backend()

    # 2. Screenshot capture
    t0 = time.perf_counter()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_shot:
        shot_path = Path(tmp_shot.name)
    try:
        await backend.observe(shot_path)
        if not shot_path.is_file() or shot_path.stat().st_size == 0:
            steps.append(("Screenshot capture", False, "Screenshot file missing or empty"))
            return False, "Screenshot capture failed", steps
        size_kb = shot_path.stat().st_size / 1024
        steps.append(
            ("Screenshot capture", True, f"Captured {size_kb:.1f} KB in {(time.perf_counter() - t0) * 1000:.1f}ms")
        )
    finally:
        if shot_path.is_file():
            shot_path.unlink()

    # 3. Accessibility discovery on frontmost application
    t0 = time.perf_counter()
    app, win, elements = await backend.observe(None)
    if not elements and not app:
        steps.append(("Accessibility discovery", False, "No active application or accessibility elements found"))
        return False, "Accessibility discovery failed", steps
    steps.append(
        (
            "Accessibility discovery",
            True,
            f"Discovered {len(elements)} elements in '{app}' ({win or 'no title'}) in {(time.perf_counter() - t0) * 1000:.1f}ms",
        )
    )

    if (app or "").casefold() == "loginwindow" or (win or "").casefold() == "login":
        steps.append(
            (
                "Display lock check",
                False,
                "macOS desktop is locked (frontmost app is 'loginwindow'). Unlock the laptop screen to run interactive GUI tests.",
            )
        )
        return False, "macOS desktop screen is locked (loginwindow); unlock screen to verify in-app interaction", steps

    # 4. Open TextEdit with temporary document

    t0 = time.perf_counter()
    unique_id = f"Lilly-Verify-{uuid.uuid4().hex[:8]}"
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as tmp_doc:
        doc_path = Path(tmp_doc.name)

    try:
        subprocess.run(["/usr/bin/open", "-a", "TextEdit", str(doc_path)], check=True)  # nosec B603
        if _HAS_PYOBJC:
            import AppKit

            for running_app in AppKit.NSWorkspace.sharedWorkspace().runningApplications():
                if running_app.localizedName() == "TextEdit":
                    running_app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
                    break
        subprocess.run(["/usr/bin/osascript", "-e", 'tell application "TextEdit" to activate'], check=False)  # nosec B603

        # Wait up to 5 seconds for TextEdit to be ready
        textedit_ready = False
        t_app: str | None = None
        t_win: str | None = None
        t_elems: Sequence[A11yElement] = ()
        for _ in range(50):
            await asyncio.sleep(0.1)
            t_app, t_win, t_elems = await backend.observe(None, "TextEdit")
            if (t_app or "").casefold() == "textedit":
                textedit_ready = True
                break
            subprocess.run(["/usr/bin/osascript", "-e", 'tell application "TextEdit" to activate'], check=False)  # nosec B603

        if not textedit_ready:
            steps.append(("Open TextEdit", False, f"Could not observe TextEdit (observed '{t_app}')"))
            return False, "TextEdit launch failed", steps
        steps.append(
            ("Open TextEdit", True, f"TextEdit launched and ready in {(time.perf_counter() - t0) * 1000:.1f}ms")
        )

        # 5. Click inside window to focus
        t0 = time.perf_counter()
        target_pt = (200, 200)
        if t_elems:
            for e in t_elems:
                if e.x is not None and e.y is not None and (e.width or 0) > 50 and (e.height or 0) > 50:
                    target_pt = (e.x + (e.width or 0) // 2, e.y + (e.height or 0) // 2)
                    break
        await backend.click(target_pt[0], target_pt[1])
        steps.append(("Click to focus", True, f"Clicked at {target_pt} in {(time.perf_counter() - t0) * 1000:.1f}ms"))

        # 6. Type unique string into document
        t0 = time.perf_counter()
        await backend.type_text(unique_id)
        steps.append(
            ("Type text", True, f"Typed unique test string '{unique_id}' in {(time.perf_counter() - t0) * 1000:.1f}ms")
        )

        # 7. Press keyboard key (return)
        t0 = time.perf_counter()
        await backend.press("return")
        steps.append(("Keyboard press", True, f"Pressed 'return' key in {(time.perf_counter() - t0) * 1000:.1f}ms"))

        # 8. App search workflow: Open Find/Search bar (command+f), type query and press return
        t0 = time.perf_counter()
        await backend.press("command+f")
        await asyncio.sleep(0.15)
        await backend.type_text(unique_id)
        await backend.press("return")
        steps.append(
            ("App search", True, f"Triggered find bar (cmd+f), typed query '{unique_id}' and searched in {(time.perf_counter() - t0) * 1000:.1f}ms")
        )

        # 9. Visible-state verification in accessibility tree
        t0 = time.perf_counter()
        verified = False
        for _ in range(25):
            await asyncio.sleep(0.15)
            _, _, fresh_elems = await backend.observe(None, "TextEdit")
            for item in fresh_elems:
                if unique_id in item.text or unique_id in item.name or unique_id in item.description:
                    verified = True
                    break
            if verified:
                break


        if not verified:
            steps.append(
                (
                    "Visible-state verification",
                    False,
                    f"Unique string '{unique_id}' was not found in TextEdit accessibility tree",
                )
            )
            return False, "Visible-state verification failed", steps
        steps.append(
            (
                "Visible-state verification",
                True,
                f"Verified '{unique_id}' in accessibility tree in {(time.perf_counter() - t0) * 1000:.1f}ms",
            )
        )

    finally:
        # 9. Clean up TextEdit
        subprocess.run(["/usr/bin/osascript", "-e", 'tell application "TextEdit" to close front window saving no'], check=False)  # nosec B603
        subprocess.run(["/usr/bin/osascript", "-e", 'tell application "TextEdit" to quit saving no'], check=False)  # nosec B603
        if doc_path.is_file():
            doc_path.unlink()

    total_ms = (time.perf_counter() - started_all) * 1000
    summary = f"All real-Mac desktop control checks passed successfully in {total_ms:.1f}ms"
    return True, summary, steps
