"""Contracts shared across layers: model providers, the key store and what a tool receives and returns."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from lilly.domain.caps import Cap
from lilly.domain.labels import Label, Mode


# ---- providers --------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ToolSchema:
    name: str
    description: str
    parameters: Mapping[str, Any]  # JSON Schema


@dataclass(frozen=True, slots=True)
class ModelToolCall:
    id: str
    name: str
    arguments: Mapping[str, Any] | None
    raw: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: tuple[ModelToolCall, ...] = ()
    tool_call_id: str | None = None
    provider_state: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    messages: tuple[Message, ...]
    max_tokens: int
    json_mode: bool = False
    temperature: float = 0.2
    deadline_s: float = 60.0
    quick: bool = False             # a small, simple job: models the owner marked "quick" are tried first
    on_text: Callable[[str], None] | None = field(default=None, compare=False)  # told the whole text so far
    tools: tuple[ToolSchema, ...] = ()
    tool_choice: str = "auto"       # "auto" | "none"
    role: str = "act"
    tag: str | None = None
    priority: int = 0               # 0 interactive, 1 background


@dataclass(frozen=True, slots=True)
class CompletionResult:
    text: str
    input_tokens: int
    output_tokens: int
    finish_reason: str
    tool_calls: tuple[ModelToolCall, ...] = ()
    provider_state: Mapping[str, Any] | None = None


class Provider(ABC):
    name: str

    @abstractmethod
    async def complete(self, req: CompletionRequest) -> CompletionResult:
        """Raises QuotaExhausted or ProviderError. Never logs keys or prompts."""


@dataclass(frozen=True, slots=True)
class Completed:
    result: CompletionResult
    model: str   # the model that actually answered


class Completer(Protocol):
    """Anything that can run a completion through Lilly's unified model broker."""

    async def complete(self, req: CompletionRequest, *, need: Cap = Cap.NONE, label: Label = Label.PUBLIC,
                       task_id: str | None = None, payload_hash: str | None = None, mode: Mode = Mode.ASK,
                       pin: str | None = None, role: str = "act", tag: str | None = None,
                       priority: int = 0) -> Completed: ...


class Secret:
    """A value that never prints itself."""

    def __init__(self, value: str) -> None:
        self._v = value

    def reveal(self) -> str:
        return self._v

    def __repr__(self) -> str:
        return "Secret(***)"

    __str__ = __repr__


class KeyStore(Protocol):
    def get(self, ref: str) -> Secret | None: ...
    def put(self, ref: str, value: Secret) -> None: ...
    def delete(self, ref: str) -> None: ...


# ---- tools ------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ToolContext:
    """What a running step knows about the task it belongs to."""

    task_id: str
    step_id: str
    deadline_s: float
    cancelled: Callable[[], bool]
    label: Label = Label.PUBLIC       # highest label of anything the task has seen so far
    tainted: bool = False             # the task has read untrusted content
    mode: Mode = Mode.ASK
    pin_model: str | None = None
    payload_hash: str | None = None   # hash of this exact step; a model permission is bound to it
    on_text: Callable[[str], None] | None = None   # a step that writes text may report it as it goes
    ask: Callable[[str, list[str] | None], Awaitable[str]] | None = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    output: str
    label: Label        # sensitivity of the result
    untrusted: bool     # the content came from outside (web page, email, file written by someone else)
    model: str | None = None  # the model that produced it, when one did
