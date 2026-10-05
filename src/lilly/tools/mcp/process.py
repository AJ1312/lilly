"""Starting and stopping one MCP server process. Never a shell; the environment is built from scratch."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import signal
import subprocess  # nosec B404 - only used for the Windows process-group flag
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from lilly.domain.errors import ToolError
from lilly.domain.mcp import INHERITED_ENV, MAX_MESSAGE_BYTES, McpServerConfig
from lilly.tools.mcp.protocol import McpStartRefused

log = logging.getLogger("lilly.mcp")

STDERR_KEEP = 4096
GRACE_S = 0.3        # how long a server gets to exit after its stdin is closed
TERM_WAIT_S = 2.0    # how long after SIGTERM before SIGKILL


def build_env(cfg: McpServerConfig, resolve_secret: Callable[[str], str | None],
              parent: Mapping[str, str]) -> dict[str, str]:
    """The child's whole environment: inherited basics, the configured values, then resolved secrets.

    Nothing else from the parent (LILLY_*, API keys, proxies) is passed on. A missing secret refuses the start;
    the error names only the variable."""
    env = {k: parent[k] for k in INHERITED_ENV if k in parent}
    env.update(cfg.env)
    for var, ref in cfg.secret_env.items():
        value = resolve_secret(ref)
        if not value or "\x00" in value:
            raise McpStartRefused(f"the secret for {var} is not set; add it in Settings")
        env[var] = value
    return env


class McpProcess:
    """One server child process in its own process group, with stderr kept as a small ring buffer."""

    def __init__(self, cfg: McpServerConfig, resolve_secret: Callable[[str], str | None], cwd: Path | None = None,
                 parent_env: Mapping[str, str] | None = None) -> None:
        self._cfg, self._resolve, self._cwd = cfg, resolve_secret, cwd
        self._parent = os.environ if parent_env is None else parent_env
        self._proc: asyncio.subprocess.Process | None = None
        self._pid = 0
        self._tmp: str | None = None
        self._tail = b""
        self._stderr_task: asyncio.Task[None] | None = None
        self._stop_lock = asyncio.Lock()

    async def start(self) -> None:
        env = await asyncio.to_thread(build_env, self._cfg, self._resolve, self._parent)   # a keychain may be slow
        if self._cwd is None:
            self._tmp = tempfile.mkdtemp(prefix="lilly-mcp-")
            cwd = Path(self._tmp)
        else:
            cwd = self._cwd
            cwd.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined,unused-ignore]
        else:
            kwargs["start_new_session"] = True
        try:
            self._proc = await asyncio.create_subprocess_exec(  # argv list, never a shell; scrubbed env
                self._cfg.command, *self._cfg.args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=cwd, env=env, limit=MAX_MESSAGE_BYTES + 2, **kwargs)
        except (OSError, ValueError) as exc:
            self._remove_tmp()
            raise ToolError(f"could not start the server: {getattr(exc, 'strerror', None) or 'invalid command'}") from exc
        self._pid = self._proc.pid
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    @property
    def stdout(self) -> asyncio.StreamReader:
        assert self._proc is not None and self._proc.stdout is not None
        return self._proc.stdout

    def write(self, data: bytes) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(data)

    async def drain(self) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        await self._proc.stdin.drain()

    def stderr_tail(self) -> str:
        return self._tail.decode("utf-8", "replace")

    async def _drain_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        while chunk := await self._proc.stderr.read(4096):
            self._tail = (self._tail + chunk)[-STDERR_KEEP:]

    def _signal(self, name: str) -> None:
        """Signal the whole process group (POSIX) or the process (Windows)."""
        if self._pid <= 1:
            return
        if sys.platform == "win32":
            if self._proc is not None and self._proc.returncode is None:
                with contextlib.suppress(OSError):
                    self._proc.terminate() if name == "SIGTERM" else self._proc.kill()
            return
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(self._pid, getattr(signal, name))

    async def stop(self) -> None:
        """Close stdin, give the server a moment, then SIGTERM and SIGKILL its group. Safe to call twice."""
        async with self._stop_lock:
            proc = self._proc
            if proc is None:
                return
            if proc.stdin is not None and not proc.stdin.is_closing():
                with contextlib.suppress(OSError, RuntimeError):
                    proc.stdin.close()
            for name, wait in (("", GRACE_S), ("SIGTERM", TERM_WAIT_S), ("SIGKILL", TERM_WAIT_S)):
                if proc.returncode is not None:
                    break
                if name:
                    self._signal(name)
                with contextlib.suppress(TimeoutError):
                    async with asyncio.timeout(wait):
                        await proc.wait()
            self._signal("SIGKILL")  # sweep anything the server left behind in its group
            self._proc = None
            if proc.returncode is None:
                await proc.wait()
            await self._finish(proc)

    async def _finish(self, proc: asyncio.subprocess.Process) -> None:
        task, self._stderr_task = self._stderr_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        transport = getattr(proc, "_transport", None)
        if transport is not None:
            transport.close()
        self._remove_tmp()
        if self._tail:
            log.debug("mcp server %s stderr tail: %s", self._cfg.name, self.stderr_tail())

    def _remove_tmp(self) -> None:
        tmp, self._tmp = self._tmp, None
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
