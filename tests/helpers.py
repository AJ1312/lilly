"""Shared test helpers."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from lilly.domain.caps import Cap
from lilly.domain.errors import ProviderError
from lilly.domain.labels import Label, Mode
from lilly.domain.ports import Completed, CompletionRequest, CompletionResult
from lilly.providers.keys import KeyStore, Secret


class Clock:
    """A settable wall clock."""

    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


Reply = str | Exception | Callable[[CompletionRequest], str]


@dataclass
class ScriptedCompleter:
    """A Completer that answers from a script and records every request it was given."""

    replies: list[Reply] = field(default_factory=list)
    calls: list[CompletionRequest] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)
    pins: list[str | None] = field(default_factory=list)
    model: str = "fake-model"
    needs_grant: bool = False

    async def complete(self, req: CompletionRequest, *, need: Cap = Cap.NONE, label: Label = Label.PUBLIC,
                       task_id: str | None = None, payload_hash: str | None = None, mode: Mode = Mode.ASK,
                       pin: str | None = None, role: str = "act", tag: str | None = None,
                       priority: int = 0) -> Completed:
        self.calls.append(req)
        self.labels.append(label)
        self.pins.append(pin)
        if not self.replies:
            raise ProviderError(retryable=False)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        text = reply(req) if callable(reply) else reply
        if req.on_text is not None:          # like a model that writes a little at a time
            req.on_text(text[: len(text) // 2])
            req.on_text(text)
        return Completed(CompletionResult(text, 10, 10, "stop"), self.model)


def plan(*steps: dict[str, object], reasoning: str = "test", answer: str | None = None) -> str:
    import json

    return json.dumps({"reasoning": reasoning, "answer": answer, "steps": list(steps)})


def step(sid: str, tool: str, **args: object) -> dict[str, object]:
    return {"id": sid, "tool": tool, "expect": "something useful", "args": args}


class MemoryKeyStore(KeyStore):
    """Keys held in memory only: for tests."""

    kind = "memory"
    secure = True

    def __init__(self, initial: Mapping[str, str] | None = None) -> None:
        self._keys = {k: Secret(v) for k, v in (initial or {}).items()}

    def get(self, ref: str) -> Secret | None:
        return self._keys.get(ref)

    def put(self, ref: str, value: Secret) -> None:
        self._keys[ref] = value

    def delete(self, ref: str) -> None:
        self._keys.pop(ref, None)


class ControllableRand:
    """Deterministic random float generator for tests."""

    def __init__(self, values: list[float] | None = None, default: float = 0.5) -> None:
        self.values = list(values or [])
        self.default = default
        self.history: list[float] = []

    def __call__(self) -> float:
        val = self.values.pop(0) if self.values else self.default
        self.history.append(val)
        return val


class FakeSleep:
    """An asyncio.sleep stand-in tied to a fake Clock."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.sleeps: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.clock.advance(seconds)
        import asyncio

        await asyncio.sleep(0)
