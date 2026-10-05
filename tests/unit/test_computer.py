"""Computer control: guard rails in the tools, and the policy rule that makes every use ask."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psutil
import pytest

from lilly.domain.errors import PolicyDenied, ToolError, ValidationFailed
from lilly.domain.labels import Label, Mode, Risk, TaskCtx, Verdict
from lilly.domain.plan import tool_call
from lilly.domain.policy import PathScope, decide
from lilly.domain.ports import ToolContext
from lilly.domain.tools_registry import DEFAULT_TOOLS
from lilly.tools import computer
from lilly.tools.computer import (
    NotifyTool,
    OpenAppTool,
    OpenUrlTool,
    RunCommandTool,
    StopProcessTool,
)

CTX = ToolContext("t", "s1", 30.0, lambda: False)


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    seen: list[list[str]] = []
    monkeypatch.setattr(computer, "_spawn_detached", seen.append)
    monkeypatch.setattr(computer, "_opener", lambda: "/usr/bin/open")
    return seen


@pytest.mark.parametrize("name", [n for n, s in DEFAULT_TOOLS.items() if s.confirm])
@pytest.mark.parametrize("mode", list(Mode))
def test_confirm_tools_ask_in_every_mode(name: str, mode: Mode) -> None:
    call = tool_call(name, DEFAULT_TOOLS[name], {})
    verdict, _ = decide(call, TaskCtx(mode=mode), PathScope(["/tmp"]))
    assert verdict in (Verdict.NEEDS_APPROVAL, Verdict.DENY)  # never ALLOW


def test_every_command_and_launch_tool_is_marked_confirm() -> None:
    for name in ("computer.open_url", "computer.open_app", "computer.stop_process", "computer.run"):
        assert DEFAULT_TOOLS[name].confirm and DEFAULT_TOOLS[name].risk is Risk.R2


def test_a_locked_agent_cannot_run_commands_that_read_private_data() -> None:
    call = tool_call("computer.run", DEFAULT_TOOLS["computer.run"], {})
    assert decide(call, TaskCtx(mode=Mode.LOCKED), PathScope(["/tmp"]))[0] is Verdict.DENY


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "ftp://x.test/", "ms-msdt:/id", "http:///x"])
async def test_only_web_links_are_opened(url: str, launched: list[list[str]]) -> None:
    with pytest.raises(ValidationFailed):
        await OpenUrlTool().run({"url": url}, CTX)
    assert launched == []


async def test_a_web_link_is_opened_by_the_system(launched: list[list[str]]) -> None:
    await OpenUrlTool().run({"url": "https://example.com/a?b=1"}, CTX)
    assert launched == [["/usr/bin/open", "https://example.com/a?b=1"]]


@pytest.mark.parametrize("name", ["-a evil", "../x", "a;b", "", "x" * 61])
async def test_application_names_are_validated(name: str, launched: list[list[str]]) -> None:
    with pytest.raises((ValidationFailed, ToolError)):
        await OpenAppTool().run({"name": name}, CTX)
    assert launched == []


async def test_notifications_pass_text_as_arguments_not_code(launched: list[list[str]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(computer.shutil, "which", lambda n: f"/usr/bin/{n}")
    await NotifyTool().run({"title": 'x" & do shell script "rm -rf ~', "message": "hi"}, CTX)
    argv = launched[0]
    assert argv[-2:] == ["hi", 'x" & do shell script "rm -rf ~'] or argv[-2:] == ['x" & do shell script "rm -rf ~', "hi"]
    assert all("do shell script" not in a for a in argv if a.startswith("-e") or a in argv[1:-2])


@pytest.fixture
def tool(tmp_path: Path) -> RunCommandTool:
    (tmp_path / "shared").mkdir()
    return RunCommandTool(PathScope([str(tmp_path / "shared")]))


async def test_a_command_runs_in_the_shared_folder_and_returns_its_output(tool: RunCommandTool, tmp_path: Path) -> None:
    (tmp_path / "shared" / "note.txt").write_text("hello")
    result = await tool.run({"command": "ls", "cwd": str(tmp_path / "shared")}, CTX)
    assert "note.txt" in result.output and "exit code 0" in result.output
    assert result.label is Label.PERSONAL and result.untrusted


async def test_the_default_folder_is_the_first_shared_one(tool: RunCommandTool, tmp_path: Path) -> None:
    result = await tool.run({"command": "pwd"}, CTX)
    assert str(tmp_path / "shared") in result.output


async def test_no_shared_folder_means_no_commands() -> None:
    with pytest.raises(ToolError, match="share a folder"):
        await RunCommandTool(PathScope([])).run({"command": "pwd"}, CTX)


async def test_commands_cannot_start_outside_the_shared_folders(tool: RunCommandTool, tmp_path: Path) -> None:
    with pytest.raises(PolicyDenied):
        await tool.run({"command": "ls", "cwd": str(tmp_path)}, CTX)


@pytest.mark.parametrize("command", [
    "sudo ls", "/usr/bin/sudo ls", "su root", "shutdown -h now", "rm -rf /", "rm -rf ~", "mkfs.ext4 /dev/sda",
    "dd if=/dev/zero of=/dev/sda", "bash -c 'sudo ls'", "diskutil eraseDisk x",
])
async def test_dangerous_programs_are_refused(command: str, tool: RunCommandTool) -> None:
    with pytest.raises(ToolError):
        await tool.run({"command": command}, CTX)


async def test_there_is_no_shell_so_pipes_and_substitution_are_plain_text(tool: RunCommandTool) -> None:
    result = await tool.run({"command": "echo a | cat; $(whoami) `id`"}, CTX)
    assert "a | cat; $(whoami) `id`" in result.output


async def test_the_environment_is_scrubbed(tool: RunCommandTool, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "super-secret")
    result = await tool.run({"command": "env"}, CTX)
    assert "super-secret" not in result.output


async def test_long_output_is_cut_and_timeouts_kill_the_whole_group(tool: RunCommandTool, monkeypatch: pytest.MonkeyPatch) -> None:
    big = await tool.run({"command": f"{sys.executable} -c \"print('x' * 200000)\""}, CTX)
    assert "[output cut at 64 KB]" in big.output and len(big.output) < 70_000
    short = ToolContext("t", "s1", 6.0, lambda: False)  # leaves 1 second
    slow = await tool.run({"command": f"{sys.executable} -c \"import time; time.sleep(30)\""}, short)
    assert "timed out" in slow.output


async def test_a_missing_program_is_reported(tool: RunCommandTool) -> None:
    with pytest.raises(ToolError, match="not found"):
        await tool.run({"command": "definitely-not-a-program"}, CTX)


async def test_stop_process_checks_identity_and_ends_only_what_was_named() -> None:
    import subprocess

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # nosec B603
    try:
        name = psutil.Process(child.pid).name()
        with pytest.raises(ToolError, match="not 'other'|is now"):
            await StopProcessTool().run({"pid": child.pid, "name": "other"}, CTX)
        assert child.poll() is None  # untouched
        await StopProcessTool().run({"pid": child.pid, "name": name}, CTX)
        child.wait(timeout=5)
        assert child.returncode is not None
    finally:
        if child.poll() is None:
            child.kill()


@pytest.mark.parametrize("pid", [0, 1, os.getpid(), os.getppid()])
async def test_stop_process_refuses_system_and_own_processes(pid: int) -> None:
    with pytest.raises(ToolError):
        await StopProcessTool().run({"pid": pid, "name": "x"}, CTX)
