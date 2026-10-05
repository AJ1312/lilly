"""The small JSON-RPC 2.0 subset Lilly speaks to an MCP server: newline-delimited messages over stdio.

Everything a server sends is untrusted. These helpers only parse and build messages; they never act on them.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from lilly.domain.errors import ToolError

METHOD_NOT_FOUND = -32601
MAX_BAD_LINES = 20       # invalid JSON lines tolerated before the connection is cut
MAX_IN_FLIGHT = 4        # concurrent tools/call requests on one server
MAX_ID_CHARS = 256       # a server request id longer than this is not echoed back


class McpConnectionError(ToolError):
    """The connection to the server is unusable (it exited, timed out or misbehaved); it must be restarted."""


class McpTimeout(McpConnectionError):
    """The server did not answer in time."""


class McpStartRefused(ToolError):
    """The server was not started because of Lilly-side configuration (for example a missing secret)."""


@dataclass(frozen=True, slots=True)
class CallResult:
    """A tools/call answer, still untrusted: content items as the server sent them."""

    content: tuple[Mapping[str, Any], ...]
    is_error: bool


def encode(msg: Mapping[str, Any]) -> bytes:
    return json.dumps(msg, separators=(",", ":")).encode() + b"\n"


def request(rid: int, method: str, params: Mapping[str, Any]) -> bytes:
    return encode({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})


def notification(method: str, params: Mapping[str, Any] | None = None) -> bytes:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params:
        msg["params"] = params
    return encode(msg)


def result_reply(rid: str | int, result: Mapping[str, Any]) -> bytes:
    return encode({"jsonrpc": "2.0", "id": rid, "result": result})


def error_reply(rid: str | int, code: int, message: str) -> bytes:
    return encode({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}})


def decode(line: bytes) -> dict[str, Any] | None:
    """One message, or None when the line is not a JSON object."""
    try:
        msg = json.loads(line)
    except (ValueError, RecursionError):
        return None
    return msg if isinstance(msg, dict) else None


def valid_id(value: object) -> str | int | None:
    """A JSON-RPC id we are willing to echo: an int or a short string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and len(value) <= MAX_ID_CHARS:
        return value
    return None


def parse_call_result(result: object) -> CallResult:
    if not isinstance(result, dict):
        raise ToolError("the server sent an invalid tool result")
    content = result.get("content", [])
    if not isinstance(content, list):
        raise ToolError("the server sent an invalid tool result")
    items = tuple(c for c in content if isinstance(c, dict))
    return CallResult(items, result.get("isError") is True)
