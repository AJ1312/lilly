"""The reply check: after a task has finished, ask in the background whether its reply followed the request.

It is advice for the owner and nothing more: the reply is already saved and shown, and the answer never rewrites
it or blocks anything. It only becomes a note on the task (an event the interface can show). It runs beside the
tasks, never inside one, so it can neither hold a task back nor fail one, and it is cancelled when Lilly closes."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from lilly.domain.decisions import REPLY_OPTIONS, Brief, Context, Kind, reply_state
from lilly.engine.decisions import DecisionPipeline

log = logging.getLogger("lilly.replycheck")

EVENT = "reply_check"
MAX_PENDING = 32      # checks waiting at once; when Laya cannot keep up, newer replies are simply not checked

Record = Callable[[str, dict[str, Any]], Awaitable[None]]


class ReplyChecker:
    def __init__(self, pipeline: DecisionPipeline) -> None:
        self._pipeline = pipeline
        self._tasks: set[asyncio.Task[None]] = set()

    def start(self, task_id: str, brief: Brief, reply: str, record: Record) -> None:
        """Check `reply` in the background, if the question is switched on. Returns at once and never raises."""
        if len(self._tasks) >= MAX_PENDING or not self._pipeline.active(Kind.REPLY):
            return
        task = asyncio.get_running_loop().create_task(self._check(task_id, brief, reply, record),
                                                      name=f"lilly-reply-check-{task_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _check(self, task_id: str, brief: Brief, reply: str, record: Record) -> None:
        try:
            outcome = await self._pipeline.decide(Kind.REPLY, task_id, REPLY_OPTIONS, Context(text=reply_state(brief, reply)))
            if outcome.choice is not None:     # no answer, and a watch-only answer, leave nothing on the task
                await record(EVENT, {"choice": outcome.choice, "confidence": outcome.confidence,
                                     "decider": outcome.decider})
        except Exception as exc:
            log.warning("the reply check of task %s failed: %s", task_id, type(exc).__name__)

    async def aclose(self) -> None:
        """Cancel what is still waiting and wait for it to end."""
        pending = tuple(self._tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
