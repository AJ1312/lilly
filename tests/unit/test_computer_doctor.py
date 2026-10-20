"""Tests for lilly computer doctor and smoke test diagnostics."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lilly.daemon import cli
from lilly.tools import computer_doctor
from lilly.tools.computer_runtime import A11yElement


def test_check_computer_environment() -> None:
    checks = computer_doctor.check_computer_environment()
    assert len(checks) >= 5
    names = {c.name for c in checks}
    assert "OS Platform" in names
    assert "Screen Recording permission" in names
    assert "Accessibility permission" in names
    assert "Computer backend" in names
    assert "Emergency stop failsafe" in names


def test_check_computer_environment_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    checks = computer_doctor.check_computer_environment()
    assert any(c.name == "OS Platform" and not c.ok for c in checks)
    assert any(c.name == "Screen Recording permission" and "N/A on non-macOS" in c.detail for c in checks)
    assert any(c.name == "Accessibility permission" and "N/A on non-macOS" in c.detail for c in checks)


def test_check_computer_environment_missing_permissions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(computer_doctor, "check_macos_screen_capture_permission", lambda: False)
    monkeypatch.setattr(computer_doctor, "check_macos_accessibility_permission", lambda: False)
    checks = computer_doctor.check_computer_environment()
    assert any(c.name == "Screen Recording permission" and not c.ok for c in checks)
    assert any(c.name == "Accessibility permission" and not c.ok for c in checks)


@pytest.mark.asyncio
async def test_smoke_test_aborts_early_on_non_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    ok, summary, steps = await computer_doctor.run_computer_smoke_test()
    assert not ok
    assert "requires macOS" in summary


@pytest.mark.asyncio
async def test_smoke_test_aborts_early_if_permissions_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(computer_doctor, "check_macos_screen_capture_permission", lambda: False)
    monkeypatch.setattr(computer_doctor, "check_macos_accessibility_permission", lambda: True)

    ok, summary, steps = await computer_doctor.run_computer_smoke_test()
    assert not ok
    assert "Permission preflight failed" in summary
    assert any("Screen Recording permission missing" in detail for _, _, detail in steps)


@pytest.mark.asyncio
async def test_smoke_test_aborts_if_ax_permission_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(computer_doctor, "check_macos_screen_capture_permission", lambda: True)
    monkeypatch.setattr(computer_doctor, "check_macos_accessibility_permission", lambda: False)

    ok, summary, steps = await computer_doctor.run_computer_smoke_test()
    assert not ok
    assert "Permission preflight failed" in summary
    assert any("Accessibility permission missing" in detail for _, _, detail in steps)


class MockSmokeBackend:
    def __init__(self, fail_observe_textedit: bool = False, fail_verify: bool = False) -> None:
        self.fail_observe_textedit = fail_observe_textedit
        self.fail_verify = fail_verify
        self.typed_text = ""
        self.clicks: list[tuple[int, int]] = []
        self.pressed: list[str] = []

    async def observe(self, shot_path: Path | None, app_name: str | None = None):
        if shot_path is not None:
            shot_path.write_bytes(b"\x89PNG\r\n\x1a\nfakeimage")
            return "Finder", "Desktop", [A11yElement("AXWindow", "Desktop", x=0, y=0, width=800, height=600)]
        if app_name == "TextEdit":
            if self.fail_observe_textedit:
                return "Finder", "Desktop", []
            elems = [
                A11yElement(
                    "AXTextArea",
                    "Text Area",
                    x=100,
                    y=100,
                    width=400,
                    height=300,
                    description=self.typed_text if not self.fail_verify else "",
                )
            ]
            return "TextEdit", "Untitled", elems
        return "Terminal", "Terminal", [A11yElement("AXWindow", "Terminal", x=50, y=50, width=500, height=400)]

    async def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))

    async def type_text(self, text: str) -> None:
        self.typed_text += text

    async def press(self, key: str) -> None:
        self.pressed.append(key)


@pytest.mark.asyncio
async def test_smoke_test_success_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(computer_doctor, "check_macos_screen_capture_permission", lambda: True)
    monkeypatch.setattr(computer_doctor, "check_macos_accessibility_permission", lambda: True)
    mock_backend = MockSmokeBackend()
    monkeypatch.setattr(computer_doctor, "default_computer_backend", lambda: mock_backend)
    monkeypatch.setattr(computer_doctor.subprocess, "run", MagicMock())

    ok, summary, steps = await computer_doctor.run_computer_smoke_test()
    assert ok
    assert "passed successfully" in summary
    assert len(steps) >= 8
    assert mock_backend.clicks
    assert mock_backend.typed_text.startswith("Lilly-Verify-")
    assert "return" in mock_backend.pressed


@pytest.mark.asyncio
async def test_smoke_test_textedit_launch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(computer_doctor, "check_macos_screen_capture_permission", lambda: True)
    monkeypatch.setattr(computer_doctor, "check_macos_accessibility_permission", lambda: True)
    mock_backend = MockSmokeBackend(fail_observe_textedit=True)
    monkeypatch.setattr(computer_doctor, "default_computer_backend", lambda: mock_backend)
    monkeypatch.setattr(computer_doctor.subprocess, "run", MagicMock())

    import asyncio

    async def fast_sleep(_):
        pass

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    ok, summary, steps = await computer_doctor.run_computer_smoke_test()
    assert not ok
    assert "TextEdit launch failed" in summary


@pytest.mark.asyncio
async def test_smoke_test_verification_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(computer_doctor, "check_macos_screen_capture_permission", lambda: True)
    monkeypatch.setattr(computer_doctor, "check_macos_accessibility_permission", lambda: True)
    mock_backend = MockSmokeBackend(fail_verify=True)
    monkeypatch.setattr(computer_doctor, "default_computer_backend", lambda: mock_backend)
    monkeypatch.setattr(computer_doctor.subprocess, "run", MagicMock())

    import asyncio

    async def fast_sleep(_):
        pass

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    ok, summary, steps = await computer_doctor.run_computer_smoke_test()
    assert not ok
    assert "Visible-state verification failed" in summary


def test_cli_cmd_computer_doctor(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace()
    ret = cli.cmd_computer_doctor(args)
    captured = capsys.readouterr().out
    assert "OS Platform" in captured
    assert ret in (0, 1)


def test_cli_cmd_computer_smoke_test(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace()
    mock_steps = [("Permission check", True, "OK"), ("Screenshot capture", True, "2.2 MB")]

    async def fake_smoke():
        return True, "All real-Mac desktop control checks passed", mock_steps

    monkeypatch.setattr(computer_doctor, "run_computer_smoke_test", fake_smoke)
    ret = cli.cmd_computer_smoke_test(args)
    assert ret == 0
    captured = capsys.readouterr().out
    assert "Permission check" in captured
    assert "All real-Mac desktop control checks passed" in captured

