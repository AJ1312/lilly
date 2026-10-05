"""An approved MCP tool as a Lilly Tool. Its answers are untrusted text: returned as data, never interpreted."""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from typing import Any, Protocol

from lilly.domain.errors import ToolError, ValidationFailed
from lilly.domain.labels import Risk
from lilly.domain.mcp import MAX_OUTPUT_CHARS, McpServerConfig, McpToolInfo, exposed_name
from lilly.domain.ports import ToolContext, ToolResult
from lilly.domain.tools_registry import ToolSpec
from lilly.tools.base import Tool
from lilly.tools.mcp.protocol import CallResult

MAX_ARGS_BYTES = 100_000
MAX_ERROR_CHARS = 500
MAX_ARGS_SUMMARY = 300
POLL_S = 0.1
_TRUNCATED = f"\n[truncated: the result was cut at {MAX_OUTPUT_CHARS} characters]"
_PROP_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_JSON_TYPES = frozenset({"string", "number", "integer", "boolean", "array", "object", "null"})


class Caller(Protocol):
    async def call(self, server: str, tool: str, arguments: Mapping[str, Any], timeout: float | None) -> CallResult: ...


def args_summary(schema: Mapping[str, Any]) -> str:
    """A compact `{"name": "type"}` summary of the schema's properties. Only plain names and JSON type words
    survive, so a hostile schema cannot smuggle text into the planner's prompt through it."""
    props = schema.get("properties")
    required = schema.get("required")
    req = {r for r in required if isinstance(r, str)} if isinstance(required, list) else set()
    out: dict[str, str] = {}
    if isinstance(props, dict):
        for key, value in props.items():
            if not isinstance(key, str) or not _PROP_NAME.fullmatch(key):
                continue
            kind = value.get("type") if isinstance(value, dict) else None
            text = kind if isinstance(kind, str) and kind in _JSON_TYPES else "any"
            out[key] = text if key in req else f"{text}, optional"
    text = json.dumps(out, separators=(",", ":"))
    return text if len(text) <= MAX_ARGS_SUMMARY else text[:MAX_ARGS_SUMMARY - 1] + "…"


def render_content(items: tuple[Mapping[str, Any], ...]) -> str:
    """Text items joined; everything else is summarised, never passed through."""
    parts: list[str] = []
    for item in items:
        kind = item.get("type")
        if kind == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
        elif kind in ("image", "audio"):
            mime = _short(item.get("mimeType"), "unknown type")
            data = item.get("data")
            size = len(data) * 3 // 4 if isinstance(data, str) else 0
            parts.append(f"[{kind}: {mime}, {size} bytes omitted]")
        elif kind == "resource" and isinstance(item.get("resource"), dict):
            res = item["resource"]
            if isinstance(res.get("text"), str):
                parts.append(res["text"])
            else:
                blob = res.get("blob")
                parts.append(f"[resource: {_short(res.get('uri'), 'unnamed')}, "
                             f"{len(blob) * 3 // 4 if isinstance(blob, str) else 0} bytes omitted]")
        elif kind == "resource_link":
            parts.append(f"[resource link: {_short(item.get('uri'), 'unnamed')} not fetched]")
        else:
            parts.append(f"[{_short(kind, 'unknown')} item omitted]")
    return "\n".join(parts)


def _short(value: object, default: str) -> str:
    return re.sub(r"[^A-Za-z0-9/+._:-]", "?", value[:80]) if isinstance(value, str) and value else default


def cap_output(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS - len(_TRUNCATED)] + _TRUNCATED


class McpTool(Tool):
    """One approved tool of one server. Risk comes from the owner's approval, never from the server."""

    def __init__(self, caller: Caller, cfg: McpServerConfig, info: McpToolInfo, risk: Risk) -> None:
        self.name = exposed_name(cfg.name, info.name)
        self._caller, self._cfg, self._tool = caller, cfg, info.name
        self._spec = ToolSpec(risk=risk, egress=True, reads_label=cfg.data_label, untrusted=True, path_args=(),
                              confirm=False, module=None,
                              doc=f"(MCP server {cfg.name}) {info.description or info.name}",
                              args=args_summary(info.input_schema))

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        if not isinstance(args, dict):
            raise ValidationFailed("the arguments must be an object")
        try:
            size = len(json.dumps(args))
        except (TypeError, ValueError):
            raise ValidationFailed("the arguments must be plain JSON values") from None
        if size > MAX_ARGS_BYTES:
            raise ValidationFailed("the arguments are too large")
        if ctx.cancelled():
            raise ToolError("the step was cancelled")
        task = asyncio.ensure_future(self._caller.call(self._cfg.name, self._tool, args, ctx.deadline_s))
        try:
            while not (await asyncio.wait({task}, timeout=POLL_S))[0]:
                if ctx.cancelled():
                    raise ToolError("the step was cancelled")
            result = task.result()
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            elif not task.cancelled():
                task.exception()  # mark retrieved
        text = render_content(result.content)
        if result.is_error:
            raise ToolError(f"the tool reported an error: {text[:MAX_ERROR_CHARS] or 'no details'}")
        return ToolResult(cap_output(text), self._cfg.data_label, True)
