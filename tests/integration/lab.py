"""A lab for engine tests: real database, runner and approvals, a scripted model, and fake tools that take time."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

from lilly.decide.rules import InstructionRules, LoopRule, MatchRule, SearchRanker
from lilly.domain.decisions import Decider, DecisionSettings
from lilly.domain.errors import ToolError
from lilly.domain.grants import GrantStore
from lilly.domain.labels import Label, Mode, Risk
from lilly.domain.policy import PathScope
from lilly.domain.ports import ToolContext, ToolResult
from lilly.domain.settings import MODULES, LimitSettings, Settings
from lilly.domain.tools_registry import ToolSpec
from lilly.engine.approvals import ApprovalService
from lilly.engine.bus import EventBus
from lilly.engine.decisions import DatabaseSink, DecisionPipeline
from lilly.engine.orchestrator import Orchestrator, SubmitRequest
from lilly.engine.runner import EngineDeps
from lilly.store.db import Database
from lilly.tools import Tool, build_tools
from tests.conftest import Engine
from tests.helpers import Clock, MemoryKeyStore, ScriptedCompleter, plan


@dataclass
class Trace:
    """When each fake tool call started and ended, and how many are running right now."""

    log: list[tuple[str, str]] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    running: int = 0
    peak: int = 0

    def index(self, kind: str, step_id: str) -> int:
        return self.log.index((kind, step_id))


class Probe(Tool):
    """A tool that records itself, sleeps, and then returns or fails."""

    def __init__(self, name: str, spec: ToolSpec, trace: Trace, delay: float = 0.0, fail: str | None = None) -> None:
        self.name, self._spec, self._trace, self._delay, self._fail = name, spec, trace, delay, fail

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        t = self._trace
        t.log.append(("start", ctx.step_id))
        t.running += 1
        t.peak = max(t.peak, t.running)
        try:
            await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            t.cancelled.append(ctx.step_id)
            raise
        finally:
            t.running -= 1
        if self._fail:
            raise ToolError(self._fail)
        t.log.append(("end", ctx.step_id))
        return ToolResult(f"result of {self.name}", self._spec.reads_label, self._spec.untrusted)


READ = ToolSpec(Risk.R0, path_args=())
PRIVATE = ToolSpec(Risk.R0, reads_label=Label.PERSONAL, path_args=())
SEND = ToolSpec(Risk.R0, egress=True, path_args=())
WRITE = ToolSpec(Risk.R1, path_args=())
PRESS = ToolSpec(Risk.R2, confirm=True, path_args=())


@dataclass
class Lab:
    engine: Engine
    trace: Trace
    limits: list[LimitSettings]
    decisions: list[DecisionSettings]
    deciders: dict[str, Decider]     # extra deciders a test installs, such as a stand-in for Laya

    def add(self, name: str, spec: ToolSpec = READ, delay: float = 0.0, fail: str | None = None) -> None:
        self.engine.tools[name] = Probe(name, spec, self.trace, delay, fail)

    async def submit(self, *steps: dict[str, object], mode: Mode = Mode.OPEN, conversation_id: str | None = None,
                     goal: str = "go"):  # type: ignore[no-untyped-def]
        self.engine.completer.replies = [plan(*steps), *self.engine.completer.replies]
        agent = await self.engine.agent(mode, files_allowed=True)
        return await self.engine.orchestrator.submit(SubmitRequest(goal, agent_id=agent, conversation_id=conversation_id))


@pytest.fixture
async def lab(tmp_path: Path) -> AsyncIterator[Lab]:
    """The engine fixture, except that the limits can be changed by the test."""
    root, home = tmp_path / "shared", tmp_path / "home"
    root.mkdir()
    home.mkdir()
    clock, db, bus, grants, completer = Clock(), Database(tmp_path / "lilly.db"), EventBus(), GrantStore(), ScriptedCompleter()
    settings = Settings(file_roots=(str(root),), modules=MODULES)
    scope = PathScope(settings.file_roots, deny=(str(home),))
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    tools = build_tools(settings, scope=scope, db=db, router=completer, keys=MemoryKeyStore(), client=client, clock=clock)
    approvals = ApprovalService(db, bus, clock, ttl_s=30.0)
    limits = [LimitSettings()]
    lab_settings = [DecisionSettings()]
    extra: dict[str, Decider] = {}
    pipeline = DecisionPipeline(lambda: lab_settings[0], lambda: {"search": SearchRanker(), "loop": LoopRule(),
                                                                  "rules": InstructionRules(), "match": MatchRule(),
                                                                  **extra}, DatabaseSink(db), clock)
    deps = EngineDeps(db, completer, lambda: tools, lambda: scope, lambda: settings.file_roots, bus, approvals, grants,
                      clock, lambda: limits[0], pipeline)
    orchestrator = Orchestrator(deps)
    orchestrator.configure(settings)
    await orchestrator.start()
    yield Lab(Engine(db, bus, approvals, grants, orchestrator, completer, tools, root, clock), Trace(), limits, lab_settings, extra)
    await orchestrator.aclose()
    await client.aclose()
    db.close()


