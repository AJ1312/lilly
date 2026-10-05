"""Adapter for the Google Gemini API."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from lilly.domain.errors import ProviderError
from lilly.domain.ports import CompletionRequest, CompletionResult, KeyStore, Provider
from lilly.providers.base import post_json


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, client: httpx.AsyncClient, keys: KeyStore, key_ref: str, model_id: str,
                 base_url: str = "https://generativelanguage.googleapis.com/v1beta") -> None:
        self._client, self._keys, self._key_ref = client, keys, key_ref
        self._model_id, self._base_url = model_id, base_url.rstrip("/")

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        secret = await asyncio.to_thread(self._keys.get, self._key_ref)
        if secret is None:
            raise ProviderError(retryable=False, status=401)
        system = "\n\n".join(m.content for m in req.messages if m.role == "system")
        contents = [{"role": "user" if m.role == "user" else "model", "parts": [{"text": m.content}]}
                    for m in req.messages if m.role != "system"]
        config: dict[str, Any] = {"maxOutputTokens": req.max_tokens, "temperature": req.temperature}
        if req.json_mode:
            config["responseMimeType"] = "application/json"
        body: dict[str, Any] = {"contents": contents, "generationConfig": config}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        data = await post_json(
            self._client, f"{self._base_url}/models/{self._model_id}:generateContent",
            headers={"x-goog-api-key": secret.reveal(), "Content-Type": "application/json"},
            body=body, deadline_s=req.deadline_s)
        try:
            cand = data["candidates"][0]
            text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
            usage = data.get("usageMetadata") or {}
            return CompletionResult(text, int(usage.get("promptTokenCount", 0)),
                                    int(usage.get("candidatesTokenCount", 0)), str(cand.get("finishReason", "STOP")).lower())
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise ProviderError(retryable=False) from exc
