"""The model pool: the user's ordered models, with rate limits, daily quotas and circuit breakers.

Selection is deterministic: the first enabled model that fits the capability, the data label,
the user's permissions and its quota wins. Failure state is kept per model.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from lilly.core.limits import CircuitBreaker, DailyQuota, LimitWatch, SlidingWindowLimiter
from lilly.domain.caps import Cap
from lilly.domain.clock import Clock
from lilly.domain.grants import GrantStore, label_access
from lilly.domain.labels import Label, Mode
from lilly.domain.settings import ModelSpec, Settings


@dataclass(slots=True)
class ModelEntry:
    spec: ModelSpec
    minute: SlidingWindowLimiter | None
    daily: DailyQuota | None
    breaker: CircuitBreaker
    last_error: str | None = field(default=None)
    tokens: list[int] = field(default_factory=lambda: [0, 0, 0])      # [calls, tokens in, tokens out] since Lilly started
    watch: LimitWatch = field(default_factory=LimitWatch)             # what the provider's rejections taught us

    # label_access() reads these
    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def caps(self) -> Cap:
        return self.spec.caps

    @property
    def max_label(self) -> Label:
        return self.spec.max_label

    @property
    def local(self) -> bool:
        return self.spec.local

    @property
    def ask_private(self) -> bool:
        return self.spec.private_access == "ask"

    @property
    def trains(self) -> bool:
        return self.spec.trains and not self.spec.local

    def record_use(self, tokens_in: int, tokens_out: int) -> None:
        self.tokens[0] += 1
        self.tokens[1] += tokens_in
        self.tokens[2] += tokens_out

    def try_begin(self) -> bool:
        """Reserve one call against every limit and the breaker, or change nothing."""
        limiters = [lim for lim in (self.minute, self.daily) if lim is not None]
        if not self.breaker.ready() or not all(lim.would_allow() for lim in limiters):
            return False
        for lim in limiters:
            lim.commit()
        return self.breaker.begin()


@dataclass(frozen=True, slots=True)
class Routing:
    """The outcome of choosing a model: the entry, or why there is none (and who could be asked)."""

    entry: ModelEntry | None
    reason: str
    grantable: tuple[str, ...] = ()


class ProviderPool:
    def __init__(self, entries: list[ModelEntry]) -> None:
        self.entries: tuple[ModelEntry, ...] = tuple(entries)

    def get(self, name: str) -> ModelEntry | None:
        return next((e for e in self.entries if e.name == name), None)

    def route(self, need: Cap = Cap.NONE, label: Label = Label.PUBLIC, *, pin: str | None = None,
              grants: GrantStore | None = None, task_id: str | None = None, payload_hash: str | None = None,
              mode: Mode = Mode.ASK, skip: frozenset[str] = frozenset(), quick: bool = False,
              usable: Callable[[ModelEntry], bool] = lambda e: True) -> Routing:
        """Pick a model or say why not. A pinned model is never replaced silently."""
        candidates = [e for e in self.entries if e.spec.enabled and e.name not in skip and usable(e)]
        if pin:
            only = next((e for e in candidates if e.name == pin), None)
            if only is None:
                return Routing(None, f"pinned model {pin!r} is unavailable")
            candidates = [only]
        if quick:       # quick models first; the rest keep their order, so nothing is lost if they are down
            candidates.sort(key=lambda e: not e.spec.quick)
        grantable: list[str] = []
        for e in candidates:
            if (e.caps & need) != need:
                continue
            ok, grant = label_access(e, label, grants, task_id, payload_hash, mode)
            if not ok:
                if e.max_label < label and e.ask_private and mode is not Mode.LOCKED \
                        and not (label is Label.SECRET and not e.local) and (mode is Mode.ASK or e.trains):
                    grantable.append(e.name)
                continue
            if e.try_begin():
                if grant and grants:
                    grants.consume(grant)
                return Routing(e, "ok")
        if grantable:
            return Routing(None, "needs permission: " + ", ".join(grantable), tuple(grantable))
        if label >= Label.PERSONAL:
            return Routing(None, "no model may see this data: enable a local model or allow a model to ask")
        return Routing(None, "every model is busy, over quota or down: try again shortly")

    def snapshot(self) -> list[dict[str, object]]:
        """Live quota and breaker state for the Models screen."""
        out: list[dict[str, object]] = []
        for e in self.entries:
            out.append({
                "name": e.name, "enabled": e.spec.enabled, "breaker": e.breaker.state,
                "minute_used": e.minute.used if e.minute else None, "rpm": e.spec.rpm,
                "day_used": e.daily.used if e.daily else None, "rpd": e.spec.rpd,
                "resets_in_s": round(e.daily.seconds_to_reset()) if e.daily else None,
                "last_error": e.last_error, "calls": e.tokens[0], "tokens_in": e.tokens[1],
                "tokens_out": e.tokens[2],
                "suggested_rpm": _lower(e.watch.rpm, e.spec.rpm), "suggested_rpd": _lower(e.watch.rpd, e.spec.rpd),
            })
        return out


def _lower(learned: int | None, set_by_owner: int | None) -> int | None:
    """A learned limit is worth showing only while the owner has not set one that is already as low."""
    return learned if learned is not None and (set_by_owner is None or set_by_owner > learned) else None


def _entry(spec: ModelSpec, kept: ModelEntry | None, clock: Clock) -> ModelEntry:
    """The entry for `spec`, reusing from `kept` each counter whose own limit is unchanged and the breaker while
    it is still the same endpoint."""
    if kept is None or (kept.spec.provider, kept.spec.model_id, kept.spec.base_url, kept.spec.key_ref) != (
            spec.provider, spec.model_id, spec.base_url, spec.key_ref):
        return ModelEntry(spec, SlidingWindowLimiter(spec.rpm, 60.0, clock) if spec.rpm else None,
                          DailyQuota(spec.rpd, spec.tz) if spec.rpd else None, CircuitBreaker(clock=clock))
    minute = kept.minute if kept.spec.rpm == spec.rpm else SlidingWindowLimiter(spec.rpm, 60.0, clock) if spec.rpm else None
    daily = kept.daily if (kept.spec.rpd, kept.spec.tz) == (spec.rpd, spec.tz) else \
        DailyQuota(spec.rpd, spec.tz) if spec.rpd else None
    return ModelEntry(spec, minute, daily, kept.breaker, kept.last_error, kept.tokens, kept.watch)


def build_pool(settings: Settings, previous: ProviderPool | None = None, clock: Clock = time.monotonic) -> ProviderPool:
    """Build the pool in the user's order. Editing settings never resets a limit that was not itself edited."""
    old = {e.name: e for e in previous.entries} if previous else {}
    return ProviderPool([_entry(spec, old.get(spec.name), clock) for spec in settings.models])
