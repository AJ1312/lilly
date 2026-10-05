"""Provider HTTP behaviour: short retries on transient errors, and plain-language failures."""
from __future__ import annotations

import httpx
import pytest

from lilly.domain.errors import ProviderError, QuotaExhausted
from lilly.engine.outcome import describe_provider_error
from lilly.providers.base import post_json


def client(*statuses: int) -> tuple[httpx.AsyncClient, list[int]]:
    seen: list[int] = []
    queue = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        status = queue.pop(0)
        seen.append(status)
        return httpx.Response(status, json={"ok": True} if status == 200 else {})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


async def call(c: httpx.AsyncClient) -> dict[str, object]:
    return await post_json(c, "https://api.test/x", headers={}, body={}, deadline_s=5.0, retry_delays=(0.0, 0.0))


async def test_a_brief_503_is_ridden_out() -> None:
    c, seen = client(503, 503, 200)
    assert await call(c) == {"ok": True} and seen == [503, 503, 200]


async def test_a_persistent_503_fails_after_the_retries() -> None:
    c, seen = client(503, 503, 503)
    with pytest.raises(ProviderError) as info:
        await call(c)
    assert info.value.status == 503 and info.value.retryable and len(seen) == 3


@pytest.mark.parametrize("status", [401, 404, 429])
async def test_client_errors_and_rate_limits_are_not_retried(status: int) -> None:
    c, seen = client(status)
    with pytest.raises(ProviderError):
        await call(c)
    assert seen == [status]


def test_failures_are_explained_with_what_to_do() -> None:
    assert "API key" in describe_provider_error(ProviderError(False, status=401))
    assert "model id" in describe_provider_error(ProviderError(False, status=404))
    assert "rate limited" in describe_provider_error(QuotaExhausted(False, status=429))
    overloaded = describe_provider_error(ProviderError(True, status=503))
    assert "overloaded" in overloaded and "HTTP 503" in overloaded and "another model key" in overloaded
