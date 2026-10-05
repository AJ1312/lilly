"""ModelRouter: the one place that turns "I need a completion" into a call on a real provider.

It applies the pool's choice, falls back on quota and provider failures, keeps breaker and quota
state honest, persists daily usage, and reports when the user's permission is needed.
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from lilly.core.pool import ModelEntry, ProviderPool, build_pool
from lilly.domain.caps import Cap
from lilly.domain.errors import NeedsGrant, NoModelAvailable, ProviderError, QuotaExhausted, WriterBusy
from lilly.domain.grants import GrantStore
from lilly.domain.labels import Label, Mode
from lilly.domain.ports import Completed, CompletionRequest, CompletionResult, KeyStore, Message, Provider
from lilly.domain.settings import Settings
from lilly.providers.factory import build_provider
from lilly.providers.local_gate import LocalGate
from lilly.providers.ollama import OllamaStatus, probe
from lilly.store.db import Database
from lilly.store.ledger import load_usage, save_usage

log = logging.getLogger("lilly.router")
_BAD_KEY_COOLDOWN_S = 900.0


class ModelRouter:
    def __init__(self, settings: Settings, keys: KeyStore, client: httpx.AsyncClient, db: Database,
                 grants: GrantStore, local_client: httpx.AsyncClient | None = None) -> None:
        self._keys, self._client, self._db = keys, client, db
        self._local_client = local_client or client
        self.grants = grants
        self._gate = LocalGate()            # local models take turns and only one stays in memory
        self._providers: dict[str, Provider] = {}
        self._key_present: set[str] = set()
        self.pool: ProviderPool = build_pool(settings)
        self._settings = settings

    # ---- configuration ---------------------------------------------------------
    async def start(self) -> None:
        """Rebuild providers, learn which keys exist, and restore today's quota usage."""
        await self.configure(self._settings)
        usage = load_usage(self._db.reader)
        for e in self.pool.entries:
            if e.daily is not None and e.name in usage:
                e.daily.restore(*usage[e.name])

    async def configure(self, settings: Settings) -> None:
        """Apply new settings. Unchanged models keep their quota counters and breakers."""
        self._settings = settings
        self.pool = build_pool(settings, self.pool)
        self._providers = {s.name: build_provider(s, self._client, self._keys, self._local_client, self._gate,
                                                       lambda: self._settings.limits.local_unload_s) for s in settings.models}
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
            row.update(provider=e.spec.provider, model_id=e.spec.model_id, local=e.spec.local,
                       has_key=self.has_key(e))
        return rows

    # ---- completion ---------------------------------------------------------------
    async def complete(self, req: CompletionRequest, *, need: Cap = Cap.NONE, label: Label = Label.PUBLIC,
                       task_id: str | None = None, payload_hash: str | None = None, mode: Mode = Mode.ASK,
                       pin: str | None = None) -> Completed:
        """Run `req` on the best permitted model, falling back down the list on failure.

        Raises NeedsGrant when a model could take the data with the user's permission, and
        NoModelAvailable when nothing can. A pinned model never falls back.
        """
        if not any(e.spec.enabled and self.has_key(e) for e in self.pool.entries):
            raise NoModelAvailable("No model has an API key yet. Add one in Settings → Models & keys "
                                   "(a free key works), or turn on a local model.")
        skip: set[str] = set()
        last_error: ProviderError | None = None
        while True:
            routing = self.pool.route(need, label, pin=pin, grants=self.grants, task_id=task_id,
                                      payload_hash=payload_hash, mode=mode, skip=frozenset(skip), quick=req.quick,
                                      usable=self.has_key)
            if routing.entry is None:
                if routing.grantable:
                    raise NeedsGrant(list(routing.grantable), int(label))
                if last_error is not None:
                    raise last_error
                raise NoModelAvailable(routing.reason)
            entry = routing.entry
            entry.watch.began()
            try:
                result = await self._call(entry, req)
            except asyncio.CancelledError:
                entry.breaker.abort()
                raise
            except ProviderError as exc:
                self._record_failure(entry, exc)
                last_error = exc
                if pin:
                    raise
                skip.add(entry.name)
                continue
            entry.breaker.success()
            entry.watch.worked()
            entry.last_error = None
            entry.record_use(result.input_tokens, result.output_tokens)
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
            entry.breaker.trip(entry.watch.wait_after_refusal(exc.retry_after))   # do not spend another call finding out again
            entry.last_error = "rate limited by the provider"
        elif not exc.retryable:
            entry.breaker.failure(_BAD_KEY_COOLDOWN_S)
            entry.last_error = f"rejected by the provider (HTTP {exc.status})" if exc.status else "rejected by the provider"
        else:
            entry.breaker.failure(exc.retry_after)
            entry.last_error = "temporarily unavailable"
        log.warning("model %s failed: %s", entry.name, entry.last_error)

    async def _persist_usage(self) -> None:
        usage = {e.name: (e.daily.day, e.daily.used) for e in self.pool.entries if e.daily is not None}
        if not usage:
            return
        try:
            await self._db.write(lambda con: save_usage(con, usage))
        except WriterBusy:
            log.warning("quota usage not saved: database busy")

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
        if not entry.try_begin():
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
