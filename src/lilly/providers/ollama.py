"""Adapter for an Ollama server on this computer (or your private network), and a check that explains problems."""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from lilly.domain.errors import ProviderError
from lilly.domain.ports import CompletionRequest, CompletionResult, ModelToolCall, Provider
from lilly.domain.tools_registry import unwire_name, wire_name
from lilly.providers.base import MAX_RESPONSE_BYTES, get_json, map_http_error
from lilly.providers.local_gate import LocalGate

DEFAULT_URL = "http://127.0.0.1:11434"
MIN_DEADLINE_S = 120.0        # the first call loads the model into memory, which can take a while
DEFAULT_KEEP_ALIVE_S = 300
MAX_MODELS_LISTED = 200
PROBE_TIMEOUT_S = 5.0


def _parse_line(line: str) -> dict[str, Any]:
    try:
        data = json.loads(line)
    except ValueError as exc:
        raise ProviderError(retryable=True) from exc
    if not isinstance(data, dict):
        raise ProviderError(retryable=True)
    return data


class OllamaProvider(Provider):
    """Streams the answer, so a slow model is not mistaken for a dead one: the connection only fails after a
    long silence (the client's read timeout) or when the whole call passes its deadline."""

    name = "ollama"

    def __init__(self, client: httpx.AsyncClient, model_id: str, base_url: str | None = None,
                 gate: LocalGate | None = None, keep_alive_s: Callable[[], int] = lambda: DEFAULT_KEEP_ALIVE_S) -> None:
        self._client, self._model_id = client, model_id
        self._base_url = (base_url or DEFAULT_URL).rstrip("/")
        self._gate, self._keep_alive_s = gate or LocalGate(), keep_alive_s

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        formatted_messages: list[dict[str, Any]] = []
        for m in req.messages:
            if m.role == "tool":
                formatted_messages.append({"role": "tool", "content": m.content})
            elif m.role == "assistant" and m.tool_calls:
                tc_list = [
                    {
                        "function": {
                            "name": wire_name(tc.name),
                            "arguments": dict(tc.arguments or {}) if isinstance(tc.arguments, Mapping) else {},
                        }
                    }
                    for tc in m.tool_calls
                ]
                formatted_messages.append({"role": "assistant", "content": m.content, "tool_calls": tc_list})
            else:
                formatted_messages.append({"role": m.role, "content": m.content})

        body: dict[str, object] = {
            "model": self._model_id,
            "messages": formatted_messages,
            "stream": True,
            "keep_alive": f"{self._keep_alive_s()}s",      # how long the model stays in memory after this answer
            "options": {"temperature": req.temperature, "num_predict": req.max_tokens},
        }
        if req.json_mode:
            body["format"] = "json"
        if req.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": wire_name(t.name),
                        "description": t.description,
                        "parameters": dict(t.parameters),
                    },
                }
                for t in req.tools
            ]

        try:
            async with asyncio.timeout(max(req.deadline_s, MIN_DEADLINE_S)):
                async with self._gate.use(self._client, self._base_url, self._model_id):
                    return await self._stream(body, req.on_text)
        except (TimeoutError, httpx.HTTPError) as exc:
            raise ProviderError(retryable=True) from exc   # not running, stalled, or too slow: try later

    @staticmethod
    def _take(
        raw: bytes,
        parts: list[str],
        tool_calls_raw: list[dict[str, Any]],
        on_text: Callable[[str], None] | None = None,
    ) -> dict[str, Any] | None:
        """Read one line of the stream: add its text to `parts`, and return it when it is the final line."""
        if not raw.strip():
            return None
        chunk = _parse_line(raw.decode("utf-8", "replace"))
        if "error" in chunk:
            raise ProviderError(retryable=True)
        message = chunk.get("message")
        if isinstance(message, dict):
            if isinstance(message.get("content"), str):
                parts.append(message["content"])
                if on_text is not None and message["content"]:
                    on_text("".join(parts))
            if "tool_calls" in message and isinstance(message["tool_calls"], list):
                tool_calls_raw.extend(message["tool_calls"])
        return chunk if chunk.get("done") is True else None

    async def _stream(self, body: Mapping[str, object], on_text: Callable[[str], None] | None) -> CompletionResult:
        parts: list[str] = []
        raw_tool_calls: list[dict[str, Any]] = []
        total = 0
        last: dict[str, Any] = {}
        async with self._client.stream("POST", f"{self._base_url}/api/chat", json=body,
                                       headers={"Content-Type": "application/json"}) as resp:
            if resp.status_code == 404:            # the model is not installed: fixable, so not a long cool-down
                raise ProviderError(retryable=True, status=404)
            if resp.status_code != 200:
                err_body = await resp.aread()
                raise map_http_error(resp.status_code, resp.headers, err_body)
            buffer = b""
            async for data in resp.aiter_bytes():
                total += len(data)
                if total > MAX_RESPONSE_BYTES:
                    raise ProviderError(retryable=False)     # counted as bytes arrive, newline or not
                buffer += data
                *lines, buffer = buffer.split(b"\n")
                for line in lines:
                    done = self._take(line, parts, raw_tool_calls, on_text)
                    if done is not None:
                        last = done
                        break
                if last:
                    break
            if not last and buffer.strip():
                last = self._take(buffer, parts, raw_tool_calls, on_text) or {}
        if not last:
            raise ProviderError(retryable=True)    # the connection ended before the answer was complete

        parsed_tool_calls: list[ModelToolCall] = []
        for tc in raw_tool_calls:
            fn = tc.get("function") or {}
            fn_name = unwire_name(str(fn.get("name", "")))
            args_val = fn.get("arguments")
            raw_str = ""
            args_dict: Mapping[str, Any] | None = None
            err_msg: str | None = None
            if isinstance(args_val, dict):
                args_dict = args_val
                raw_str = json.dumps(args_val)
            elif isinstance(args_val, str):
                raw_str = args_val
                try:
                    loaded = json.loads(args_val)
                    if isinstance(loaded, dict):
                        args_dict = loaded
                    else:
                        err_msg = "arguments must be a JSON object"
                except Exception as exc:
                    err_msg = f"invalid JSON: {exc}"
            else:
                args_dict = {}
                raw_str = "{}"
            parsed_tool_calls.append(ModelToolCall(
                id=f"call_{uuid.uuid4().hex[:8]}",
                name=fn_name,
                arguments=args_dict,
                raw=raw_str,
                error=err_msg,
            ))

        try:
            return CompletionResult(
                "".join(parts),
                int(last.get("prompt_eval_count", 0)),
                int(last.get("eval_count", 0)),
                str(last.get("done_reason", "stop")),
                tool_calls=tuple(parsed_tool_calls),
            )
        except (TypeError, ValueError) as exc:
            raise ProviderError(retryable=False) from exc


