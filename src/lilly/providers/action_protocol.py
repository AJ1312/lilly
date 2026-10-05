"""Action Protocol fallback for models that lack native tool calling.

For models with tools = "protocol" (or detected at runtime), this adapter:
1. Renders tool schemas into the system prompt using ACTION_PROTOCOL.
2. Formats messages into pure user/assistant dialog.
3. Parses the single JSON object reply (tolerating fenced JSON and leading/trailing prose).
4. Handles one repair turn on invalid JSON using ACTION_PROTOCOL_REPAIR.
5. Remembers runtime detections for the current session only.
"""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from typing import Any

from lilly.domain.ports import CompletionRequest, CompletionResult, Message, ModelToolCall, Provider, ToolSchema
from lilly.domain.prompts import ACTION_PROTOCOL, ACTION_PROTOCOL_REPAIR

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_DETECTED_PROTOCOL_MODELS: set[str] = set()
_ACTION_SHAPE_COUNTS: dict[str, int] = {}


def mark_detected_protocol(model_name: str) -> None:
    """Record that this model was detected as following the action protocol in this session."""
    _DETECTED_PROTOCOL_MODELS.add(model_name)


def is_detected_protocol(model_name: str) -> bool:
    """True if this model has been detected as following the action protocol in this session."""
    return model_name in _DETECTED_PROTOCOL_MODELS


def reset_detected_protocol() -> None:
    """Reset session detections (used in tests)."""
    _DETECTED_PROTOCOL_MODELS.clear()
    _ACTION_SHAPE_COUNTS.clear()


def render_tool_list(tools: tuple[ToolSchema, ...] | list[ToolSchema]) -> str:
    """Render tools into a readable list for the ACTION_PROTOCOL prompt."""
    lines: list[str] = []
    for t in tools:
        props = t.parameters.get("properties", {})
        req = set(t.parameters.get("required", ()))
        args_summary: list[str] = []
        for k, v in props.items():
            if isinstance(v, Mapping):
                desc = v.get("description") or v.get("type", "value")
                opt = "" if k in req else " (optional)"
                args_summary.append(f"{k}: {desc}{opt}")
            else:
                args_summary.append(f"{k}")
        args_str = ", ".join(args_summary) if args_summary else "no arguments"
        lines.append(f"- {t.name}: {t.description}\n  args: {{{args_str}}}")
    return "\n".join(lines)


def _extract_json_object(text: str) -> str | None:
    """Find a candidate JSON object substring, handling code fences and surrounding text."""
    # 1. Try markdown code fences first
    match = _FENCED_JSON_RE.search(text)
    if match:
        return match.group(1).strip()

    # 2. Find outermost balanced braces containing either 'thought', 'calls', or 'final'
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace:last_brace + 1].strip()
        return candidate

    return None


def parse_protocol_reply(text: str) -> tuple[str, tuple[ModelToolCall, ...], bool]:
    """Parse an action protocol reply into (thought_or_final_text, tool_calls, is_valid).
    
    Tolerates code fences and leading/trailing text.
    """
    raw_json = _extract_json_object(text)
    if not raw_json:
        return text, (), False

    try:
        data = json.loads(raw_json)
    except Exception:
        return text, (), False

    if not isinstance(data, dict):
        return text, (), False

    # Shape A: To use tools: {"thought": "...", "calls": [{"tool": "...", "args": {...}}]}
    if "calls" in data and isinstance(data["calls"], list):
        calls: list[ModelToolCall] = []
        for c in data["calls"]:
            if not isinstance(c, dict):
                continue
            t_name = str(c.get("tool") or c.get("name") or "")
            raw_args = c.get("args") if "args" in c else c.get("arguments", {})
            args_map: Mapping[str, Any] | None = None
            err: str | None = None
            if isinstance(raw_args, dict):
                args_map = raw_args
                raw_str = json.dumps(raw_args)
            elif isinstance(raw_args, str):
                raw_str = raw_args
                try:
                    loaded = json.loads(raw_args)
                    if isinstance(loaded, dict):
                        args_map = loaded
                    else:
                        err = "args must be an object"
                except Exception as exc:
                    err = f"invalid JSON: {exc}"
            else:
                args_map = {}
                raw_str = "{}"
            calls.append(ModelToolCall(
                id=f"call_{uuid.uuid4().hex[:8]}",
                name=t_name,
                arguments=args_map,
                raw=raw_str,
                error=err,
            ))
        thought = str(data.get("thought") or "")
        return thought, tuple(calls), True

    # Shape B: To finish: {"thought": "...", "final": "..."}
    if "final" in data:
        final_text = str(data["final"])
        return final_text, (), True

    return text, (), False


