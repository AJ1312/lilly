"""A stand-in for Docker or Podman that follows the `Engines` contract and records what it was asked."""
from __future__ import annotations

import asyncio

from lilly.domain.devbox import OutputSink, RunResult
from lilly.domain.errors import ToolError


class FakeEngine:
    name = "fake"

    def __init__(self, *, image_ready: bool = True, state: str = "missing") -> None:
        self.image_ready, self.box = image_ready, state
        self.calls: list[str] = []
        self.created_with: list[list[str]] = []
        self.ran: list[list[str]] = []
        self.output = "hello\n"
        self.exit_code: int | None = 0
        self.hang = False                     # the next command never finishes (reported as timed out)
        self.delay = 0.0
        self.running_now = self.peak = 0
        self.fail_start = False

    async def image_present(self, image: str) -> bool:
        return self.image_ready

    async def pull(self, image: str) -> None:
        self.calls.append("pull")
        self.image_ready = True

    async def state(self) -> str:
        return self.box

    async def create(self, args: list[str]) -> None:
        self.calls.append("create")
        self.created_with.append(args)
        self.box = "stopped"

    async def start(self) -> None:
        self.calls.append("start")
        if self.fail_start:
            raise ToolError("no")
        self.box = "running"

    async def stop(self) -> None:
        self.calls.append("stop")
        self.box = "stopped"

    async def remove(self) -> None:
        self.calls.append("remove")
        self.box = "missing"

    async def run(self, args: list[str], timeout_s: float, on_output: OutputSink | None) -> RunResult:
        assert self.box == "running", "a command was sent to a box that is not running"
        self.calls.append("run")
        self.ran.append(args)
        self.running_now += 1
        self.peak = max(self.peak, self.running_now)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.hang:
                return RunResult(None, "partial", timed_out=True)
            if on_output is not None:
                on_output(self.output[:3])
                on_output(self.output)
            return RunResult(self.exit_code, self.output)
        finally:
            self.running_now -= 1
