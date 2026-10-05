"""Docker and Podman through their command line, with fixed argument lists and no shell.

Only the exec output is read as text; everything else is judged by exit code. Never run in tests: tests use a fake
that follows the same `Engines` contract, and this file is checked by hand on a real engine (see docs/VERIFICATION.md)."""
from __future__ import annotations

import asyncio
import codecs
import contextlib
import os
import shutil
import signal
from collections.abc import Callable

from lilly.domain.devbox import CONTAINER_NAME, MAX_OUTPUT_CHARS, Engine, OutputSink, RunResult
from lilly.domain.errors import ToolError

KILL_GRACE_S = 5.0
PULL_S = 1800.0                      # a first download can be large
QUICK_S = 60.0                       # inspect, create, start, stop and remove all answer quickly
_PREFERRED = (Engine.DOCKER, Engine.PODMAN)


def find_engine(wanted: Engine, which: Callable[[str], str | None] = shutil.which) -> tuple[str, str] | None:
    """(name, path) of the engine to use, or None when none is installed."""
    for name in (_PREFERRED if wanted is Engine.AUTO else (wanted,)):
        if (path := which(name.value)) is not None:
            return name.value, path
    return None


class CliEngine:
    def __init__(self, name: str, path: str) -> None:
        self.name, self._path = name, path

    async def _call(self, *args: str, timeout_s: float = QUICK_S) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            self._path, *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, start_new_session=True)
        try:
            async with asyncio.timeout(timeout_s):
                out, _ = await proc.communicate()
        except BaseException:
            await _kill(proc)
            raise
        return proc.returncode or 0, out.decode("utf-8", "replace")

    async def image_present(self, image: str) -> bool:
        code, _ = await self._call("image", "inspect", "--format", "{{.Id}}", image)
        return code == 0

    async def pull(self, image: str) -> None:
        code, out = await self._call("pull", "--quiet", image, timeout_s=PULL_S)
        if code != 0:
            raise ToolError(f"the image could not be downloaded: {out.strip()[-300:] or 'no reason given'}")

    async def state(self) -> str:
        code, out = await self._call("container", "inspect", "--format", "{{.State.Running}}", CONTAINER_NAME)
        if code != 0:
            return "missing"
        return "running" if out.strip() == "true" else "stopped"

    async def _must(self, *args: str) -> None:
        code, out = await self._call(*args)
        if code != 0:
            raise ToolError(f"the devbox engine refused: {out.strip()[-300:] or 'no reason given'}")

    async def create(self, args: list[str]) -> None:
        await self._must(*args)

    async def start(self) -> None:
        await self._must("start", CONTAINER_NAME)

    async def stop(self) -> None:
        await self._call("stop", "--time", "2", CONTAINER_NAME)

    async def remove(self) -> None:
        await self._call("rm", "--force", "--volumes", CONTAINER_NAME)

    async def run(self, args: list[str], timeout_s: float, on_output: OutputSink | None) -> RunResult:
        proc = await asyncio.create_subprocess_exec(
            self._path, *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, limit=1_000_000, start_new_session=True)
        assert proc.stdout is not None
        decoder = codecs.getincrementaldecoder("utf-8")("replace")     # a character may straddle two reads
        text, dropped, timed_out = "", False, False
        try:
            async with asyncio.timeout(timeout_s):
                while chunk := await proc.stdout.read(4096):
                    text += decoder.decode(chunk)
                    if len(text) > MAX_OUTPUT_CHARS:
                        text, dropped = text[-MAX_OUTPUT_CHARS:], True
                    if on_output is not None:
                        on_output(text)
                text += decoder.decode(b"", final=True)
                await proc.wait()
        except TimeoutError:
            timed_out = True
        except BaseException:
            await _kill(proc)
            raise
        if timed_out:
            await _kill(proc)       # the command inside the box may live on: the caller destroys the box
        return RunResult(None if timed_out else proc.returncode, text, dropped, timed_out)


async def _kill(proc: asyncio.subprocess.Process) -> None:
    """End the engine's command line and anything it started (it runs in its own process group)."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(proc.wait(), KILL_GRACE_S)
