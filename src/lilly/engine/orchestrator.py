"""The orchestrator: accepts tasks, queues them, runs a few at a time, and can stop them all at once."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from lilly.domain.errors import ConflictError, LillyError, NotFound, ValidationFailed
from lilly.domain.ids import new_id
from lilly.domain.labels import Label, Mode
from lilly.domain.pets import agent_prompt
from lilly.domain.settings import EngineSettings, Settings
from lilly.domain.skills import BUILTIN_SKILLS
from lilly.domain.tasks import TERMINAL, TaskState
from lilly.engine.replycheck import ReplyChecker
from lilly.engine.runner import EngineDeps, RunSpec, TaskRunner
from lilly.store import agents as agent_store
from lilly.store import approvals as approval_store
from lilly.store import conversations, tasks
from lilly.store.events import append_event
from lilly.tools.base import Tool

log = logging.getLogger("lilly.orchestrator")
MAX_ACTIVE = 50
MAX_GOAL = 4000
KILL_SWITCH_WAIT_S = 1.0
AGENT_CHANGED = "stopped because the agent's permissions were changed"
AGENT_DELETED = "stopped because the agent was deleted"


@dataclass(frozen=True, slots=True)
class SubmitRequest:
    goal: str
    conversation_id: str | None = None
    agent_id: str | None = None
    skill: str | None = None
    params: Mapping[str, str] = field(default_factory=dict)
    pin_model: str | None = None
    source: str = "app"          # where the request came from: "app", or a chat app such as "telegram"
    outside: bool = False        # the text came from outside Lilly's own interface: the task starts out untrusted


class Gate:
    """Lets at most `limit` tasks run at once, and the limit can change while tasks wait or run."""

    def __init__(self, limit: int) -> None:
        self._limit, self.running = limit, 0
        self._cond = asyncio.Condition()
        self._waking: set[asyncio.Task[None]] = set()

    def resize(self, limit: int) -> None:
        self._limit = limit
        task = asyncio.get_running_loop().create_task(self._wake())  # a larger limit lets queued tasks start now
        self._waking.add(task)
        task.add_done_callback(self._waking.discard)

    async def _wake(self) -> None:
        async with self._cond:
            self._cond.notify_all()

    async def __aenter__(self) -> None:
        async with self._cond:
            await self._cond.wait_for(lambda: self.running < self._limit)
            self.running += 1

    async def __aexit__(self, *exc: object) -> None:
        async with self._cond:
            self.running -= 1
            self._cond.notify_all()


class Orchestrator:
    def __init__(self, deps: EngineDeps) -> None:
        self._d = deps
        self._settings: Settings | None = None
        self._gate = Gate(deps.limits().max_running)
        self._active: dict[str, tuple[asyncio.Task[None], TaskRunner]] = {}
        self._submitting = 0                              # submits that hold a slot but are not in _active yet
        self._finishing: set[asyncio.Task[None]] = set()  # cleanups of cancelled tasks
        self._closed = False
        self._replies = ReplyChecker(deps.decisions) if deps.decisions is not None else None

    def configure(self, settings: Settings) -> None:
        self._settings = settings
        self._gate.resize(settings.limits.max_running)

    @property
    def running_count(self) -> int:
        return self._gate.running

    @property
    def queued_count(self) -> int:
        return len(self._active) - self._gate.running

    @property
    def active_count(self) -> int:
        return len(self._active)

    # ---- lifecycle ---------------------------------------------------------------------------
    async def start(self) -> None:
        """After a restart nothing is running: fail what was in flight (with a reason) and void old approvals."""
        now = self._d.clock()

        def recover(con: sqlite3.Connection) -> list[str]:
            ids = tasks.interrupt_unfinished(con, now)
            approval_store.expire_all_pending(con, now)
            return ids

        interrupted = await self._d.db.write(recover)
        if interrupted:
            log.warning("marked %d unfinished task(s) as interrupted after restart", len(interrupted))

    async def aclose(self) -> None:
        self._closed = True
        await self.stop_all(wait_s=5.0)
        if self._replies is not None:
            await self._replies.aclose()

    # ---- submitting ------------------------------------------------------------------------------
    def _effective_mode(self, agent_mode: int | None) -> Mode:
        if agent_mode is not None:
            return Mode(agent_mode)
        return self._settings.default_mode if self._settings else Mode.ASK

    async def submit(self, req: SubmitRequest) -> tasks.TaskRow:
        """Create the task and its first message, then run it in the background. Returns at once."""
        goal = " ".join(req.goal.split()) if req.skill else req.goal.strip()
        if not goal or len(goal) > MAX_GOAL:
            raise ValidationFailed(f"say what you want in 1 to {MAX_GOAL} characters")
        if self._closed:
            raise ConflictError("Lilly is shutting down")
        if len(self._active) + self._submitting >= MAX_ACTIVE:
            raise ConflictError("too many tasks are queued; wait for some to finish or stop them")
        if req.skill and req.skill not in BUILTIN_SKILLS:
            raise NotFound(f"skill {req.skill}")
        db = self._d.db
        agent = agent_store.get_agent(db.reader, req.agent_id) if req.agent_id else None
        if req.agent_id and agent is None:
            raise NotFound(f"agent {req.agent_id}")
        if req.conversation_id and conversations.get_conversation(db.reader, req.conversation_id) is None:
            raise NotFound(f"conversation {req.conversation_id}")

        mode = self._effective_mode(agent.mode if agent else None)
        pin = req.pin_model or (agent.model if agent else "") or None   # a request's pin beats the pet's own model
        task_id, conv_id, now = new_id(), req.conversation_id or new_id(), self._d.clock()
        title = goal[:60]

        def create(con: sqlite3.Connection) -> tasks.TaskRow:
            if not req.conversation_id:
                conversations.create_conversation(con, conv_id, title, now,
                                                  agent.space_id if agent else None)
            row = tasks.create_task(
                con, id=task_id, goal=goal, mode=int(mode),
                label=Label.PUBLIC, tainted=req.outside, now=now, conversation_id=conv_id,
                agent_id=agent.id if agent else None, skill=req.skill, pinned_model=pin)
            conversations.add_message(con, conv_id, "user", goal, now, task_id=task_id)
            append_event(con, task_id, "created", {"mode": mode.name, "skill": req.skill,
                                                   "agent": agent.name if agent else None, "source": req.source}, "user", now)
            return row

        self._submitting += 1      # the slot is held from here, before the first await
        try:
            row = await db.write(create)
            if self._closed:       # shutdown began while the task was being written: nobody would stop it
                await self._cancel_queued(task_id)
                raise ConflictError("Lilly is shutting down")
            spec = RunSpec(goal, conv_id, agent_prompt(agent.instructions, agent.skills) if agent else "",
                           req.skill, req.params, pin)
            runner = TaskRunner(self._scoped_deps(agent), row, spec, self._replies)
            handle = asyncio.create_task(self._run(runner), name=f"lilly-task-{task_id}")
            self._active[task_id] = (handle, runner)
            handle.add_done_callback(lambda h: self._ended(task_id, h))
            if agent is not None and self._narrowed_since(agent):   # changed after it was read, before it was registered
                runner.request_cancel(AGENT_CHANGED)
                handle.cancel()
        finally:
            self._submitting -= 1
        self._d.bus.publish({"type": "task", "task_id": task_id, "state": row.state.value})
        return row

    def _narrowed_since(self, agent: agent_store.AgentRow) -> bool:
        now = agent_store.get_agent(self._d.db.reader, agent.id)
        return now is None or agent_store.narrows(agent, now)

    def _scoped_deps(self, agent: agent_store.AgentRow | None) -> EngineDeps:
        """The tools this task may use: the enabled ones, narrowed by the agent's permissions."""
        base = self._d.tools

        def allowed() -> Mapping[str, Tool]:
            out = {}
            for name, tool in base().items():
                if agent is not None:
                    if name.startswith(("web.", "browser.")) and not agent.research_allowed:
                        continue
                    if name.startswith(("memory.", "notes.")) and not agent.memory_allowed:
                        continue
                    if name.startswith(("fs.", "data.", "devbox.")) and not agent.files_allowed:
                        continue
                    if name.startswith("computer.") and not agent.computer_allowed:
                        continue
                out[name] = tool
            return out

        engine_fn = self._d.engine_settings
        if self._settings is not None and engine_fn is EngineSettings:
            settings_ref = self._settings

            def engine_fn() -> EngineSettings:
                return settings_ref.engine
        return replace(self._d, tools=allowed, engine_settings=engine_fn)

    async def _run(self, runner: TaskRunner) -> None:
        async with self._gate:
            await runner.run()

    def _ended(self, task_id: str, handle: asyncio.Task[None]) -> None:
        """A task is over. One cancelled before it ran never recorded its end, so that is done here."""
        if not handle.cancelled():
            self._active.pop(task_id, None)
            return
        cleanup = asyncio.get_running_loop().create_task(self._cancelled(task_id))
        self._finishing.add(cleanup)
        cleanup.add_done_callback(self._finishing.discard)

    async def _cancelled(self, task_id: str) -> None:
        try:
            await self._cancel_queued(task_id, self._active[task_id][1].stop_reason)
        except LillyError:
            log.exception("could not record the cancellation of task %s", task_id)
        finally:
            self._active.pop(task_id, None)

    async def _cancel_queued(self, task_id: str, reason: str = "stopped") -> None:
        now = self._d.clock()

        def job(con: sqlite3.Connection) -> bool:
            row = tasks.get_task(con, task_id)
            if row is None or row.state in TERMINAL:
                return False
            tasks.set_state(con, task_id, TaskState.CANCELLED, now, error=reason)
            append_event(con, task_id, "state", {"state": "CANCELLED", "error": reason}, "system", now)
            return True

        if await self._d.db.write(job):
            self._d.bus.publish({"type": "task", "task_id": task_id, "state": "CANCELLED"})

    # ---- stopping ----------------------------------------------------------------------------------
    async def cancel(self, task_id: str) -> None:
        entry = self._active.get(task_id)
        if entry is None:
            raise NotFound(task_id)
        handle, runner = entry
        runner.request_cancel()
        handle.cancel()

    async def stop_all(self, wait_s: float = KILL_SWITCH_WAIT_S) -> int:
        """The kill switch: cancel every task, running or queued, and wait briefly for them to end.

        Not permanent: new tasks can be submitted straight afterwards. Returns how many were stopped."""
        return await self._stop(list(self._active.values()), "stopped", wait_s)

    async def cancel_agent_tasks(self, agent_id: str, reason: str, wait_s: float = KILL_SWITCH_WAIT_S) -> int:
        """Cancel every unfinished task of one agent, a step already running included, and say why in the task.
        Other agents' tasks are untouched. Returns how many were stopped."""
        return await self._stop([e for e in self._active.values() if e[1].agent_id == agent_id], reason, wait_s)

    async def _stop(self, entries: list[tuple[asyncio.Task[None], TaskRunner]], reason: str, wait_s: float) -> int:
        for handle, runner in entries:
            runner.request_cancel(reason)
            handle.cancel()
        if entries:
            await asyncio.wait([h for h, _ in entries], timeout=wait_s)
        if self._finishing:
            await asyncio.wait(set(self._finishing), timeout=wait_s)
        return len(entries)
