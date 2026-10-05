"""DevboxManager: starts the box when a command needs it, runs one command at a time, stops it when idle.

The box is created from `create_args` and nothing else. A box left over from an earlier run of Lilly, or built with
older settings, is destroyed and rebuilt instead of trusted. A command that runs out of time destroys the box, because
something it started may still be running; the shared folder keeps its files."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lilly.domain.clock import Clock
from lilly.domain.devbox import (
    MAX_COMMAND_CHARS,
    DevboxSettings,
    Engines,
    OutputSink,
    RunResult,
    create_args,
    exec_args,
    folder_problem,
    relative_problem,
)
from lilly.domain.errors import ConflictError, ToolError, ValidationFailed
from lilly.domain.policy import PathScope

log = logging.getLogger("lilly.devbox")
REAP_EVERY_S = 15.0

EngineFinder = Callable[[DevboxSettings], Engines | None]


class DevboxManager:
    def __init__(self, settings: Callable[[], DevboxSettings], scope: Callable[[], PathScope], find: EngineFinder,
                 clock: Clock, ids: tuple[int, int] | None = None) -> None:
        self._settings, self._scope, self._find, self._clock = settings, scope, find, clock
        self._ids = ids or (os.getuid(), os.getgid())
        self._lock = asyncio.Lock()
        self._built_with: list[str] | None = None      # the create arguments of the box THIS run of Lilly made
        self._last_used: float | None = None
        self._reaper: asyncio.Task[None] | None = None
        self._warming: asyncio.Task[None] | None = None
        self._preparing: asyncio.Task[None] | None = None
        self._prepare_error: str | None = None

    # ---- what the settings screen shows ---------------------------------------------------------
    async def status(self) -> dict[str, Any]:
        cfg = self._settings()
        engine = self._find(cfg)
        out: dict[str, Any] = {"engine": engine.name if engine else None, "image": cfg.image, "image_ready": False,
                               "state": "unavailable", "folder_ok": self._folder_problem(cfg) is None,
                               "folder_problem": self._folder_problem(cfg),
                               "preparing": self._preparing is not None and not self._preparing.done(),
                               "prepare_error": self._prepare_error}
        if engine is not None:
            try:
                out["image_ready"] = await engine.image_present(cfg.image)
                out["state"] = await engine.state()
            except (OSError, TimeoutError, ToolError):
                out["state"] = "unavailable"
        return out

    def _folder_problem(self, cfg: DevboxSettings) -> str | None:
        if not cfg.shared_folder:
            return "choose a shared folder first"
        if (bad := folder_problem(cfg.shared_folder)) is not None:
            return bad
        if not self._scope().allows(cfg.shared_folder):
            return "the shared folder must be inside a folder you have shared with Lilly"
        real = Path(os.path.realpath(cfg.shared_folder))     # this is what gets mounted, so it is judged too
        if (bad := folder_problem(str(real))) is not None:
            return f"the shared folder points to {real}, which cannot be shared: {bad}"
        if not real.is_dir():
            return "the shared folder does not exist"
        if self._scope().shields(real):
            return "the shared folder holds folders Lilly keeps private (such as its own data or your keys); choose a smaller one"
        return None

    def begin_prepare(self) -> None:
        """Download the image in the background. Only ever started by the owner, from Settings."""
        if self._preparing is not None and not self._preparing.done():
            raise ConflictError("the image is already being downloaded")
        cfg = self._settings()
        engine = self._find(cfg)
        if engine is None:
            raise ConflictError("Docker or Podman is not installed on this computer")
        self._prepare_error = None
        self._preparing = asyncio.create_task(self._prepare(engine, cfg.image), name="lilly-devbox-prepare")

    async def _prepare(self, engine: Engines, image: str) -> None:
        try:
            await engine.pull(image)
        except (OSError, TimeoutError, ToolError) as exc:
            self._prepare_error = str(exc) if isinstance(exc, ToolError) else "the image could not be downloaded"

    async def prepare(self) -> None:
        """Download the image and wait for it."""
        self.begin_prepare()
        assert self._preparing is not None
        await self._preparing
        if self._prepare_error:
            raise ToolError(self._prepare_error)

    # ---- running a command ----------------------------------------------------------------------
    async def run(self, rel_dir: str, command: str, on_output: OutputSink | None = None) -> RunResult:
        if not command.strip() or len(command) > MAX_COMMAND_CHARS:
            raise ValidationFailed(f"the command must be 1 to {MAX_COMMAND_CHARS} characters")
        if (bad := relative_problem(rel_dir)) is not None:
            raise ValidationFailed(bad)
        cfg = self._settings()
        engine = self._need_engine(cfg)
        if (problem := self._folder_problem(cfg)) is not None:
            raise ToolError(f"the devbox cannot start: {problem}")
        async with self._lock:
            self._reaper = self._reaper or asyncio.create_task(self._reap(), name="lilly-devbox-reaper")
            self._last_used = self._clock()
            await self._ensure(engine, cfg)
            try:
                result = await engine.run(exec_args(rel_dir, command), cfg.command_timeout_s, on_output)
            except BaseException:
                # Stopped, cancelled or broken part-way: the command may still be running inside the box.
                await asyncio.shield(self._destroy(engine))
                raise
            if result.timed_out:
                await self._destroy(engine)
            self._last_used = self._clock()
            return result

    def warm(self) -> None:
        """Start the box in the background because a plan is about to use it, so the first command finds it ready.
        Does nothing when it is already starting or running, cannot start, or has no downloaded image."""
        if self._warming is not None and not self._warming.done():
            return
        self._warming = asyncio.create_task(self._warm(), name="lilly-devbox-warm")

    async def _warm(self) -> None:
        cfg = self._settings()
        engine = self._find(cfg)
        if engine is None or self._folder_problem(cfg) is not None or self._lock.locked():
            return
        try:
            async with self._lock:
                self._reaper = self._reaper or asyncio.create_task(self._reap(), name="lilly-devbox-reaper")
                self._last_used = self._clock()
                await self._ensure(engine, cfg)
        except (OSError, TimeoutError, ToolError):
            log.info("the devbox could not be warmed up; it will be started when a command needs it")

    def _need_engine(self, cfg: DevboxSettings) -> Engines:
        engine = self._find(cfg)
        if engine is None:
            raise ToolError("the devbox needs Docker or Podman, and neither is installed")
        return engine

    async def _ensure(self, engine: Engines, cfg: DevboxSettings) -> None:
        if not await engine.image_present(cfg.image):
            raise ToolError(f"the devbox image {cfg.image} has not been downloaded; use Prepare in Settings")
        args = create_args(cfg, os.path.realpath(cfg.shared_folder), *self._ids)
        state = await engine.state()
        if state != "missing" and self._built_with != args:
            await self._destroy(engine)             # left over from before, or built with other settings
            state = "missing"
        if state == "missing":
            await engine.create(args)
            self._built_with = args
            state = "stopped"
        if state == "stopped":
            await engine.start()

    # ---- stopping ---------------------------------------------------------------------------------
    async def _destroy(self, engine: Engines) -> None:
        self._built_with = None
        await engine.remove()

    async def reset(self) -> None:
        """Remove the box now (Settings → Reset). Its files stay in the shared folder."""
        await self._remove_now()

    async def _remove_now(self) -> None:
        """Remove the box without waiting for the command that is running in it: removing it ends that command, and
        Stop all must not wait for a command to finish."""
        engine = self._find(self._settings())
        if engine is not None:
            with contextlib.suppress(OSError, TimeoutError, ToolError):
                await self._destroy(engine)

    async def close_all(self) -> None:
        """Stop all, and shutting Lilly down: nothing is left running, and the box is gone."""
        for task in (self._warming, self._reaper, self._preparing):
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._warming = self._reaper = self._preparing = None
        await self._remove_now()

    async def _reap(self) -> None:
        while True:
            await asyncio.sleep(REAP_EVERY_S)
            try:
                await self.reap_once()
            except Exception:
                log.exception("devbox clean-up failed")

    async def reap_once(self) -> None:
        """Stop a box that has been idle for a while and remove one idle for longer."""
        cfg = self._settings()
        engine = self._find(cfg)
        if engine is None or self._lock.locked():
            return
        async with self._lock:
            state = await engine.state()
            if state == "missing":
                return
            now = self._clock()
            if self._last_used is None:
                self._last_used = now                  # a box from before this run: start its clock now
            idle = now - self._last_used
            if idle >= cfg.destroy_after_s:
                await self._destroy(engine)
            elif state == "running" and idle >= cfg.idle_stop_s:
                await engine.stop()
