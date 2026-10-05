"""Starts routines when they are due. It is driven by a regular tick, so it keeps no timers of its own."""
from __future__ import annotations

import functools
import logging
from datetime import tzinfo

from lilly.domain.clock import Clock
from lilly.domain.errors import ConflictError, NotFound, ValidationFailed
from lilly.domain.schedule import next_run
from lilly.domain.tasks import TERMINAL
from lilly.engine.orchestrator import Orchestrator, SubmitRequest
from lilly.store import routines, tasks
from lilly.store.db import Database

log = logging.getLogger("lilly.scheduler")


class Scheduler:
    """A routine that was due while Lilly was off runs once when Lilly starts; a routine never starts while its
    previous run is still going; a routine that cannot start because its agent is gone is paused, not retried."""

    def __init__(self, db: Database, orchestrator: Orchestrator, clock: Clock, tz: tzinfo | None = None) -> None:
        self._db, self._orch, self._clock, self._tz = db, orchestrator, clock, tz

    async def tick(self) -> None:
        await self._settle_finished()
        now = self._clock()
        for routine in routines.due_routines(self._db.reader, now):
            await self._start(routine, now)

    def next_due(self) -> float | None:
        return routines.next_due(self._db.reader)

    async def run_now(self, routine_id: str) -> tasks.TaskRow:
        """Start a routine on request. Its schedule is not changed."""
        routine = routines.get_routine(self._db.reader, routine_id)
        if routine is None:
            raise NotFound(routine_id)
        if self._running(routine):
            raise ConflictError("this routine is already running")
        row = await self._orch.submit(SubmitRequest(goal=routine.goal, agent_id=routine.agent_id))
        now = self._clock()
        await self._db.write(lambda con: routines.record_start(con, routine.id, row.id, now, routine.next_run))
        return row

    def _running(self, routine: routines.RoutineRow) -> bool:
        if routine.last_task_id is None or routine.last_state != "running":
            return False
        last = tasks.get_task(self._db.reader, routine.last_task_id)
        return last is not None and last.state not in TERMINAL

    async def _start(self, routine: routines.RoutineRow, now: float) -> None:
        later = next_run(routine.schedule, now, self._tz)
        if self._running(routine):  # skip this slot instead of piling runs up behind a slow one
            await self._db.write(lambda con: routines.record_skip(con, routine.id, later))
            return
        try:
            row = await self._orch.submit(SubmitRequest(goal=routine.goal, agent_id=routine.agent_id))
        except (NotFound, ValidationFailed) as exc:
            reason = str(exc)
            await self._db.write(lambda con: routines.record_refused(con, routine.id, now, reason))
            log.warning("routine %s paused: %s", routine.name, reason)
        except ConflictError:  # Lilly is busy; try again at the next slot
            await self._db.write(lambda con: routines.record_skip(con, routine.id, later))
        else:
            await self._db.write(lambda con: routines.record_start(con, routine.id, row.id, now, later))

    async def _settle_finished(self) -> None:
        for routine in routines.unsettled_routines(self._db.reader):
            last = tasks.get_task(self._db.reader, routine.last_task_id) if routine.last_task_id else None
            if last is not None and last.state not in TERMINAL:
                continue
            state = last.state.value.lower() if last else "failed"
            error = (last.error if last else "the run was removed") or None
            await self._db.write(functools.partial(routines.record_finish, routine_id=routine.id, state=state,
                                                   error=error))
