"""Context management: observation truncation, deterministic compaction, summarization, and prefix stability."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable

from lilly.domain.caps import Cap
from lilly.domain.labels import Label, Mode
from lilly.domain.ports import (
    Completer,
    CompletionRequest,
    Message,
)
from lilly.domain.settings import EngineSettings

UNTRUSTED_OPEN = "<untrusted_data>"
UNTRUSTED_CLOSE = "</untrusted_data>"


def estimate_tokens(text: str) -> int:
    """Fast, deterministic estimate of token count (approx. 4 characters per token)."""
    return max(1, (len(text) + 3) // 4)


def message_tokens(msg: Message) -> int:
    overhead = 4
    if msg.tool_calls:
        overhead += sum(estimate_tokens(tc.name) + estimate_tokens(str(tc.arguments)) for tc in msg.tool_calls)
    return estimate_tokens(msg.content) + overhead


def total_tokens(messages: list[Message]) -> int:
    return sum(message_tokens(m) for m in messages)


def truncate_observation(content: str, max_chars: int) -> str:
    """Truncate tool result body to max_chars, preserving result.read pagination instruction."""
    if len(content) <= max_chars:
        return content

    # Check if already has OBS_OK prefix: "RESULT {step_id} {tool} ok ..."
    first_line, _, rest = content.partition("\n")
    m = re.match(r"^RESULT\s+(\S+)\s+(\S+)\s+ok(?:\s+\((\d+)\s+characters.*?\))?", first_line)
    if m:
        step_id, tool = m.group(1), m.group(2)
        total_chars = int(m.group(3)) if m.group(3) else len(rest)
        body = rest
        is_untrusted = False
        if body.startswith(UNTRUSTED_OPEN) and body.endswith(UNTRUSTED_CLOSE):
            is_untrusted = True
            body = body[len(UNTRUSTED_OPEN):-len(UNTRUSTED_CLOSE)].strip("\r\n")

        if len(body) > max_chars:
            trimmed = body[:max_chars]
            shown = max_chars
            if is_untrusted:
                body_out = f"{UNTRUSTED_OPEN}\n{trimmed}\n{UNTRUSTED_CLOSE}"
            else:
                body_out = trimmed
            return (
                f"RESULT {step_id} {tool} ok ({total_chars} characters, showing the first {shown})\n"
                f"{body_out}\n"
                f'[truncated: call result.read with {{"step": "{step_id}", "offset": {shown}}} for more]'
            )
        return content

    # Generic truncation
    shown = max_chars
    return content[:shown] + f"\n[truncated: {len(content)} characters, showing the first {shown}]"


def make_digest(msg: Message) -> str:
    """Convert an older tool observation message to a compact one-line digest."""
    content = msg.content.strip()
    is_untrusted = UNTRUSTED_OPEN in content

    # Clean untrusted tags for inspection
    raw = content
    if is_untrusted:
        raw = raw.replace(UNTRUSTED_OPEN, "").replace(UNTRUSTED_CLOSE, "").strip()

    first_line, _, body = raw.partition("\n")
    body = body.strip()

    # Pattern: RESULT <step_id> <tool> <ok|error|blocked|declined> ...
    m = re.match(r"^RESULT\s+(\S+)\s+(\S+)\s+(ok|error|blocked|declined)(?::|\s+\((\d+)\s+chars|\s+\((\d+)\s+characters)?", first_line)
    if m:
        step_id, tool, status = m.group(1), m.group(2), m.group(3)
        chars_str = m.group(4) or m.group(5)
        chars_count = int(chars_str) if chars_str else (len(body) or len(content))

        if status == "ok":
            first_120 = body[:120].replace("\n", " ")
            digest = f'{step_id} {tool} ok, {chars_count:,} chars, starts: "{first_120}"'
        else:
            reason = first_line.split(f"{status}:", 1)[-1].strip() if f"{status}:" in first_line else first_line
            digest = f"{step_id} {tool} {status}: {reason}"
    else:
        # Fallback digest
        first_120 = raw[:120].replace("\n", " ")
        digest = f'result: {len(raw):,} chars, starts: "{first_120}"'

    if is_untrusted:
        # Do not carry arbitrary web/MCP text into a compacted prompt. Keep
        # provenance and size only; the original result remains available via
        # result.read.
        digest = re.sub(r', starts: ".*"$', "", digest)
        return f"{UNTRUSTED_OPEN}\n{digest}\n{UNTRUSTED_CLOSE}"
    return digest


class ContextManager:
    """Manages prompt context: truncation, compaction, summarization, and prefix stability."""

    def __init__(
        self,
        engine_settings: Callable[[], EngineSettings] | EngineSettings,
        completer: Completer | None = None,
    ) -> None:
        self._engine_settings = engine_settings if callable(engine_settings) else (lambda: engine_settings)
        self._completer = completer
        self._summary_cache: dict[str, str] = {}

    def truncate_observations(self, messages: list[Message]) -> list[Message]:
        """Truncate tool observation messages to observation_chars."""
        obs_chars = self._engine_settings().observation_chars
        result: list[Message] = []
        for m in messages:
            if m.role == "tool":
                truncated = truncate_observation(m.content, obs_chars)
                result.append(Message(
                    role=m.role,
                    content=truncated,
                    tool_calls=m.tool_calls,
                    tool_call_id=m.tool_call_id,
                    provider_state=m.provider_state,
                ))
            else:
                result.append(m)
        return result

    async def prepare(self, messages: list[Message], budget: int | None = None,
                      *, label: Label = Label.PUBLIC, mode: Mode = Mode.ASK,
                      task_id: str | None = None) -> list[Message]:
        """Prepare messages before a model call: truncate observations and compact if over budget."""
        if not messages:
            return []

        # 1. Truncate tool results to observation_chars
        msgs = self.truncate_observations(messages)

        # 2. Check token budget
        soft_limit = budget if budget is not None else self._engine_settings().soft_context_tokens
        current_tokens = total_tokens(msgs)
        if current_tokens <= soft_limit:
            return msgs

        # 3. Deterministic compaction:
        # Keep:
        # - System prompt (index 0)
        # - Initial user request (first user message)
        # - Any to-do list / plan message
        # - Any pending approval
        # - The latest turn in full (last assistant message and everything after it)
        # - The last error
        n = len(msgs)
        if n <= 3:
            return msgs

        # Find latest turn start (index of the last assistant message)
        last_assistant_idx = -1
        for i in range(n - 1, -1, -1):
            if msgs[i].role == "assistant":
                last_assistant_idx = i
                break

        latest_turn_start = last_assistant_idx if last_assistant_idx >= 0 else (n - 1)

        # Find the last error before the latest turn
        last_error_idx = -1
        for i in range(latest_turn_start - 1, -1, -1):
            c = msgs[i].content.lower()
            if "error:" in c or "blocked by policy" in c or "declined by the user" in c or "failed" in c:
                last_error_idx = i
                break

        first_user_idx = -1
        for i in range(n):
            if msgs[i].role == "user":
                first_user_idx = i
                break

        protected_indices: set[int] = set()
        if n > 0 and msgs[0].role == "system":
            protected_indices.add(0)
        if first_user_idx >= 0:
            protected_indices.add(first_user_idx)
        for i in range(latest_turn_start, n):
            protected_indices.add(i)
        if last_error_idx >= 0:
            protected_indices.add(last_error_idx)

        for i, m in enumerate(msgs):
            if i in protected_indices:
                continue
            c = m.content.lower()
            # to-do list / plan
            if (
                "to-do list" in c
                or ("plan" in c and "todos" in c)
                or ("plan" in c and "items" in c)
                or (m.tool_calls and any(tc.name == "agent.plan" for tc in m.tool_calls))
            ):
                protected_indices.add(i)
                continue
            # pending approval
            if "waiting for approval" in c or "approve" in c:
                protected_indices.add(i)
                continue

        # Pass 1: Compact older messages (replace older tool results with digests)
        compacted: list[Message] = []
        for i, m in enumerate(msgs):
            if i in protected_indices:
                compacted.append(m)
            elif m.role == "tool":
                digest = make_digest(m)
                compacted.append(Message(
                    role="tool",
                    content=digest,
                    tool_calls=m.tool_calls,
                    tool_call_id=m.tool_call_id,
                    provider_state=m.provider_state,
                ))
            elif m.role == "assistant":
                if m.tool_calls:
                    compacted.append(Message(
                        role="assistant",
                        content=m.content[:200] if m.content else "",
                        tool_calls=m.tool_calls,
                    ))
                else:
                    compacted.append(m)
            else:
                compacted.append(m)

        # Pass 2: If still over soft limit -> produce "Working notes" (max 400 tokens)
        if total_tokens(compacted) > soft_limit:
            compacted = await self._summarize_notes(compacted, protected_indices,
                                                    label=label, mode=mode, task_id=task_id)

        return compacted

    async def _summarize_notes(
        self,
        messages: list[Message],
        protected_indices: set[int],
        *,
        label: Label = Label.PUBLIC,
        mode: Mode = Mode.ASK,
        task_id: str | None = None,
    ) -> list[Message]:
        """Produce cached Working notes (<= 400 tokens) using a quick summarize model call."""
        unprotected_middle = [
            (i, m) for i, m in enumerate(messages)
            if i not in protected_indices and m.role in ("tool", "assistant")
        ]
        if not unprotected_middle:
            return messages

        corpus = "\n".join(
            f"{m.role}: {make_digest(m) if UNTRUSTED_OPEN in m.content else m.content}"
            for _, m in unprotected_middle
        )
        content_hash = hashlib.sha256(corpus.encode()).hexdigest()

        notes = self._summary_cache.get(content_hash)
        if notes is None:
            if self._completer is not None:
                try:
                    summary_prompt = (
                        "Summarize these earlier steps into concise Working notes (at most 400 tokens). "
                        "State what has been done, key findings, and current state:\n\n" + corpus[:8000]
                    )
                    req = CompletionRequest(
                        messages=(Message("user", summary_prompt),),
                        max_tokens=400,
                        role="summarize",
                        tag="quick",
                    )
                    completed = await self._completer.complete(
                        req,
                        need=Cap.NONE,
                        label=label,
                        task_id=task_id or "summarize",
                        payload_hash=content_hash,
                        mode=mode,
                    )
                    notes = completed.result.text.strip()
                except Exception:
                    notes = "\n".join(make_digest(m) for _, m in unprotected_middle if m.role == "tool")[:1600]
            else:
                # Deterministic fallback notes without model
                notes = "\n".join(make_digest(m) for _, m in unprotected_middle if m.role == "tool")[:1600]

            self._summary_cache[content_hash] = notes

        # Replace unprotected middle messages with a single Working notes user message
        result: list[Message] = []
        replaced = False
        for i, m in enumerate(messages):
            if i in protected_indices:
                result.append(m)
            else:
                if not replaced:
                    result.append(Message("user", f"Working notes:\n{notes}"))
                    replaced = True

        return result
