"""Adapter for the Google Gemini API with native function calling."""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Mapping
from typing import Any

import httpx

from lilly.domain.errors import ProviderError
from lilly.domain.ports import CompletionRequest, CompletionResult, KeyStore, ModelToolCall, Provider
from lilly.domain.tools_registry import unwire_name, wire_name
from lilly.providers.base import post_json

_TYPE_MAP = {
    "string": "STRING",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
}


def to_gemini_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Convert JSON Schema to the subset accepted by Google Gemini function declarations.
    
    Verified against ai.google.dev/api/rest/v1beta/models/generateContent on 2026-09-24:
    - Types must be uppercase: STRING, INTEGER, NUMBER, BOOLEAN, ARRAY, OBJECT
    - Supported fields: type, description, properties, required, items, enum
    - Drops unsupported keywords: $schema, additionalProperties, minimum, maximum, etc.
    """
    out: dict[str, Any] = {}
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        out["type"] = _TYPE_MAP.get(raw_type.lower(), "STRING")
    elif isinstance(raw_type, (list, tuple)) and raw_type:
        # Take first mapped type
        first = str(raw_type[0]).lower()
        out["type"] = _TYPE_MAP.get(first, "STRING")
    else:
        out["type"] = "OBJECT"

    if "description" in schema and isinstance(schema["description"], str):
        out["description"] = schema["description"]

    if "enum" in schema and isinstance(schema["enum"], (list, tuple)):
        out["enum"] = [str(e) for e in schema["enum"]]

    if "properties" in schema and isinstance(schema["properties"], Mapping):
        props: dict[str, Any] = {}
        for k, v in schema["properties"].items():
            if isinstance(v, Mapping):
                props[k] = to_gemini_schema(v)
        out["properties"] = props

    if "required" in schema and isinstance(schema["required"], (list, tuple)):
        out["required"] = [str(r) for r in schema["required"]]

    if "items" in schema and isinstance(schema["items"], Mapping):
        out["items"] = to_gemini_schema(schema["items"])

    return out


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
        contents: list[dict[str, Any]] = []

        # Find any passed provider_state to echo
        provider_state: Mapping[str, Any] | None = None
        for m in req.messages:
            if m.provider_state:
                provider_state = m.provider_state

            if m.role == "system":
                continue
            elif m.role == "tool":
                # In Gemini, tool responses are user turns with functionResponse parts
                func_name = wire_name(m.tool_call_id or "")
                contents.append({
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": func_name,
                                "response": {"output": m.content},
                            }
                        }
                    ],
                })
            elif m.role == "assistant":
                parts: list[dict[str, Any]] = []
                if m.content:
                    parts.append({"text": m.content})
                for tc in m.tool_calls:
                    parts.append({
                        "functionCall": {
                            "name": wire_name(tc.name),
                            "args": dict(tc.arguments or {}),
                        }
                    })
                if not parts:
                    parts.append({"text": ""})
                contents.append({"role": "model", "parts": parts})
            else:
                contents.append({"role": "user", "parts": [{"text": m.content}]})

        config: dict[str, Any] = {"maxOutputTokens": req.max_tokens, "temperature": req.temperature}
        if req.json_mode:
            config["responseMimeType"] = "application/json"

        body: dict[str, Any] = {"contents": contents, "generationConfig": config}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        if req.tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": wire_name(t.name),
                            "description": t.description,
                            "parameters": to_gemini_schema(t.parameters),
                        }
                        for t in req.tools
                    ]
                }
            ]

        data = await post_json(
            self._client, f"{self._base_url}/models/{self._model_id}:generateContent",
            headers={"x-goog-api-key": secret.reveal(), "Content-Type": "application/json"},
            body=body, deadline_s=req.deadline_s)
        try:
            cand = data["candidates"][0]
            parts = cand.get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts if "text" in p)

            tool_calls: list[ModelToolCall] = []
            for p in parts:
                if "functionCall" in p:
                    fc = p["functionCall"]
                    fn_name = unwire_name(str(fc.get("name", "")))
                    args = fc.get("args") or {}
                    tc_id = str(fc.get("id") or f"call_{uuid.uuid4().hex[:8]}")
                    tool_calls.append(ModelToolCall(
                        id=tc_id,
                        name=fn_name,
                        arguments=args,
                        raw=json.dumps(args),
                        error=None,
                    ))

            usage = data.get("usageMetadata") or {}
            # Echo or capture provider_state
            resp_state = data.get("providerState") or provider_state

            return CompletionResult(
                text,
                int(usage.get("promptTokenCount", 0)),
                int(usage.get("candidatesTokenCount", 0)),
                str(cand.get("finishReason", "STOP")).lower(),
                tool_calls=tuple(tool_calls),
                provider_state=resp_state,
            )
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise ProviderError(retryable=False) from exc
