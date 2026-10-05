"""The composition root. `Runtime` builds every service exactly once and owns their lifetime.

The UI and the daemon talk to Lilly only through this object, so there is one place where the pieces are
tied together and one place where they are shut down.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from lilly.app.laya import LayaService
from lilly.app.paths import LillyPaths
from lilly.app.power import Caffeinate
from lilly.decide.rules import InstructionRules, LoopRule, MatchRule, SearchRanker
from lilly.decide.small_model import SmallModelDecider
from lilly.domain.clock import Clock
from lilly.domain.decisions import Decider
from lilly.domain.devbox import Engine, Engines
from lilly.domain.grants import GrantStore
from lilly.domain.pets import look_to_dict
from lilly.domain.policy import PathScope
from lilly.domain.ports import KeyStore
from lilly.domain.settings import Settings, load_settings, save_settings
from lilly.engine.approvals import ApprovalService
from lilly.engine.bus import EventBus
from lilly.engine.decisions import DatabaseSink, DecisionPipeline
from lilly.engine.orchestrator import Orchestrator
from lilly.engine.runner import EngineDeps
from lilly.engine.scheduler import Scheduler
from lilly.providers.http import create_http_client, create_local_client
from lilly.providers.keys import open_key_store
from lilly.providers.router import ModelRouter
from lilly.store import agents, conversations, memory, retention, routines, snapshot, spaces
from lilly.store import mcp as mcp_store
from lilly.store.connection import open_reader
from lilly.store.db import Database
from lilly.tools import Tool, build_tools
from lilly.tools.browser.manager import BrowserManager
from lilly.tools.devbox.engines import CliEngine, find_engine
from lilly.tools.devbox.manager import DevboxManager
from lilly.tools.mcp import McpManager

log = logging.getLogger("lilly.runtime")

# Folders that hold credentials. No task may touch them, even when they sit inside a shared folder.
SENSITIVE_DIRS = ("~/.ssh", "~/.aws", "~/.gnupg", "~/.config/gcloud", "~/.kube", "~/Library/Keychains")


def _engine_for(wanted: Engine) -> Engines | None:
    """Docker or Podman as installed on this computer, or None."""
    found = find_engine(wanted)
    return CliEngine(*found) if found else None


TICK_S = 10.0                  # while tasks are running
IDLE_SLEEP_S = 60.0            # with nothing running: at most this long between looks, sooner when a routine is due
PRUNE_EVERY_S = 3600.0
BACKUP_EVERY_S = 86400.0
BACKUP_RETRY_S = 3600.0        # after a failed backup


@dataclass(slots=True)
class Maintenance:
    last_prune: float = 0.0
    last_backup: float = 0.0
    last_backup_file: str | None = None
    integrity_ok: bool | None = None
    backup_retry_at: float = 0.0


class Runtime:
    """Everything Lilly is made of, built once."""

    def __init__(self, paths: LillyPaths, db: Database, keys: KeyStore, client: httpx.AsyncClient,
                 local_client: httpx.AsyncClient, owns_clients: bool, clock: Clock, settings: Settings,
                 problems: list[str]) -> None:
        self.paths, self.db, self.keys, self.client, self.clock = paths, db, keys, client, clock
        self.local_client, self._owns_clients = local_client, owns_clients
        self.settings, self.settings_problems = settings, problems
        self.started_at = clock()
        self.bus = EventBus()
        self.grants = GrantStore()
        self.router = ModelRouter(settings, keys, client, db, self.grants, local_client)
        self.approvals = ApprovalService(db, self.bus, clock)
        self.scope = self._build_scope(settings)
        self.mcp = McpManager(self._secret)
        self.browser = BrowserManager(lambda: self.settings.browser)
        self.devbox = DevboxManager(lambda: self.settings.devbox, lambda: self.scope,
                                    lambda cfg: _engine_for(cfg.runtime), self.clock)
        self._mcp_lock = asyncio.Lock()      # database read and configure happen together, one reload at a time
        self.tools: dict[str, Tool] = {**self._build_tools(settings), **self.mcp.tools()}
        self.laya = LayaService(paths.root / "addons" / "laya")
        self._static_deciders: dict[str, Decider] = {"search": SearchRanker(), "loop": LoopRule(),
                                                     "rules": InstructionRules(), "match": MatchRule()}
        self._small: tuple[str, SmallModelDecider] | None = None
        self.decisions = DecisionPipeline(lambda: self.settings.decisions, self._deciders, DatabaseSink(db), clock)
        self.orchestrator = Orchestrator(EngineDeps(
            db, self.router, lambda: self.tools, lambda: self.scope, lambda: self.settings.file_roots, self.bus,
            self.approvals, self.grants, clock, lambda: self.settings.limits, self.decisions,
            engine_settings=lambda: self.settings.engine))
        self.scheduler = Scheduler(db, self.orchestrator, clock)
        self._wake = asyncio.Event()
        self.maintenance = Maintenance()
        if (newest := snapshot.newest_backup(paths.backups)) is not None:     # a restart is not a reason to back up
            self.maintenance.last_backup, self.maintenance.last_backup_file = newest.stat().st_mtime, newest.name
        self.power = Caffeinate()
        self._background: list[asyncio.Task[None]] = []
        self._observers: list[Callable[[Settings], Awaitable[None]]] = []

    def _deciders(self) -> dict[str, Decider]:
        """The deciders that exist right now, looked up for every question so that a local model switched on or
        Laya installed a moment ago counts at once. The small-model decider uses the first enabled local model;
        one that is not available is simply absent, and a chain that names it skips it."""
        found = dict(self._static_deciders)
        local = next((m.name for m in self.settings.models if m.local and m.enabled), None)
        if local is not None:
            if self._small is None or self._small[0] != local:
                self._small = (local, SmallModelDecider(self.router, local))
            found["small_model"] = self._small[1]
        if (laya := self.laya.decider) is not None:
            found["laya"] = laya
        return found

    @classmethod
    async def create(cls, paths: LillyPaths, *, client: httpx.AsyncClient | None = None,
                     local_client: httpx.AsyncClient | None = None, keys: KeyStore | None = None,
                     clock: Clock = time.time) -> Runtime:
        settings, problems = load_settings(paths.settings)
        owns_clients = client is None
        rt = cls(paths, Database(paths.db), keys or open_key_store(paths.config),
                 client or create_http_client(), local_client or client or create_local_client(),
                 owns_clients, clock, settings, problems)
        try:
            await rt.router.start()
            await rt.reload_mcp()
            rt.orchestrator.configure(settings)
            await rt.orchestrator.start()
        except BaseException:
            await rt.close()
            raise
        rt._background = [asyncio.create_task(rt._housekeeping(), name="lilly-housekeeping"),
                          asyncio.create_task(rt._wake_on_tasks(), name="lilly-wake-on-tasks")]
        return rt

    # ---- wiring ---------------------------------------------------------------------
    def _build_scope(self, settings: Settings) -> PathScope:
        return PathScope(settings.file_roots, deny=(str(self.paths.root), *SENSITIVE_DIRS))

    def _build_tools(self, settings: Settings) -> dict[str, Tool]:
        return build_tools(settings, scope=self.scope, db=self.db, router=self.router, keys=self.keys,
                           client=self.client, clock=self.clock,
                           browser=(self.browser, lambda: self.settings.browser), devbox=self.devbox)

    def _secret(self, ref: str) -> str | None:
        found = self.keys.get(ref)
        return found.reveal() if found else None

    async def reload_mcp(self) -> None:
        """Apply the stored MCP servers and approvals. Unchanged running servers keep running; the tool set the
        planner sees is rebuilt from what the owner approved."""
        async with self._mcp_lock:
            servers, approvals = await self.db.write(
                lambda con: (mcp_store.list_servers(con), mcp_store.get_approvals(con)))
            await self.mcp.configure(servers, approvals)
            self.tools = {**self._build_tools(self.settings), **self.mcp.tools()}

    async def apply_settings(self, new: Settings) -> None:
        """Save, then switch every service to the new settings. Running tasks pick them up at their next step;
        model counters and circuit breakers of unchanged models are kept."""
        await asyncio.to_thread(save_settings, self.paths.settings, new)
        self.settings, self.settings_problems = new, []
        self.scope = self._build_scope(new)
        self.tools = {**self._build_tools(new), **self.mcp.tools()}
        await self.router.configure(new)
        self.orchestrator.configure(new)
        self._sync_power()
        for observe in self._observers:
            try:
                await observe(new)
            except Exception:
                log.exception("a settings observer failed")

    def observe_settings(self, observer: Callable[[Settings], Awaitable[None]]) -> None:
        """Be told after every settings change (a chat bridge starts or stops here). An observer that raises is
        logged and does not stop the change."""
        self._observers.append(observer)

    async def refresh_keys(self) -> None:
        await self.router.refresh_keys()

    # ---- maintenance ----------------------------------------------------------------
    def _sync_power(self) -> None:
        self.power.sync(self.settings.stay_awake or self.orchestrator.active_count > 0)

    async def _housekeeping(self) -> None:
        while True:
            try:
                self._sync_power()
                await self._tick_routines()
                now = self.clock()
                if now - self.maintenance.last_prune >= PRUNE_EVERY_S:
                    self.maintenance.last_prune = now
                    await self.prune()
                if now - self.maintenance.last_backup >= BACKUP_EVERY_S and now >= self.maintenance.backup_retry_at:
                    await self._scheduled_backup(now)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("housekeeping failed; will retry")
            await self._sleep_until_needed()

    async def _scheduled_backup(self, now: float) -> None:
        try:
            await self.backup()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.maintenance.backup_retry_at = now + BACKUP_RETRY_S
            log.exception("backup failed; trying again in an hour")

    async def _wake_on_tasks(self) -> None:
        """A task starting or finishing changes what housekeeping must do (power hold, routine results)."""
        async for message in self.bus.subscribe():
            if message.get("type") == "task":
                self._wake.set()

    def routines_changed(self) -> None:
        """A routine was added, changed, removed or run by hand: the scheduler looks again now."""
        self._wake.set()

    async def _sleep_until_needed(self) -> None:
        """Sleep until something could need doing: the next routine, or the next tick while tasks are running (their
        power hold and routine results are kept current). Idle with nothing scheduled, wake rarely."""
        wait = TICK_S
        if self.orchestrator.active_count == 0:
            try:
                due = self.scheduler.next_due()
            except sqlite3.Error:
                log.exception("could not read the next routine time")     # keep the short interval and try again
            else:
                wait = IDLE_SLEEP_S if due is None else min(IDLE_SLEEP_S, max(1.0, due - self.clock()))
        self._wake.clear()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), wait)

    async def _tick_routines(self) -> None:
        try:
            await self.scheduler.tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("routine scheduler failed; will retry")  # must not hold up pruning and backups

    async def prune(self) -> int:
        """Remove finished tasks older than the retention period."""
        days = self.settings.retention_days
        return await self.db.write(lambda con: retention.prune_tasks(con, days, self.clock()))

    async def backup(self) -> Path:
        """Online backup of the database (the newest seven are kept), after an integrity check. A damaged
        database is copied aside under its own name, so it never pushes good backups out.

        It reads through its own read-only connection on a worker thread, so writes carry on meanwhile."""
        def work() -> tuple[Path, bool]:
            con = open_reader(self.db.path)
            try:
                ok = snapshot.integrity_ok(con)
                return snapshot.backup_db(con, self.paths.backups, self.clock(), prefix="lilly" if ok else "damaged"), ok
            finally:
                con.close()

        path, ok = await asyncio.to_thread(work)
        await self.db.write(retention.vacuum)
        self.maintenance.last_backup = self.clock()
        self.maintenance.last_backup_file = path.name
        self.maintenance.integrity_ok = ok
        return path

    def export_all(self) -> dict[str, Any]:
        """Everything the user created, as plain JSON they can keep. Secrets are never part of it."""
        con = self.db.reader
        convs = [{"id": c.id, "title": c.title, "created_at": c.created_at,
                  "messages": [{"role": m.role, "content": m.content, "at": m.created_at}
                               for m in conversations.list_messages(con, c.id, limit=10_000)]}
                 for c in conversations.list_conversations(con, include_archived=True, limit=10_000)]
        return {
            "app": "lilly", "exported_at": self.clock(),
            "conversations": convs,
            "memory": [{"text": m.text, "label": m.label.name, "source": m.source} for m in memory.list_memory(con, 10_000)],
            "agents": [{"name": a.name, "instructions": a.instructions, "mode": a.mode, "skills": a.skills, "pet": a.pet,
                        "look": look_to_dict(a.look), "model": a.model,
                        "allowed": {p: getattr(a, p) for p in agents.PERMISSIONS}} for a in agents.list_agents(con)],
            "routines": [{"name": x.name, "goal": x.goal, "enabled": x.enabled, "schedule": asdict(x.schedule)}
                         for x in routines.list_routines(con)],
            "spaces": [{"name": s.name, "description": s.description,
                        "pages": [{"title": p.title, "content": p.content} for p in spaces.list_pages(con, s.id)]}
                       for s in spaces.list_spaces(con)],
        }

    # ---- shutdown ---------------------------------------------------------------------
    async def close(self) -> None:
        """Stop work first, then the things work depends on."""
        for t in self._background:
            t.cancel()
        for t in self._background:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        await self.orchestrator.aclose()
        await self.mcp.aclose()
        await self.browser.close_all()
        await self.devbox.close_all()
        await self.laya.aclose()
        self.bus.close()
        self.power.release()
        if self._owns_clients:
            await self.client.aclose()
            await self.local_client.aclose()
        self.db.close()

