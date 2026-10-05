"""Adapter for OpenAI-style chat completion APIs (OpenAI, Mistral, OpenRouter)."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from lilly.domain.errors import ProviderError
from lilly.domain.ports import CompletionRequest, CompletionResult, KeyStore, Provider
from lilly.providers.base import post_json, post_sse


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
        body: dict[str, object] = {
            "model": self._model_id,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            self._limit_field: req.max_tokens * self._limit_factor,
        }
        if self._send_temperature:
            body["temperature"] = req.temperature
        if req.json_mode and self._supports_json:
            body["response_format"] = {"type": "json_object"}
        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {secret.reveal()}", "Content-Type": "application/json", **self._extra}
        if req.on_text is not None:
            return await self._stream(url, headers, body, req)
        data = await post_json(self._client, url, headers=headers, body=body, deadline_s=req.deadline_s)
        try:
            choice = data["choices"][0]
            content = choice["message"].get("content") or ""
            usage = data.get("usage") or {}
            return CompletionResult(content, int(usage.get("prompt_tokens", 0)),
                                    int(usage.get("completion_tokens", 0)), choice.get("finish_reason") or "stop")
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise ProviderError(retryable=False) from exc

    async def _stream(self, url: str, headers: dict[str, str], body: dict[str, object],
                      req: CompletionRequest) -> CompletionResult:
        body = {**body, "stream": True, **({"stream_options": {"include_usage": True}} if self._stream_usage else {})}
        tokens, finish, text, on_text = [0, 0], "stop", "", req.on_text
        assert on_text is not None

        def take(event: dict[str, Any]) -> None:
            nonlocal text, finish
            try:
                usage = event.get("usage")
                if isinstance(usage, dict):
                    tokens[:] = [int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))]
                for choice in event.get("choices") or ():
                    piece = (choice.get("delta") or {}).get("content")
                    if isinstance(piece, str) and piece:
                        text += piece
                        on_text(text)
                    if choice.get("finish_reason"):
                        finish = str(choice["finish_reason"])
            except (TypeError, ValueError, AttributeError) as exc:
                raise ProviderError(retryable=False) from exc

        await post_sse(self._client, url, headers=headers, body=body, deadline_s=req.deadline_s, on_event=take)
        return CompletionResult(text, tokens[0], tokens[1], finish)
