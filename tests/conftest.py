"""Fixtures: a complete engine wired against a temporary database and a scripted model."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from lilly.domain.grants import GrantStore
from lilly.domain.ids import new_id
from lilly.domain.labels import Mode
from lilly.domain.policy import PathScope
from lilly.domain.settings import MODULES, EngineSettings, Settings
from lilly.engine.approvals import ApprovalService
from lilly.engine.bus import EventBus
from lilly.engine.orchestrator import Orchestrator, SubmitRequest
from lilly.engine.runner import EngineDeps
from lilly.store import agents as agent_store
from lilly.store import tasks
from lilly.store.db import Database
from lilly.tools import Tool, build_tools
from tests.helpers import Clock, MemoryKeyStore, ScriptedCompleter


@dataclass
class Engine:
    db: Database
    bus: EventBus
    approvals: ApprovalService
    grants: GrantStore
    orchestrator: Orchestrator
    completer: ScriptedCompleter
    tools: dict[str, Tool]
    root: Path
    clock: Clock

    async def run(self, goal: str, **kw: object) -> tasks.TaskRow:
        """Submit and wait for the task to reach a terminal state."""
        row = await self.orchestrator.submit(SubmitRequest(goal, **kw))  # type: ignore[arg-type]
        return await self.wait(row.id)

    async def agent(self, mode: Mode = Mode.OPEN, **kw: Any) -> str:
        """Create an agent and return its id."""
        agent_id = new_id()
        await self.db.write(lambda con: agent_store.create_agent(con, agent_id, "Tester", "", int(mode), self.clock(), **kw))
        return agent_id

    async def wait(self, task_id: str, timeout: float = 10.0) -> tasks.TaskRow:
        async with asyncio.timeout(timeout):
            while task_id in self.orchestrator._active:
                await asyncio.sleep(0.01)
        row = tasks.get_task(self.db.reader, task_id)
        assert row is not None
        return row

    async def wait_for_approval(self, timeout: float = 5.0):  # type: ignore[no-untyped-def]
        async with asyncio.timeout(timeout):
            while not (pending := self.approvals.pending()):
                await asyncio.sleep(0.01)
        return pending[0]


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[Engine]:
    root = tmp_path / "shared"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    clock = Clock()
    db = Database(tmp_path / "lilly.db")
    bus = EventBus()
    grants = GrantStore()
    completer = ScriptedCompleter()
    settings = Settings(file_roots=(str(root),), modules=MODULES, engine=EngineSettings(mode="plan"))
    scope = PathScope(settings.file_roots, deny=(str(home),))
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    tools = build_tools(settings, scope=scope, db=db, router=completer, keys=MemoryKeyStore(), client=client,
                        clock=clock)
    approvals = ApprovalService(db, bus, clock, ttl_s=30.0)
    deps = EngineDeps(db, completer, lambda: tools, lambda: scope, lambda: settings.file_roots, bus, approvals,
                      grants, clock, engine_settings=lambda: settings.engine)
    orchestrator = Orchestrator(deps)
    orchestrator.configure(settings)
    await orchestrator.start()
    yield Engine(db, bus, approvals, grants, orchestrator, completer, tools, root, clock)
    await orchestrator.aclose()
    await client.aclose()
    db.close()
pytest_plugins = ["tests.integration.lab"]
