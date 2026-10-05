"""Shared plumbing for provider adapters: error mapping and a deadline- and size-capped JSON POST."""
from __future__ import annotations

import asyncio
import contextlib
import email.utils
import json
import re
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from lilly.domain.errors import ProviderError, RateLimited, RateLimitScope

MAX_RESPONSE_BYTES = 2_000_000
_RETRY_DELAY_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)s?$")


def _parse_retry_after(raw: str, clock_wall: Callable[[], float]) -> float | None:
    raw = raw.strip()
    with contextlib.suppress(ValueError):
        return max(0.0, float(raw))
    with contextlib.suppress(Exception):
        dt = email.utils.parsedate_to_datetime(raw)
        return max(0.0, dt.timestamp() - clock_wall())
    return None


def _parse_reset_header(raw: str, clock_wall: Callable[[], float]) -> float | None:
    raw = raw.strip()
    with contextlib.suppress(ValueError):
        val = float(raw)
        if val > 1_000_000_000_000:  # epoch ms
            return max(0.0, (val / 1000.0) - clock_wall())
        if val > 1_000_000_000:      # epoch seconds
            return max(0.0, val - clock_wall())
        return max(0.0, val)          # relative seconds
    return None


def _parse_google_retry_delay(data: Any) -> float | None:
    """Extract retryDelay from Google-style error details."""
    if not isinstance(data, dict):
        return None
    details = data.get("error", {}).get("details", [])
    if not isinstance(details, list):
        return None
    for item in details:
        if isinstance(item, dict) and "retryDelay" in item:
            val_str = str(item["retryDelay"]).strip()
            m = _RETRY_DELAY_RE.match(val_str)
            if m:
                with contextlib.suppress(ValueError):
                    return max(0.0, float(m.group(1)))
    return None


def _classify_scope(body_text: str, reset_tokens: bool, retry_after: float | None) -> RateLimitScope:
    lower = body_text.lower()
    if any(k in lower for k in ("daily", "per day", "per-day", "requestsperday", "day_quota", "quota_daily")):
        return "day"
    if reset_tokens or any(k in lower for k in ("token", "tokens", "tpm", "tokensperminute", "tpd")):
        return "tokens"
    if retry_after is not None and retry_after <= 600.0:
        return "minute"
    return "unknown"


def map_http_error(
    status: int,
    headers: Mapping[str, str],
    body: bytes | str | Mapping[str, Any] | None = None,
    clock_wall: Callable[[], float] = time.time,
) -> ProviderError:
    """Translate an HTTP failure into the error the router reasons about."""
    retry_after: float | None = None
    hdrs_lower = {k.lower(): v for k, v in headers.items()}
    if "retry-after" in hdrs_lower:
        retry_after = _parse_retry_after(hdrs_lower["retry-after"], clock_wall)

    reset_token_hdr = False
    for k, v in hdrs_lower.items():
        if k.startswith("x-ratelimit-reset"):
            if "token" in k:
                reset_token_hdr = True
            if retry_after is None:
                retry_after = _parse_reset_header(v, clock_wall)

    body_obj: Any = None
    body_text = ""
    if body is not None:
        if isinstance(body, bytes):
            body_text = body.decode("utf-8", "replace")
        elif isinstance(body, str):
            body_text = body
        elif isinstance(body, Mapping):
            body_obj = body
            body_text = json.dumps(body)

        if body_obj is None and body_text:
            with contextlib.suppress(Exception):
                body_obj = json.loads(body_text)

    if body_obj is not None:
        g_delay = _parse_google_retry_delay(body_obj)
        if g_delay is not None and retry_after is None:
            retry_after = g_delay

    if status == 429:
        scope = _classify_scope(body_text, reset_token_hdr, retry_after)
        return RateLimited(scope=scope, retry_after=retry_after, status=status)
    if status >= 500:
        return ProviderError(retryable=True, retry_after=retry_after, status=status)
    return ProviderError(retryable=False, status=status)  # 401/403 bad key, 404 bad model, other client errors


TRANSIENT = frozenset({502, 503, 504})
RETRY_DELAYS_S = (1.0, 2.0)  # free tiers often answer 503 for a moment; two short retries ride it out


async def _post_once(client: httpx.AsyncClient, url: str, headers: Mapping[str, str], body: Mapping[str, Any],
                     max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async with client.stream("POST", url, headers=dict(headers), json=body) as resp:
        if resp.status_code != 200:
            err_body = await resp.aread()
            raise map_http_error(resp.status_code, resp.headers, err_body)
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
                err_body = await resp.aread()
                raise map_http_error(resp.status_code, resp.headers, err_body)
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
            err_body = await resp.aread()
            raise map_http_error(resp.status_code, resp.headers, err_body)
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ProviderError(retryable=False)
            chunks.append(chunk)
    data = json.loads(b"".join(chunks))
    if not isinstance(data, dict):
        raise ProviderError(retryable=False)
    return data
