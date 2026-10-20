"""Integration test for MacTestHarnessControl module with cliclick and macOS AX API."""

from __future__ import annotations

from pathlib import Path

from tests.mac_control import MacTestHarnessControl


def test_mac_harness_initialization() -> None:
    harness = MacTestHarnessControl()
    assert harness.has_cliclick is True
    assert harness.cliclick_path is not None


def test_mac_harness_screenshot(tmp_path: Path) -> None:
    harness = MacTestHarnessControl()
    out = tmp_path / "test_screen.png"
    result = harness.take_screenshot(str(out))
    assert result == str(out)
    assert out.is_file()
    assert out.stat().st_size > 0


def test_mac_harness_active_window() -> None:
    harness = MacTestHarnessControl()
    title = harness.get_active_window_title()
    assert isinstance(title, str)


def test_mac_harness_ui_tree() -> None:
    harness = MacTestHarnessControl()
    elements = harness.get_ui_tree()
    assert isinstance(elements, list)


def test_mac_harness_keyboard_and_mouse() -> None:
    harness = MacTestHarnessControl()
    # Execute non-disruptive key and click commands
    harness.press_key("tab")
    harness.press_key("esc")
    harness.type_text("")  # empty typing check
