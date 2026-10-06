"""Computer control: open links and apps, list and stop processes, show notifications, run commands.

Every tool here is `confirm` in the registry (or reversible and visible), so the user approves each use,
whatever the agent's access mode. The checks below are guard rails against mistakes, not the security boundary:
the boundary is that nothing runs until the person has read the exact command or target and said yes.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shlex
import shutil
import signal
import subprocess  # nosec B404 - launches the fixed system openers and the commands the user approved
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

import psutil

from lilly.domain.errors import ToolError, ValidationFailed
from lilly.domain.labels import Label
from lilly.domain.policy import PathScope
from lilly.domain.ports import ToolContext, ToolResult
from lilly.tools.base import Tool, bool_arg, int_arg, resolve_in_scope, str_arg

MAX_OUTPUT_BYTES = 64_000
MAX_RUN_S = 120.0
_APP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+-]{0,59}$")
_BLOCKED_PROGRAMS = frozenset({"sudo", "su", "doas", "pkexec", "shutdown", "reboot", "halt", "poweroff", "mkfs",
                               "fdisk", "diskutil", "launchctl", "csrutil", "nvram"})
_SHELLS = frozenset({"sh", "bash", "zsh", "fish", "dash", "ksh"})
_SAFE_ENV_KEYS = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR")


def _spawn_detached(argv: list[str]) -> None:
    """Start a program and let it live on its own; its output is not ours."""
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,  # nosec B603
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise ToolError(f"could not start it: {exc.strerror}") from exc


def _opener() -> str:
    tool = "open" if sys.platform == "darwin" else "xdg-open"
    found = shutil.which(tool)
    if found is None:
        raise ToolError(f"this computer has no '{tool}' command")
    return found


class OpenUrlTool(Tool):
    name = "computer.open_url"

    def summary(self, args: Mapping[str, object], output: str) -> str:
        """The sentence shown as the answer when this tool ends a task."""
        url = str(args.get("url", ""))
        return f"Opened {url}."

    def standing_target(self, args: Mapping[str, object]) -> str | None:
        """Return the standing approval target for this tool."""
        url = str(args.get("url", "")).strip()
        parts = urlparse(url)
        return parts.hostname.lower() if parts.hostname else None

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        url = str_arg(args, "url", max_len=2000).strip()
        parts = urlparse(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValidationFailed("only http and https links can be opened")
        await asyncio.to_thread(_spawn_detached, [_opener(), url])
        return ToolResult(f"Opened {url}.", Label.PUBLIC, False)


class OpenAppTool(Tool):
    name = "computer.open_app"

    def summary(self, args: Mapping[str, object], output: str) -> str:
        """The sentence shown as the answer when this tool ends a task."""
        app = str(args.get("name", ""))
        return f"Opened {app}."

    def standing_target(self, args: Mapping[str, object]) -> str | None:
        """Return the standing approval target for this tool."""
        app = str(args.get("name", "")).strip()
        return app.lower() if app else None

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        app = str_arg(args, "name", max_len=60).strip()
        if not _APP_NAME.fullmatch(app):
            raise ValidationFailed("that is not a valid application name")
        if sys.platform == "darwin":
            argv = [_opener(), "-a", app]
        else:
            program = shutil.which(app.lower().replace(" ", "-"))
            if program is None:
                raise ToolError(f"'{app}' is not installed or not on the PATH")
            argv = [program]
        await asyncio.to_thread(_spawn_detached, argv)
        return ToolResult(f"Opened {app}.", Label.PUBLIC, False)


class ProcessesTool(Tool):
    name = "computer.processes"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        limit = int_arg(args, "limit", 15, lo=1, hi=50)
        by = str_arg(args, "sort", required=False) or "memory"
        if by not in ("memory", "cpu"):
            raise ValidationFailed("sort must be 'memory' or 'cpu'")
        rows = await asyncio.to_thread(_list_processes, by, limit)
        lines = [f"{r['pid']:>7}  {r['cpu']:>5.1f}% cpu  {r['memory']:>5.1f}% mem  {r['name']}" for r in rows]
        return ToolResult("pid      cpu          memory       name\n" + "\n".join(lines), Label.PERSONAL, False)


def _list_processes(by: str, limit: int) -> list[dict[str, float | int | str]]:
    me = psutil.Process().username()
    for p in psutil.process_iter():
        with contextlib.suppress(psutil.Error):
            p.cpu_percent(None)  # prime the counters; the second reading is the interval value
    psutil.cpu_percent(interval=0.3)
    rows: list[dict[str, float | int | str]] = []
    for p in psutil.process_iter(["pid", "name", "username", "memory_percent", "cpu_percent"]):
        with contextlib.suppress(psutil.Error):
            info = p.info
            if info["username"] == me:
                rows.append({"pid": info["pid"], "name": info["name"] or "unknown",
                             "memory": float(info["memory_percent"] or 0.0), "cpu": float(info["cpu_percent"] or 0.0)})
    rows.sort(key=lambda r: float(r["memory" if by == "memory" else "cpu"]), reverse=True)
    return rows[:limit]


class StopProcessTool(Tool):
    name = "computer.stop_process"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        pid = int_arg(args, "pid", 0, lo=0, hi=4_194_304)
        expected = str_arg(args, "name", max_len=200)
        force = bool_arg(args, "force")
        return await asyncio.to_thread(self._stop, pid, expected, force)

    @staticmethod
    def _stop(pid: int, expected: str, force: bool) -> ToolResult:
        if pid <= 1 or pid in (os.getpid(), os.getppid()):
            raise ToolError("that process cannot be stopped from here")
        try:
            proc = psutil.Process(pid)
            actual = proc.name()
            if proc.username() != psutil.Process().username():
                raise ToolError("that process belongs to another user")
        except psutil.NoSuchProcess:
            raise ToolError("no such process (it may already have ended)") from None
        except psutil.AccessDenied:
            raise ToolError("not allowed to inspect that process") from None
        if actual != expected:
            raise ToolError(f"process {pid} is now '{actual}', not '{expected}'; nothing was stopped")
        try:
            proc.kill() if force else proc.terminate()
            proc.wait(timeout=5)
        except psutil.TimeoutExpired:
            return ToolResult(f"Asked {actual} ({pid}) to stop, but it is still running. "
                              "Use force to end it immediately.", Label.PUBLIC, False)
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            raise ToolError("not allowed to stop that process") from None
        return ToolResult(f"Stopped {actual} ({pid}).", Label.PUBLIC, False)


class NotifyTool(Tool):
    name = "computer.notify"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        message = str_arg(args, "message", max_len=500)
        title = str_arg(args, "title", max_len=100, required=False) or "Lilly"
        if sys.platform == "darwin":
            script = ["-e", "on run argv", "-e", "display notification (item 1 of argv) with title (item 2 of argv)",
                      "-e", "end run"]
            argv = [shutil.which("osascript") or "osascript", *script, message, title]
        else:
            program = shutil.which("notify-send")
            if program is None:
                raise ToolError("this computer has no 'notify-send' command")
            argv = [program, "--", title, message]
        await asyncio.to_thread(_spawn_detached, argv)
        return ToolResult("Notification shown.", Label.PUBLIC, False)


class RunCommandTool(Tool):
    name = "computer.run"

    def __init__(self, scope: PathScope) -> None:
        self._scope = scope

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        argv = self._argv(str_arg(args, "command", max_len=4000))
        cwd = self._cwd(str_arg(args, "cwd", required=False))
        limit = max(1.0, min(MAX_RUN_S, ctx.deadline_s - 5.0))
        return await _run_group(argv, cwd, limit)

    @staticmethod
    def _argv(command: str) -> list[str]:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise ValidationFailed(f"cannot read that command: {exc}") from exc
        if not argv:
            raise ValidationFailed("the command is empty")
        if not Path(argv[0]).is_file() and " " in command:
            # Keep an unquoted executable path with spaces intact; execution remains shell-free.
            for end in range(len(command), 0, -1):
                candidate = command[:end].rstrip()
                rest = command[end:].lstrip()
                if rest and Path(candidate).is_file() and os.access(candidate, os.X_OK):
                    try:
                        argv = [candidate, *shlex.split(rest)]
                    except ValueError as exc:
                        raise ValidationFailed(f"cannot read that command: {exc}") from exc
                    break
        program = Path(argv[0]).name
        if program in _BLOCKED_PROGRAMS or program.startswith("mkfs"):
            raise ToolError(f"'{program}' is not allowed")
        if program == "rm" and any(a in ("/", "~", "/*", "~/*") for a in argv[1:]):
            raise ToolError("that would remove everything it points at; name the exact folder instead")
        if program == "dd" and any(a.startswith("of=/dev/") for a in argv[1:]):
            raise ToolError("writing to a disk device is not allowed")
        if program in _SHELLS and "-c" in argv:
            inner = " ".join(argv)
            if re.search(r"\b(sudo|su|doas|pkexec|mkfs|shutdown|reboot)\b", inner):
                raise ToolError("that shell command uses a program that is not allowed")
        return argv

    def _cwd(self, raw: str) -> Path:
        if raw:
            return resolve_in_scope(raw, self._scope)
        roots = self._scope.roots
        if not roots:
            raise ToolError("share a folder first (Settings → Privacy & access); commands run inside a shared folder")
        return roots[0]


async def _run_group(argv: list[str], cwd: Path, limit_s: float) -> ToolResult:
    env = {k: os.environ[k] for k in _SAFE_ENV_KEYS if k in os.environ}
    env.setdefault("LANG", "C.UTF-8")
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=cwd, env=env, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, start_new_session=True)
    except FileNotFoundError:
        raise ToolError(f"'{argv[0]}' was not found") from None
    except OSError as exc:
        raise ToolError(f"could not run it: {exc.strerror}") from exc
    assert proc.stdout is not None
    captured = bytearray()
    truncated = False

    async def drain() -> None:
        nonlocal truncated
        while chunk := await proc.stdout.read(8192):  # type: ignore[union-attr]
            room = MAX_OUTPUT_BYTES - len(captured)
            if room > 0:
                captured.extend(chunk[:room])
            if len(chunk) > room:
                truncated = True  # keep reading so the process is not blocked, but keep nothing more

    timed_out = False
    try:
        async with asyncio.timeout(limit_s):
            await asyncio.gather(drain(), proc.wait())
    except TimeoutError:
        timed_out = True
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)  # the whole group, so children do not outlive the command
            with contextlib.suppress(Exception):
                await proc.wait()
    text = captured.decode("utf-8", errors="replace")
    if truncated:
        text += "\n[output cut at 64 KB]"
    if timed_out:
        text += f"\n[stopped after {limit_s:.0f}s]"
    status = "timed out" if timed_out else f"exit code {proc.returncode}"
    return ToolResult(f"$ {shlex.join(argv)}\n{status}\n{text}".rstrip(), Label.PERSONAL, True)