class ActionProtocolAdapter(Provider):
    """Wraps an underlying Provider to speak the JSON Action Protocol."""

    def __init__(self, inner: Provider, model_name: str) -> None:
        self.inner = inner
        self.name = inner.name
        self.model_name = model_name

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        if not req.tools:
            return await self.inner.complete(req)

        # 1. Format prompt with ACTION_PROTOCOL instructions and rendered tool list
        rendered = render_tool_list(req.tools)
        protocol_instruction = ACTION_PROTOCOL.format(rendered_tool_list=rendered)

        messages: list[Message] = []
        has_system = False
        for m in req.messages:
            if m.role == "system":
                messages.append(Message("system", f"{m.content}\n\n{protocol_instruction}"))
                has_system = True
            elif m.role == "tool":
                # Convert tool observations into user messages for protocol models
                messages.append(Message("user", m.content))
            elif m.role == "assistant" and m.tool_calls:
                # Format previous assistant tool calls as protocol JSON
                calls_data = [{"tool": tc.name, "args": dict(tc.arguments or {})} for tc in m.tool_calls]
                payload = json.dumps({"thought": m.content, "calls": calls_data})
                messages.append(Message("assistant", payload))
            else:
                messages.append(m)

        if not has_system:
            messages.insert(0, Message("system", protocol_instruction))

        underlying_req = CompletionRequest(
            messages=tuple(messages),
            max_tokens=req.max_tokens,
            json_mode=False,
            temperature=req.temperature,
            deadline_s=req.deadline_s,
            quick=req.quick,
            role=req.role,
            tag=req.tag,
            priority=req.priority,
            tools=(),
            tool_choice="none",
        )

        res = await self.inner.complete(underlying_req)
        thought_or_final, tool_calls, is_valid = parse_protocol_reply(res.text)

        if is_valid:
            # Check for runtime detection
            _ACTION_SHAPE_COUNTS[self.model_name] = _ACTION_SHAPE_COUNTS.get(self.model_name, 0) + 1
            if _ACTION_SHAPE_COUNTS[self.model_name] >= 2 or tool_calls:
                mark_detected_protocol(self.model_name)
            return CompletionResult(
                thought_or_final,
                res.input_tokens,
                res.output_tokens,
                res.finish_reason,
                tool_calls=tool_calls,
                provider_state=res.provider_state,
            )

        # 2. Repair turn on failure
        repair_messages = list(messages)
        repair_messages.append(Message("assistant", res.text))
        repair_messages.append(Message("user", ACTION_PROTOCOL_REPAIR))

        repair_req = CompletionRequest(
            messages=tuple(repair_messages),
            max_tokens=req.max_tokens,
            json_mode=False,
            temperature=req.temperature,
            deadline_s=req.deadline_s,
            quick=req.quick,
            role=req.role,
            tag=req.tag,
            priority=req.priority,
            tools=(),
            tool_choice="none",
        )

        repair_res = await self.inner.complete(repair_req)
        r_thought, r_calls, r_valid = parse_protocol_reply(repair_res.text)
        if r_valid:
            _ACTION_SHAPE_COUNTS[self.model_name] = _ACTION_SHAPE_COUNTS.get(self.model_name, 0) + 1
            mark_detected_protocol(self.model_name)
            return CompletionResult(
                r_thought,
                res.input_tokens + repair_res.input_tokens,
                res.output_tokens + repair_res.output_tokens,
                repair_res.finish_reason,
                tool_calls=r_calls,
                provider_state=repair_res.provider_state,
            )

        # If repair also failed, return raw output
        return CompletionResult(
            repair_res.text,
            res.input_tokens + repair_res.input_tokens,
            res.output_tokens + repair_res.output_tokens,
            repair_res.finish_reason,
            tool_calls=(),
            provider_state=repair_res.provider_state,
        )
