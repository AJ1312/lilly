"""Permission grants and the label-access rule for models. Grants live in memory only."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from lilly.domain.clock import Clock
from lilly.domain.labels import Label, Mode


@dataclass(frozen=True, slots=True)
class Grant:
    """The user's permission for one model to see data up to `label`.
    Held in memory only, so a restart revokes everything."""
    model: str
    label: Label
    expires: float                      # on the GrantStore clock
    task_id: str | None = None          # None = any task
    payload_hash: str | None = None     # set = valid only for this exact payload
    once: bool = False


class GrantStore:
    def __init__(self, clock: Clock = time.monotonic, max_grants: int = 256):
        self._clock, self._max = clock, max_grants
        self._grants: list[Grant] = []

    def __len__(self) -> int:
        self._purge()
        return len(self._grants)

    def _purge(self) -> None:
        now = self._clock()
        self._grants = [g for g in self._grants if g.expires > now]

    def add(self, g: Grant) -> None:
        self._purge()
        self._grants.append(g)
        del self._grants[:-self._max]   # bounded: oldest grants drop first

    def grant(self, model: str, label: Label, ttl_s: float, *, task_id: str | None = None,
              payload_hash: str | None = None, once: bool = False) -> Grant:
        g = Grant(model, label, self._clock() + ttl_s, task_id, payload_hash, once)
        self.add(g)
        return g

    def find(self, model: str, label: Label, task_id: str | None = None,
             payload_hash: str | None = None) -> Grant | None:
        self._purge()
        for g in self._grants:
            if (g.model == model and g.label >= label
                    and (g.task_id is None or g.task_id == task_id)
                    and (g.payload_hash is None or g.payload_hash == payload_hash)):
                return g
        return None

    def revoke_all(self) -> int:
        """Withdraw every permission at once. Returns how many were active."""
        count = len(self)
        self._grants.clear()
        return count

    def consume(self, g: Grant) -> None:
        if g.once and g in self._grants:
            self._grants.remove(g)


class ModelAccess(Protocol):
    """What label_access needs to know about a model. core.pool.ModelEntry satisfies it."""

    @property
    def name(self) -> str: ...
    @property
    def max_label(self) -> Label: ...
    @property
    def local(self) -> bool: ...
    @property
    def ask_private(self) -> bool: ...
    @property
    def trains(self) -> bool: ...


def label_access(e: ModelAccess, label: Label, grants: GrantStore | None,
                 task_id: str | None, payload_hash: str | None,
                 mode: Mode = Mode.ASK) -> tuple[bool, Grant | None]:
    """May this model see data at `label`? Standing ceiling first, then the agent's mode:
    LOCKED never goes beyond the ceiling, OPEN skips the permission step, ASK needs a
    grant. Remote models never receive SECRET, and "never" models never get more.
    An endpoint that may train on or expose inputs (`trains`) needs a grant even in OPEN:
    that disclosure cannot be taken back."""
    if e.max_label >= label:
        return True, None
    if mode is Mode.LOCKED or not e.ask_private or (label is Label.SECRET and not e.local):
        return False, None
    if mode is Mode.OPEN and not e.trains:
        return True, None
    if grants is None:
        return False, None
    g = grants.find(e.name, label, task_id, payload_hash)
    return (g is not None), g
