"""Adapter for OpenAI-style chat completion APIs (OpenAI, Mistral, OpenRouter)."""
from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

from lilly.domain.errors import ProviderError
from lilly.domain.ports import CompletionRequest, CompletionResult, KeyStore, ModelToolCall, Provider
from lilly.domain.tools_registry import unwire_name, wire_name
from lilly.providers.base import post_json, post_sse


def _parse_tool_call(tc_raw: dict[str, Any]) -> ModelToolCall:
    tc_id = str(tc_raw.get("id", ""))
    fn = tc_raw.get("function") or {}
    name = unwire_name(str(fn.get("name", "")))
    raw_args = fn.get("arguments", "")
    if isinstance(raw_args, dict):
        # some non-standard mocks/servers return parsed object
        return ModelToolCall(id=tc_id, name=name, arguments=raw_args, raw=json.dumps(raw_args), error=None)

    raw_str = str(raw_args) if raw_args is not None else ""
    parsed_args: Mapping[str, Any] | None = None
    err: str | None = None
    if raw_str.strip():
        try:
            val = json.loads(raw_str)
            if isinstance(val, dict):
                parsed_args = val
            else:
                err = "arguments must be a JSON object"
        except Exception as exc:
            err = f"invalid JSON: {exc}"
    else:
        parsed_args = {}

    return ModelToolCall(id=tc_id, name=name, arguments=parsed_args, raw=raw_str, error=err)


class OpenAICompatProvider(Provider):
    def __init__(self, name: str, client: httpx.AsyncClient, keys: KeyStore, key_ref: str, model_id: str,
                 base_url: str, extra_headers: dict[str, str] | None = None, json_mode: bool = False,
                 limit_field: str = "max_tokens", send_temperature: bool = True, limit_factor: int = 1,
                 stream_usage: bool = False) -> None:
        self.name = name
        self._client, self._keys, self._key_ref = client, keys, key_ref
        self._model_id, self._base_url = model_id, base_url.rstrip("/")
        self._extra = extra_headers or {}
        self._supports_json = json_mode
        self._limit_field, self._send_temperature, self._limit_factor = limit_field, send_temperature, limit_factor
        self._stream_usage = stream_usage      # the vendor accepts stream_options to report token use while streaming

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        secret = await asyncio.to_thread(self._keys.get, self._key_ref)
        if secret is None:
            raise ProviderError(retryable=False, status=401)

        formatted_messages: list[dict[str, Any]] = []
        for m in req.messages:
            if m.role == "tool":
                formatted_messages.append({
                    "role": "tool",
                    "content": m.content,
                    "tool_call_id": m.tool_call_id or "",
                })
            elif m.role == "assistant" and m.tool_calls:
                tc_list = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": wire_name(tc.name),
                            "arguments": tc.raw if tc.raw else json.dumps(dict(tc.arguments or {})),
                        },
                    }
                    for tc in m.tool_calls
                ]
                msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": m.content if m.content else None,
                    "tool_calls": tc_list,
                }
                formatted_messages.append(msg)
            else:
                content: str | list[dict[str, Any]] = m.content
                if req.image_paths and m.role == "user":
                    content = [{"type": "text", "text": m.content}]
                    for image_path in req.image_paths:
                        raw = await asyncio.to_thread(_read_image, image_path)
                        mime = mimetypes.guess_type(image_path)[0] or "image/png"
                        content.append({"type": "image_url", "image_url": {
                            "url": f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"}})
                formatted_messages.append({"role": m.role, "content": content})

        body: dict[str, object] = {
            "model": self._model_id,
            "messages": formatted_messages,
            self._limit_field: req.max_tokens * self._limit_factor,
        }
        if self._send_temperature:
            body["temperature"] = req.temperature
        if req.json_mode and self._supports_json:
            body["response_format"] = {"type": "json_object"}
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
            body["tool_choice"] = req.tool_choice

        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {secret.reveal()}", "Content-Type": "application/json", **self._extra}
        if req.on_text is not None:
            return await self._stream(url, headers, body, req)
        data = await post_json(self._client, url, headers=headers, body=body, deadline_s=req.deadline_s)
        try:
            choice = data["choices"][0]
            msg = choice.get("message") or {}
            content = msg.get("content") or ""
            usage = data.get("usage") or {}
            tool_calls: list[ModelToolCall] = []
            for tc in msg.get("tool_calls") or ():
                tool_calls.append(_parse_tool_call(tc))

            return CompletionResult(
                content,
                int(usage.get("prompt_tokens", 0)),
                int(usage.get("completion_tokens", 0)),
                choice.get("finish_reason") or "stop",
                tool_calls=tuple(tool_calls),
            )
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise ProviderError(retryable=False) from exc

    async def _stream(self, url: str, headers: dict[str, str], body: dict[str, object],
                      req: CompletionRequest) -> CompletionResult:
        body = {**body, "stream": True, **({"stream_options": {"include_usage": True}} if self._stream_usage else {})}
        tokens, finish, text, on_text = [0, 0], "stop", "", req.on_text
        accumulated_tc: dict[int, dict[str, Any]] = {}
        assert on_text is not None

        def take(event: dict[str, Any]) -> None:
            nonlocal text, finish
            try:
                usage = event.get("usage")
                if isinstance(usage, dict):
                    tokens[:] = [int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))]
                for choice in event.get("choices") or ():
                    delta = choice.get("delta") or {}
                    piece = delta.get("content")
                    if isinstance(piece, str) and piece:
                        text += piece
                        on_text(text)

                    for raw_tc in delta.get("tool_calls") or ():
                        idx = int(raw_tc.get("index", 0))
                        if idx not in accumulated_tc:
                            accumulated_tc[idx] = {
                                "id": "",
                                "function": {
                                    "name": "",
                                    "arguments": "",
                                },
                            }
                        if raw_tc.get("id"):
                            accumulated_tc[idx]["id"] += raw_tc["id"]
                        fn = raw_tc.get("function") or {}
                        if fn.get("name"):
                            accumulated_tc[idx]["function"]["name"] += fn["name"]
                        if fn.get("arguments"):
                            accumulated_tc[idx]["function"]["arguments"] += fn["arguments"]

                    if choice.get("finish_reason"):
                        finish = str(choice["finish_reason"])
            except (TypeError, ValueError, AttributeError) as exc:
                raise ProviderError(retryable=False) from exc

        await post_sse(self._client, url, headers=headers, body=body, deadline_s=req.deadline_s, on_event=take)
        parsed_calls = [
            _parse_tool_call(accumulated_tc[idx])
            for idx in sorted(accumulated_tc)
        ]
        return CompletionResult(text, tokens[0], tokens[1], finish, tool_calls=tuple(parsed_calls))


def _read_image(path: str) -> bytes:
    data = Path(path).read_bytes()
    if not data or len(data) > 8_000_000:
        raise ProviderError(retryable=False)
    return data