@dataclass(frozen=True, slots=True)
class OllamaStatus:
    reachable: bool
    version: str | None
    models: tuple[str, ...]
    model_ready: bool | None      # None when no model was asked about
    message: str                  # what is wrong and what to do about it, or that all is well


def _has_model(installed: tuple[str, ...], wanted: str) -> bool:
    tagged = wanted if ":" in wanted else f"{wanted}:latest"
    return wanted in installed or tagged in installed


async def probe(client: httpx.AsyncClient, base_url: str | None = None, model_id: str | None = None) -> OllamaStatus:
    """Ask Ollama who it is and what it has installed, and explain in plain words what is wrong if it cannot."""
    url = (base_url or DEFAULT_URL).rstrip("/")
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_S):
            version = await get_json(client, f"{url}/api/version")
            tags = await get_json(client, f"{url}/api/tags")
    except (TimeoutError, httpx.TimeoutException):
        return OllamaStatus(False, None, (), None, f"Ollama at {url} did not answer within {PROBE_TIMEOUT_S:.0f} seconds. "
                                                   "Check that it is running and not busy loading a model.")
    except httpx.ConnectError:
        return OllamaStatus(False, None, (), None, f"Lilly could not reach Ollama at {url}. Start it: open the Ollama "
                                                   "app, or run 'ollama serve' in a terminal.")
    except (httpx.HTTPError, ProviderError, ValueError):
        return OllamaStatus(False, None, (), None, f"Something answered at {url}, but it does not look like Ollama. "
                                                   "Check the address in Settings.")
    raw_models = tags.get("models")
    names = tuple(sorted({str(m["name"]) for m in raw_models if isinstance(m, dict) and isinstance(m.get("name"), str)}
                         )[:MAX_MODELS_LISTED]) if isinstance(raw_models, list) else ()
    found = str(version.get("version", "")) or None
    if model_id is None:
        return OllamaStatus(True, found, names, None, f"Ollama{' ' + found if found else ''} is running with {len(names)} model(s).")
    ready = _has_model(names, model_id)
    if ready:
        return OllamaStatus(True, found, names, True, f"Ollama is running and {model_id} is installed.")
    return OllamaStatus(True, found, names, False, f"Ollama is running, but {model_id} is not installed. "
                                                   f"Install it with: ollama pull {model_id}")
