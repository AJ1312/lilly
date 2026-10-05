"""The router routes around any failing model, not only ones that raise ProviderError."""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from lilly.domain.errors import ProviderError
from lilly.domain.grants import GrantStore
from lilly.domain.ports import CompletionRequest, CompletionResult, Message, Provider
from lilly.domain.settings import CapacitySettings, ModelSpec, Settings
from lilly.providers.router import ModelRouter
from lilly.store.db import Database
from tests.helpers import MemoryKeyStore

REQ = CompletionRequest((Message("user", "hi"),), 8)


class Broken(Provider):
    name = "broken"

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        raise UnicodeEncodeError("ascii", "kéy", 1, 2, "ordinal not in range")


class Healthy(Provider):
    name = "healthy"

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        return CompletionResult("ok", 1, 1, "stop")


@pytest.fixture
async def router(tmp_path: Path) -> AsyncIterator[ModelRouter]:
    specs = (ModelSpec("bad", "mistral", "m"), ModelSpec("good", "gemini", "m"))
    db = Database(tmp_path / "lilly.db")
    client = httpx.AsyncClient()
    r = ModelRouter(Settings(models=specs), MemoryKeyStore({"mistral": "k", "gemini": "k"}), client, db, GrantStore())
    await r.start()
    r._providers = {"bad": Broken(), "good": Healthy()}
    yield r
    await client.aclose()
    db.close()


async def test_an_unexpected_adapter_error_falls_back_to_the_next_model(router: ModelRouter) -> None:
    done = await router.complete(REQ)
    assert done.model == "good"
    assert router.pool.get("bad").last_error == "temporarily unavailable"  # type: ignore[union-attr]


async def test_a_pinned_model_that_raises_unexpectedly_reports_a_provider_error(router: ModelRouter) -> None:
    with pytest.raises(ProviderError):
        await router.complete(REQ, pin="bad")


async def test_testing_a_model_that_raises_unexpectedly_reports_and_releases_the_breaker(router: ModelRouter) -> None:
    out = await router.test("bad")
    assert out["ok"] is False
    assert router.pool.get("bad").breaker.state != "half-open"  # type: ignore[union-attr]


async def test_with_no_key_at_all_the_error_says_to_add_one(tmp_path: Path) -> None:
    from lilly.domain.errors import NoModelAvailable
    db = Database(tmp_path / "lilly.db")
    client = httpx.AsyncClient()
    r = ModelRouter(Settings(models=(ModelSpec("m", "mistral", "m"),)), MemoryKeyStore({}), client, db, GrantStore())
    await r.start()
    try:
        with pytest.raises(NoModelAvailable, match="Settings → Models & keys"):
            await r.complete(REQ)
    finally:
        await client.aclose()
        db.close()


async def test_a_refusal_for_rate_stops_that_model_being_tried_again_and_teaches_its_limit(tmp_path: Path) -> None:
    from lilly.domain.errors import QuotaExhausted

    class Limited(Provider):
        name = "limited"
        calls = 0

        async def complete(self, req: CompletionRequest) -> CompletionResult:
            Limited.calls += 1
            if Limited.calls > 3:
                raise QuotaExhausted(retryable=False, retry_after=20.0, status=429)
            return CompletionResult("ok", 1, 1, "stop")

    db = Database(tmp_path / "lilly.db")
    client = httpx.AsyncClient()
    r = ModelRouter(Settings(models=(ModelSpec("a", "mistral", "m"), ModelSpec("b", "gemini", "m")), capacity=CapacitySettings(spread="ordered")),
                    MemoryKeyStore({"mistral": "k", "gemini": "k"}), client, db, GrantStore())
    await r.start()
    r._providers = {"a": Limited(), "b": Healthy()}
    try:
        for _ in range(3):
            assert (await r.complete(REQ)).model == "a"
        assert (await r.complete(REQ)).model == "b"            # a refused: b answered
        assert (await r.complete(REQ)).model == "b"
        assert Limited.calls == 4                              # a was not asked again while it was told to wait
        row = next(x for x in r.status() if x["name"] == "a")
        assert row["suggested_rpm"] == 2                       # three worked in the minute: 90% of that, rounded down
    finally:
        await client.aclose()
        db.close()
