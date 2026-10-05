"""Rate limit and capacity reproduction script.

Measures baseline behavior in Lilly 1.8.4 and verifies improvements in 2.0:
Scenario A: 24 concurrent calls against 3 models with rpm=5.
Scenario B: 429 response with Retry-After: 2 s.
Scenario C: 30 calls across 3 models in list order (load spread).
"""
from __future__ import annotations

import asyncio
import tempfile
import time
from collections import Counter
from pathlib import Path

import httpx
from tests.helpers import MemoryKeyStore

from lilly.domain.grants import GrantStore
from lilly.domain.ports import CompletionRequest, Message
from lilly.domain.settings import ModelSpec, Settings
from lilly.providers.router import ModelRouter
from lilly.store.db import Database

REQ = CompletionRequest((Message("user", "hello"),), 10)


def ok_response() -> httpx.Response:
    body = {
        "id": "chatcmpl-test",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    return httpx.Response(200, json=body)


def rate_limit_response(retry_after: str = "2") -> httpx.Response:
    body = {
        "error": {
            "message": f"Rate limit exceeded. Retry in {retry_after} s",
            "type": "rate_limit_error",
            "code": "rate_limit_exceeded",
        }
    }
    return httpx.Response(429, headers={"Retry-After": retry_after}, json=body)


async def run_scenario_a() -> dict[str, object]:
    """Scenario A: 24 calls issued at once by 12 concurrent callers against 3 providers each with rpm=5."""
    with tempfile.TemporaryDirectory() as td:
        specs = (
            ModelSpec("model-a", "mistral", "m1", rpm=5),
            ModelSpec("model-b", "mistral", "m2", rpm=5),
            ModelSpec("model-c", "mistral", "m3", rpm=5),
        )
        keys = MemoryKeyStore({"mistral": "key-123"})
        calls_per_model: Counter[str] = Counter()

        def handle_request(request: httpx.Request) -> httpx.Response:
            return ok_response()

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
        db = Database(Path(td) / "test.db")
        settings = Settings(models=specs)
        router = ModelRouter(settings, keys, client, db, GrantStore())
        await router.start()

        completed = 0
        failed = 0
        exceptions: list[str] = []
        began = time.monotonic()

        async def worker(caller_id: int) -> None:
            nonlocal completed, failed
            for _ in range(2):
                try:
                    res = await router.complete(REQ)
                    completed += 1
                    calls_per_model[res.model] += 1
                except Exception as exc:
                    failed += 1
                    exceptions.append(f"{type(exc).__name__}: {exc}")

        # 12 concurrent callers each making 2 calls = 24 calls total
        tasks = [asyncio.create_task(worker(i)) for i in range(12)]
        await asyncio.gather(*tasks)
        elapsed = time.monotonic() - began

        await client.aclose()
        db.close()

        return {
            "total_calls": 24,
            "completed": completed,
            "failed": failed,
            "elapsed_s": round(elapsed, 3),
            "distribution": dict(calls_per_model),
            "exceptions": Counter(exceptions),
        }


async def run_scenario_b() -> dict[str, object]:
    """Scenario B: 429 response with Retry-After: 2 s."""
    with tempfile.TemporaryDirectory() as td:
        specs = (ModelSpec("model-rate-limited", "mistral", "m-rl"),)
        keys = MemoryKeyStore({"mistral": "key-123"})

        def handle_request(request: httpx.Request) -> httpx.Response:
            return rate_limit_response("2")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
        db = Database(Path(td) / "test.db")
        settings = Settings(models=specs)
        router = ModelRouter(settings, keys, client, db, GrantStore())
        await router.start()

        began = time.monotonic()
        outcome = "unknown"
        error_msg = ""
        try:
            await router.complete(REQ)
            outcome = "succeeded"
        except Exception as exc:
            outcome = f"{type(exc).__name__}"
            error_msg = str(exc)
        elapsed = time.monotonic() - began

        await client.aclose()
        db.close()

        return {
            "outcome": outcome,
            "error": error_msg,
            "elapsed_s": round(elapsed, 4),
        }


async def run_scenario_c() -> dict[str, object]:
    """Scenario C: 30 calls across 3 models in list order."""
    with tempfile.TemporaryDirectory() as td:
        specs = (
            ModelSpec("model-1", "mistral", "m1"),
            ModelSpec("model-2", "mistral", "m2"),
            ModelSpec("model-3", "mistral", "m3"),
        )
        keys = MemoryKeyStore({"mistral": "key-123"})

        def handle_request(request: httpx.Request) -> httpx.Response:
            return ok_response()

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
        db = Database(Path(td) / "test.db")
        settings = Settings(models=specs)
        router = ModelRouter(settings, keys, client, db, GrantStore())
        await router.start()

        distribution: Counter[str] = Counter()
        for _ in range(30):
            res = await router.complete(REQ)
            distribution[res.model] += 1

        await client.aclose()
        db.close()

        return {
            "total_calls": 30,
            "distribution": dict(distribution),
        }


async def main() -> None:
    print("=== Lilly Rate Limit & Capacity Baseline Reproduction ===")
    print("\nRunning Scenario A (24 calls across 3 providers with rpm=5)...")
    res_a = await run_scenario_a()
    print(f"Scenario A result: completed={res_a['completed']}, failed={res_a['failed']}, elapsed={res_a['elapsed_s']}s")
    print(f"Distribution: {res_a['distribution']}")
    print(f"Exceptions: {dict(res_a['exceptions'])}")

    print("\nRunning Scenario B (Provider answers 429 Retry-After: 2 s)...")
    res_b = await run_scenario_b()
    print(f"Scenario B result: outcome={res_b['outcome']}, elapsed={res_b['elapsed_s']}s")
    print(f"Error: {res_b['error']}")

    print("\nRunning Scenario C (30 calls with 3 models in list order)...")
    res_c = await run_scenario_c()
    print(f"Scenario C distribution: {res_c['distribution']}")


if __name__ == "__main__":
    asyncio.run(main())
