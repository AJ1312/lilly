"""Shared plumbing for provider adapters: error mapping and a deadline- and size-capped JSON POST."""
from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from lilly.domain.errors import ProviderError, QuotaExhausted

MAX_RESPONSE_BYTES = 2_000_000


def _retry_after(headers: Mapping[str, str]) -> float | None:
    raw = headers.get("retry-after")
    if raw:
        with contextlib.suppress(ValueError):
            return max(0.0, float(raw))
    return None


def map_http_error(status: int, headers: Mapping[str, str]) -> ProviderError:
    """Translate an HTTP failure into the error the router reasons about."""
    if status == 429:
        return QuotaExhausted(retryable=False, retry_after=_retry_after(headers), status=status)
    if status >= 500:
        return ProviderError(retryable=True, retry_after=_retry_after(headers), status=status)
    return ProviderError(retryable=False, status=status)  # 401/403 bad key, 404 bad model, other client errors


TRANSIENT = frozenset({502, 503, 504})
RETRY_DELAYS_S = (1.0, 2.0)  # free tiers often answer 503 for a moment; two short retries ride it out


async def _post_once(client: httpx.AsyncClient, url: str, headers: Mapping[str, str], body: Mapping[str, Any],
                     max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async with client.stream("POST", url, headers=dict(headers), json=body) as resp:
        if resp.status_code != 200:
            raise map_http_error(resp.status_code, resp.headers)
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ProviderError(retryable=False)
            chunks.append(chunk)
    return b"".join(chunks)


async def post_json(client: httpx.AsyncClient, url: str, *, headers: Mapping[str, str], body: Mapping[str, Any],
                    deadline_s: float, max_bytes: int = MAX_RESPONSE_BYTES,
                    retry_delays: tuple[float, ...] = RETRY_DELAYS_S) -> dict[str, Any]:
    """POST JSON and return the decoded object. The whole call, retries included, is bounded by `deadline_s`
    and the response body by `max_bytes`, enforced while streaming. A 502/503/504 is retried briefly."""
    raw = b""
    try:
        async with asyncio.timeout(deadline_s):
            for attempt in range(len(retry_delays) + 1):
                try:
                    raw = await _post_once(client, url, headers, body, max_bytes)
                    break
                except ProviderError as exc:
                    if exc.status not in TRANSIENT or attempt == len(retry_delays):
                        raise
                    await asyncio.sleep(min(exc.retry_after or retry_delays[attempt], 5.0))
    except (TimeoutError, httpx.HTTPError) as exc:
        raise ProviderError(retryable=True) from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ProviderError(retryable=True) from exc
    if not isinstance(data, dict):
        raise ProviderError(retryable=False)
    return data


async def post_sse(client: httpx.AsyncClient, url: str, *, headers: Mapping[str, str], body: Mapping[str, Any],
                   deadline_s: float, on_event: Callable[[dict[str, Any]], None],
                   max_bytes: int = MAX_RESPONSE_BYTES) -> None:
    """POST JSON and hand each server-sent `data:` object to `on_event` as it arrives. Returns at `[DONE]`; a stream
    that ends without it was cut off and is a retryable failure. Never retried here: the caller has already shown
    the text, so the router's fallback to another model is the only safe retry."""
    total, buffer = 0, b""
    try:
        async with asyncio.timeout(deadline_s), client.stream("POST", url, headers=dict(headers), json=body) as resp:
            if resp.status_code != 200:
                raise map_http_error(resp.status_code, resp.headers)
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ProviderError(retryable=False)
                buffer += chunk
                *lines, buffer = buffer.split(b"\n")
                for raw in lines:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        event = json.loads(data)
                    except ValueError as exc:
                        raise ProviderError(retryable=True) from exc
                    if isinstance(event, dict):
                        on_event(event)
    except (TimeoutError, httpx.HTTPError) as exc:
        raise ProviderError(retryable=True) from exc
    raise ProviderError(retryable=True)      # the stream ended before [DONE]


async def get_json(client: httpx.AsyncClient, url: str, *, max_bytes: int = 1_000_000) -> dict[str, Any]:
    """GET a small JSON object. A non-200 answer or a body that is too big or not an object is a ProviderError."""
    chunks: list[bytes] = []
    total = 0
    async with client.stream("GET", url) as resp:
        if resp.status_code != 200:
            raise map_http_error(resp.status_code, resp.headers)
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ProviderError(retryable=False)
            chunks.append(chunk)
    data = json.loads(b"".join(chunks))
    if not isinstance(data, dict):
        raise ProviderError(retryable=False)
    return data
