"""The approval service: ask the user, wait for the answer, never act without it.

An approval is bound to the hash of exactly what will happen, can be decided once, and expires.
The waiting task holds the only copy of what it will run, so approving cannot change it.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from lilly.domain.clock import Clock
from lilly.domain.errors import ApprovalExpired, NotFound
from lilly.domain.ids import new_id
from lilly.domain.payload import canonical, payload_hash
from lilly.engine.bus import EventBus
from lilly.store import approvals as store
from lilly.store.db import Database

log = logging.getLogger("lilly.approvals")
DEFAULT_TTL_S = 900.0


@dataclass(frozen=True, slots=True)
class Decision:
    approved: bool
    choice: str | None = None   # for model approvals: which of the offered models the user picked


class ApprovalService:
    def __init__(self, db: Database, bus: EventBus, clock: Clock, ttl_s: float = DEFAULT_TTL_S) -> None:
        self._db, self._bus, self._clock, self._ttl = db, bus, clock, ttl_s
        self._waiting: dict[str, asyncio.Future[Decision]] = {}

    def pending(self) -> list[store.ApprovalRow]:
        return [r for r in store.list_approvals(self._db.reader, status="pending") if r.id in self._waiting]

    async def request(self, task_id: str, step_id: str, kind: str, summary: str, payload: dict[str, Any],
                      display: dict[str, Any] | None = None) -> tuple[Decision, str]:
        """Create a pending approval and wait for the user. Returns the decision and the payload hash.

        `payload` is hashed in full; `display` (what the card shows) may be shortened.
        Raises ApprovalExpired if nobody answers in time.
        """
        digest = payload_hash(task_id, step_id, kind, payload)
        approval_id, now = new_id(), self._clock()
        future: asyncio.Future[Decision] = asyncio.get_running_loop().create_future()
        self._waiting[approval_id] = future
        try:
            row = await self._db.write(lambda con: store.create_approval(
                con, id=approval_id, task_id=task_id, step_id=step_id, kind=kind, summary=summary,
                payload_json=canonical(display if display is not None else payload), payload_hash=digest,
                now=now, ttl_s=self._ttl))
        except BaseException:
            self._waiting.pop(approval_id, None)
            raise
        self._bus.publish({"type": "approval", "action": "created", "id": approval_id, "task_id": task_id})
        try:
            return await asyncio.wait_for(future, timeout=row.expires_at - now), digest
        except TimeoutError:
            await self._db.write(lambda con: store.expire(con, approval_id, self._clock()))
            self._bus.publish({"type": "approval", "action": "expired", "id": approval_id, "task_id": task_id})
            raise ApprovalExpired(approval_id) from None
        except asyncio.CancelledError:
            await asyncio.shield(self._db.write(lambda con: store.expire(con, approval_id, self._clock())))
            self._bus.publish({"type": "approval", "action": "expired", "id": approval_id, "task_id": task_id})
            raise
        finally:
            self._waiting.pop(approval_id, None)

    async def decide(self, approval_id: str, *, approve: bool, payload_hash: str,
                     choice: str | None = None) -> store.ApprovalRow:
        """Record the user's answer and wake the waiting task. Single use; the hash must match what was shown.
        Raises ApprovalExpired when the answer comes after the request ran out."""
        future = self._waiting.get(approval_id)
        if future is None:
            raise NotFound(approval_id)  # not waiting: already decided, expired, or from before a restart
        now = self._clock()
        row = await self._db.write(lambda con: store.decide(
            con, approval_id, approve=approve, payload_hash=payload_hash, now=now))
        self._waiting.pop(approval_id, None)  # single use from here on
        if row.status == "expired":           # too late: the expiry is committed, and the waiting task learns of it
            if not future.done():
                future.set_exception(ApprovalExpired(approval_id))
            self._bus.publish({"type": "approval", "action": "expired", "id": approval_id, "task_id": row.task_id})
            raise ApprovalExpired(approval_id)
        if not future.done():
            future.set_result(Decision(approve, choice))
        self._bus.publish({"type": "approval", "action": row.status, "id": approval_id, "task_id": row.task_id})
        return row

    def get(self, approval_id: str) -> store.ApprovalRow | None:
        return store.get_approval(self._db.reader, approval_id)
