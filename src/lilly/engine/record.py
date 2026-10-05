"""TaskRecord: what one running task writes down, and the context that travels with its data.

The runner and the step executor both hold the same record. It owns the task's label and taint, so a step
that finishes updates the one shared context, and every write goes through here in a single place."""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lilly.domain.clock import Clock
from lilly.domain.labels import Label, TaskCtx
from lilly.domain.reasoning import Layer, redact
from lilly.domain.tasks import TaskState
from lilly.engine.bus import EventBus
from lilly.store import tasks
from lilly.store.db import Database
from lilly.store.events import append_event


@dataclass(slots=True)
class TaskRecord:
    db: Database
    bus: EventBus
    clock: Clock
    task_id: str
    ctx: TaskCtx
    state_now: TaskState
    models: list[str] = field(default_factory=list)   # every model that took part, in order
    cancelled: bool = False                           # worker threads poll this; asyncio cannot interrupt them
    started: float = field(default_factory=time.monotonic)

    async def event(self, kind: str, payload: dict[str, Any], prov: str = "system") -> None:
        task_id, now = self.task_id, self.clock()
        row = await self.db.write(lambda con: append_event(con, task_id, kind, payload, prov, now))
        self.bus.publish({"type": "event", "task_id": task_id, "seq": row.seq, "kind": kind,
                          "payload": payload, "prov": prov, "ts": now})

    async def thought(self, layer: Layer, text: str, source: str = "system", step: str | None = None) -> None:
        await self.event("thought", {"layer": layer.name, "text": redact(text)[:1500], "step": step},
                         "model" if source == "model" else "system")

    async def state(self, state: TaskState, *, answer: str | None = None, error: str | None = None,
                    also: Callable[[sqlite3.Connection], None] | None = None) -> None:
        """Move the task to `state`. `also` writes in the same transaction: both happen or neither does."""
        if state is self.state_now:
            return
        task_id, now = self.task_id, self.clock()

        def job(con: sqlite3.Connection) -> None:
            tasks.set_state(con, task_id, state, now, answer=answer, error=error)
            append_event(con, task_id, "state", {"state": state.value, **({"error": error} if error else {})},
                         "system", now)
            if also is not None:
                also(con)

        await self.db.write(job)
        self.state_now = state
        self.bus.publish({"type": "task", "task_id": task_id, "state": state.value})

    def absorb(self, label: Label, untrusted: bool) -> None:
        """Join new data into the task's context. No await: with steps side by side, no update is ever lost."""
        self.ctx = self.ctx.absorb(label, untrusted)

    async def remember_ctx(self) -> None:
        task_id, label, tainted, now = self.task_id, self.ctx.label, self.ctx.tainted, self.clock()
        await self.db.write(lambda con: tasks.update_context(con, task_id, label=label, tainted=tainted, now=now))

    async def step_status(self, step_id: str, status: str, **kw: Any) -> None:
        task_id, now = self.task_id, self.clock()
        await self.db.write(lambda con: tasks.update_step(con, task_id, step_id, status, now, **kw))
