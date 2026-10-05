"""Chat bridges (Telegram first): who may talk to Lilly from a chat app, how fast, and how a person pairs.

Everything that arrives from a chat app is untrusted text from outside. These are the pure rules; the network side
lives in `lilly.bridges`."""
from __future__ import annotations

import hmac
import secrets
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Protocol

from lilly.domain.clock import Clock

BRIDGE_BOUNDS = {"per_minute": (1, 30), "max_chars": (100, 4000)}
_KEYS = frozenset({"enabled", "agent_id", "private_replies", "per_minute", "max_chars"})
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"      # no 0/O or 1/I: easy to read off a screen and type on a phone
CODE_LENGTH = 8


@dataclass(frozen=True, slots=True)
class BridgeSettings:
    enabled: bool = False                 # nothing listens until the owner switches it on
    agent_id: str | None = None           # the one agent chat messages go to (it must be marked reachable from chat)
    private_replies: bool = False         # may answers that used private data be sent through the chat app?
    per_minute: int = 6                   # messages one person may send a minute
    max_chars: int = 2000                 # longest message accepted


def parse_bridge(raw: object) -> tuple[BridgeSettings | None, list[str]]:
    if not isinstance(raw, dict):
        return None, ["bridges must be an object"]
    errs = [f"bridges: unknown setting {k!r}" for k in sorted(raw.keys() - _KEYS)]
    d = BridgeSettings()
    for key in ("enabled", "private_replies"):
        if not isinstance(raw.get(key, getattr(d, key)), bool):
            errs.append(f"bridges.{key} must be true or false")
    agent = raw.get("agent_id", d.agent_id)
    if agent is not None and (not isinstance(agent, str) or not 1 <= len(agent) <= 64):
        errs.append("bridges.agent_id must be text or empty")
    numbers = {}
    for key, (lo, hi) in BRIDGE_BOUNDS.items():
        v = raw.get(key, getattr(d, key))
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            errs.append(f"bridges.{key} must be a whole number from {lo} to {hi}")
        else:
            numbers[key] = v
    if errs:
        return None, errs
    return BridgeSettings(bool(raw.get("enabled", d.enabled)), agent, bool(raw.get("private_replies", d.private_replies)),
                          **numbers), []


def bridge_to_dict(b: BridgeSettings) -> dict[str, object]:
    return {"enabled": b.enabled, "agent_id": b.agent_id, "private_replies": b.private_replies,
            "per_minute": b.per_minute, "max_chars": b.max_chars}


class Pairing:
    """A one-time code the owner types into the chat app to link their account. One code at a time; it expires and works
    once. Wrong guesses are counted per sender, so a stranger locks only themselves out; a far larger total across
    everyone burns the code as a backstop."""

    def __init__(self, clock: Clock, ttl_s: float = 600.0, max_wrong: int = 5, max_wrong_total: int = 200,
                 max_senders: int = 256) -> None:
        self._clock, self._ttl, self._max_wrong = clock, ttl_s, max_wrong
        self._max_total, self._max_senders = max_wrong_total, max_senders
        self._code: str | None = None
        self._until = 0.0
        self._wrong: OrderedDict[int, int] = OrderedDict()     # sender -> wrong guesses against this code
        self._total = 0

    def new(self) -> str:
        self._code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        self._until, self._total = self._clock() + self._ttl, 0
        self._wrong.clear()
        return self._code

    def active(self) -> float | None:
        """When the current code stops working, or None when there is no usable code."""
        return self._until if self._code is not None and self._clock() < self._until else None

    def redeem(self, attempt: str, sender: int) -> bool:
        if self.active() is None or self._code is None or self._wrong.get(sender, 0) >= self._max_wrong:
            return False
        if hmac.compare_digest(attempt.strip().upper().encode(), self._code.encode()):
            self._code = None
            return True
        self._wrong[sender] = self._wrong.get(sender, 0) + 1
        self._wrong.move_to_end(sender)
        while len(self._wrong) > self._max_senders:
            self._wrong.popitem(last=False)
        self._total += 1
        if self._total >= self._max_total:
            self._code = None
        return False


class RateLimiter:
    """At most `per_minute` messages from each sender in any sliding minute, remembering a bounded number of senders."""

    def __init__(self, clock: Clock, per_minute: int, max_senders: int = 256) -> None:
        self._clock, self.per_minute, self._max = clock, per_minute, max_senders
        self._seen: OrderedDict[int, deque[float]] = OrderedDict()

    def allow(self, sender: int) -> bool:
        now = self._clock()
        window = self._seen.setdefault(sender, deque())
        self._seen.move_to_end(sender)
        while len(self._seen) > self._max:
            self._seen.popitem(last=False)
        while window and now - window[0] >= 60.0:
            window.popleft()
        if len(window) >= self.per_minute:
            return False
        window.append(now)
        return True


def clean_inbound(text: str, max_chars: int) -> str:
    """Collapse whitespace, drop control characters and cut to the limit. Empty means there was nothing to act on."""
    printable = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t ")
    return " ".join(printable.split())[:max_chars]


class BridgeControl(Protocol):
    """What the interface may ask of a running bridge. Implemented in `lilly.bridges`, handed to the web app by the
    daemon, so the two never import each other."""

    def status(self) -> dict[str, object]: ...
    async def new_pairing(self) -> dict[str, object]: ...
    async def set_token(self, token: str) -> str: ...
    async def clear_token(self) -> None: ...
    async def unpair(self, user_id: int) -> bool: ...


