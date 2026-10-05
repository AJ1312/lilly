"""ModelRouter: the one place that turns "I need a completion" into a call on a real provider.

It applies capacity management, rate limits, daily quotas, circuit breakers,
and reports when the user's permission is needed.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx

from lilly.core.capacity import CallProfile, CapacityManager
from lilly.core.pool import ModelEntry, ProviderPool, build_pool
from lilly.domain.caps import Cap
from lilly.domain.clock import Clock
from lilly.domain.errors import NoModelAvailable, ProviderError, QuotaExhausted, RateLimited, WriterBusy
from lilly.domain.grants import GrantStore
from lilly.domain.labels import Label, Mode
from lilly.domain.ports import Completed, CompletionRequest, CompletionResult, KeyStore, Message, Provider
from lilly.domain.settings import Settings
from lilly.providers.factory import build_provider
from lilly.providers.local_gate import LocalGate
from lilly.providers.ollama import OllamaStatus, probe
from lilly.store.db import Database
from lilly.store.ledger import ModelCallRecord, load_usage, record_model_call, save_usage

log = logging.getLogger("lilly.router")
_BAD_KEY_COOLDOWN_S = 900.0


class ModelRouter:
    def __init__(
        self,
        settings: Settings,
        keys: KeyStore,
        client: httpx.AsyncClient,
        db: Database,
        grants: GrantStore,
        local_client: httpx.AsyncClient | None = None,
        clock: Clock = time.monotonic,
        sleep_fn: Callable[[float], Any] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        on_thought: Callable[[str], None] | None = None,
    ) -> None:
        self._keys, self._client, self._db = keys, client, db
        self._local_client = local_client or client
        self._clock = clock
        self._sleep_fn = sleep_fn
        self._on_event = on_event
        self._on_thought = on_thought
        self.grants = grants
        self._gate = LocalGate()            # local models take turns and only one stays in memory
        self._providers: dict[str, Provider] = {}
        self._key_present: set[str] = set()
        self.pool: ProviderPool = build_pool(settings, clock=clock)
        self._settings = settings
        self.capacity = CapacityManager(
            self.pool,
            lambda: self._settings.capacity,
            clock=self._clock,
            has_key=self.has_key,
            on_event=self._on_event,
            on_thought=self._on_thought,
            sleep_fn=self._sleep_fn,
        )

    # ---- configuration ---------------------------------------------------------
    async def start(self) -> None:
        """Rebuild providers, learn which keys exist, and restore today's quota usage."""
        await self.configure(self._settings)
        usage = load_usage(self._db.reader)
        for e in self.pool.entries:
            if e.name in usage:
                day, count, tokens = usage[e.name]
                if e.daily is not None:
                    e.daily.restore(day, count)
                if e.daily_tokens is not None:
                    e.daily_tokens.restore(day, tokens)

    async def configure(self, settings: Settings) -> None:
        """Apply new settings. Unchanged models keep their quota counters and breakers."""
        self._settings = settings
        self.pool = build_pool(settings, self.pool, clock=self._clock)
        self.capacity.pool = self.pool
        self._providers = {
            s.name: build_provider(
                s,
                self._client,
                self._keys,
                self._local_client,
                self._gate,
                lambda: self._settings.limits.local_unload_s,
            )
            for s in settings.models
        }
        await self.refresh_keys()

    async def refresh_keys(self) -> None:
        refs = {s.key_ref or s.provider for s in self._settings.models if not s.local}
        present = await asyncio.to_thread(lambda: {r for r in refs if self._keys.get(r) is not None})
        self._key_present = present

    def has_key(self, entry: ModelEntry) -> bool:
        return entry.spec.local or (entry.spec.key_ref or entry.spec.provider) in self._key_present

    def status(self) -> list[dict[str, object]]:
        rows = self.pool.snapshot()
        for row, e in zip(rows, self.pool.entries, strict=True):
            row.update(
                provider=e.spec.provider,
                model_id=e.spec.model_id,
                local=e.spec.local,
                has_key=self.has_key(e),
            )
        return rows

    # ---- completion ---------------------------------------------------------------
    async def complete(
        self,
        req: CompletionRequest,
        *,
        need: Cap = Cap.NONE,
        label: Label = Label.PUBLIC,
        task_id: str | None = None,
        payload_hash: str | None = None,
        mode: Mode = Mode.ASK,
        pin: str | None = None,
        role: str = "act",
        tag: str | None = None,
        priority: int = 0,
    ) -> Completed:
        """Run `req` on the best permitted model, falling back down the list on failure.

        Raises NeedsGrant when a model could take the data with the user's permission, and
        NoModelAvailable when nothing can. A pinned model never falls back.
        """
        if not any(e.spec.enabled and self.has_key(e) for e in self.pool.entries):
            raise NoModelAvailable("No model has an API key yet. Add one in Settings → Models & keys "
                                   "(a free key works), or turn on a local model.")
        skip: set[str] = set()
        chars = sum(len(m.content) for m in req.messages)
        cpt = getattr(self._settings.capacity, "chars_per_token", 4.0)
        est_in = math.ceil(chars / max(1.0, cpt))
        est_out = min(req.max_tokens, 1000)
        profile = CallProfile(est_in=est_in, est_out=est_out, role=role, need=need, priority=priority)

        inline_retry_max_s = self._settings.capacity.inline_retry_max_s
        retry_count = 0
        max_inline_retries = 3

        while True:
            max_w = inline_retry_max_s if retry_count > 0 and not pin else None
            lease = await self.capacity.acquire(
                profile,
                label=label,
                mode=mode,
                pin=pin,
                tag=tag or ("quick" if req.quick else None),
                grants=self.grants,
                task_id=task_id,
                payload_hash=payload_hash,
                skip=frozenset(skip),
                max_wait_s=max_w,
            )

            entry = lease.entry
            entry.watch.began()
            call_id = f"mc-{uuid.uuid4().hex[:12]}"
            started = self._clock()
            try:
                result = await self._call(entry, req)
            except RateLimited as exc:
                self.capacity.release(lease, tokens_in=0, tokens_out=0, outcome="rate_limited", error=exc)
                await self._record_call(
                    call_id, task_id, role, entry.name, started,
                    int((self._clock() - started) * 1000), 0, 0,
                    int(lease.waited_s * 1000), "rate_limited",
                )
                retry_count += 1
                if pin and (exc.retry_after or 0) > self._settings.capacity.max_wait_interactive_s:
                    raise
                if retry_count > max_inline_retries and not pin:
                    skip.add(entry.name)
                continue
            except asyncio.CancelledError:
                self.capacity.release(lease, tokens_in=0, tokens_out=0, outcome="cancelled")
                await self._record_call(
                    call_id, task_id, role, entry.name, started,
                    int((self._clock() - started) * 1000), 0, 0,
                    int(lease.waited_s * 1000), "cancelled",
                )
                raise
            except ProviderError as exc:
                self._record_failure(entry, exc)
                self.capacity.release(lease, tokens_in=0, tokens_out=0, outcome="error")
                await self._record_call(
                    call_id, task_id, role, entry.name, started,
                    int((self._clock() - started) * 1000), 0, 0,
                    int(lease.waited_s * 1000), "error",
                )
                if pin:
                    raise
                skip.add(entry.name)
                continue

            # Succeeded
            self.capacity.release(lease, tokens_in=result.input_tokens, tokens_out=result.output_tokens, outcome="ok")
            entry.last_error = None
            await self._record_call(
                call_id, task_id, role, entry.name, started,
                int((self._clock() - started) * 1000),
                result.input_tokens, result.output_tokens,
                int(lease.waited_s * 1000), "ok",
            )
            await self._persist_usage()
            return Completed(result, entry.name)

    async def _call(self, entry: ModelEntry, req: CompletionRequest) -> CompletionResult:
        """One provider call. Anything unexpected an adapter raises becomes a retryable ProviderError,
        so a broken model is routed around like any other failing one."""
        try:
            return await self._providers[entry.name].complete(req)
        except (asyncio.CancelledError, ProviderError):
            raise
        except Exception as exc:
            # only the type is logged: the message of an adapter error may quote the key
            log.error("model %s raised %s", entry.name, type(exc).__name__)
            raise ProviderError(retryable=True) from None

    def _record_failure(self, entry: ModelEntry, exc: ProviderError) -> None:
        if isinstance(exc, QuotaExhausted):
            entry.watch.rejected(exc.retry_after)
            entry.breaker.trip(entry.watch.wait_after_refusal(exc.retry_after))
            entry.last_error = "rate limited by the provider"
        elif not exc.retryable:
            entry.breaker.failure(_BAD_KEY_COOLDOWN_S)
            entry.last_error = f"rejected by the provider (HTTP {exc.status})" if exc.status else "rejected by the provider"
        else:
            entry.breaker.failure(exc.retry_after)
            entry.last_error = "temporarily unavailable"
        log.warning("model %s failed: %s", entry.name, entry.last_error)

    async def _persist_usage(self) -> None:
        usage = {
            e.name: (
                e.daily.day if e.daily else 0,
                e.daily.used if e.daily else 0,
                e.daily_tokens.used if e.daily_tokens else 0,
            )
            for e in self.pool.entries
            if e.daily is not None or e.daily_tokens is not None
        }
        if not usage:
            return
        try:
            await self._db.write(lambda con: save_usage(con, usage))
        except WriterBusy:
            log.warning("quota usage not saved: database busy")

    async def _record_call(
        self,
        call_id: str,
        task_id: str | None,
        role: str | None,
        model: str,
        started_at: float,
        ms: int,
        tokens_in: int,
        tokens_out: int,
        waited_ms: int,
        outcome: str,
    ) -> None:
        record = ModelCallRecord(
            id=call_id,
            task_id=task_id,
            turn=None,
            role=role,
            model=model,
            started_at=started_at,
            ms=ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            waited_ms=waited_ms,
            outcome=outcome,
        )
        try:
            await self._db.write(lambda con: record_model_call(con, record))
        except WriterBusy:
            log.warning("model call record not saved: database busy")

    async def _explain(self, entry: ModelEntry, exc: ProviderError) -> str | None:
        """For a local Ollama model, ask the server what is wrong; otherwise the generic reason."""
        if entry.spec.provider != "ollama":
            return entry.last_error
        return (await probe(self._local_client, entry.spec.base_url, entry.spec.model_id)).message

    async def discover_ollama(self, name: str) -> OllamaStatus | None:
        """What the Ollama server behind model `name` has installed; None when `name` is not an Ollama model."""
        entry = self.pool.get(name)
        if entry is None or entry.spec.provider != "ollama":
            return None
        return await probe(self._local_client, entry.spec.base_url, entry.spec.model_id)

    # ---- testing a model from Settings ------------------------------------------------
    async def test(self, name: str) -> dict[str, object]:
        """Make one tiny real call so the user learns whether the key and model id work."""
        entry = self.pool.get(name)
        if entry is None:
            return {"ok": False, "error": "unknown model"}
        if not self.has_key(entry):
            return {"ok": False, "error": "no key saved for this model"}
        if not entry.try_begin(8, 8):
            return {"ok": False, "error": "over its configured rate or quota limit"}
        started = time.monotonic()
        try:
            await self._call(entry, CompletionRequest(
                (Message("user", "Reply with the single word: ok"),), 8, deadline_s=20.0))
        except asyncio.CancelledError:
            entry.breaker.abort()
            raise
        except ProviderError as exc:
            self._record_failure(entry, exc)
            return {"ok": False, "error": await self._explain(entry, exc), "status": exc.status}
        entry.breaker.success()
        entry.last_error = None
        return {"ok": True, "latency_ms": round((time.monotonic() - started) * 1000)}
