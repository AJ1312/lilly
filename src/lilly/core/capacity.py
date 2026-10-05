"""Capacity management: a rate limit is a delay, not a failure.

Core layer (Rank 1): owns the wait queue, capacity selection, head-of-queue fairness,
in-flight reservations, and token estimation adjustments.
"""
from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from lilly.core.pool import ModelEntry, ProviderPool
from lilly.domain.caps import Cap
from lilly.domain.clock import Clock
from lilly.domain.errors import NeedsGrant, NoModelAvailable, RateLimited
from lilly.domain.grants import GrantStore, label_access
from lilly.domain.labels import Label, Mode
from lilly.domain.settings import CapacitySettings


@dataclass(frozen=True, slots=True)
class CallProfile:
    est_in: int
    est_out: int
    role: str
    need: Cap
    priority: int  # 0 interactive, 1 background


@dataclass(slots=True)
class Lease:
    entry: ModelEntry
    reserved_in: int
    reserved_out: int
    waited_s: float


@dataclass(frozen=True, slots=True)
class CapacityRow:
    name: str
    lane: int
    tags: tuple[str, ...]
    rpm: int | None
    rpm_used: int | None
    rpd: int | None
    rpd_used: int | None
    tpm: int | None
    tpm_used: int | None
    tpd: int | None
    tpd_used: int | None
    breaker: str
    ready_in_s: float
    resets_in_s: float | None
    queue_length: int
    estimated_tasks_left: int | None


@dataclass(frozen=True, slots=True)
class CapacityMessages:
    wait_thought: str = "All models are busy. Waiting {seconds} s for {model} ({reason})."
    resume_thought: str = "Back to work on {model} after {seconds} s."
    wait_too_long: str = (
        "No model became free within {wait} s. Soonest: {soonest_desc}. "
        "{n} step(s) finished and are kept in this task. Add another key under Settings → Models, "
        "turn on a local model, or try again in {t_soonest}."
    )
    pinned_busy: str = (
        "{model} is pinned for this agent and is at its {limit}. It frees up in {t}. "
        "Lilly will not switch to another model because you pinned this one."
    )


@dataclass(slots=True)
class _Waiter:
    priority: int
    seq: int
    event: asyncio.Event
    task_id: str | None


def format_wait_duration(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        m = s // 60
        rem = s % 60
        return f"{m} min" if rem == 0 else f"{m} min {rem} s"
    h = s // 3600
    rem_m = (s % 3600) // 60
    return f"{h} h" if rem_m == 0 else f"{h} h {rem_m} min"


def _reason_limit_desc(entry: ModelEntry) -> str:
    if entry.daily and not entry.daily.would_allow():
        return "daily limit"
    if entry.daily_tokens and not entry.daily_tokens.would_allow(1):
        return "daily limit"
    if entry.minute_tokens and not entry.minute_tokens.would_allow(1):
        return "per-minute token limit"
    if entry.minute and not entry.minute.would_allow():
        return "per-minute limit"
    if not entry.breaker.ready():
        return "error cooldown"
    return "limit"


def _classify_wait_reason(entry: ModelEntry) -> tuple[str, str]:
    """Returns (reason_code, reason_text) for wait thought."""
    if not entry.breaker.ready():
        return "recovering", "recovering from an error"
    if entry.daily and not entry.daily.would_allow():
        secs = entry.daily.seconds_to_reset()
        h, m = int(secs // 3600), int((secs % 3600) // 60)
        return "daily", f"its daily limit, which resets in {h} h {m} min"
    if entry.daily_tokens and not entry.daily_tokens.would_allow(1):
        secs = entry.daily_tokens.seconds_to_reset()
        h, m = int(secs // 3600), int((secs % 3600) // 60)
        return "daily", f"its daily limit, which resets in {h} h {m} min"
    if entry.minute_tokens and not entry.minute_tokens.would_allow(1):
        return "minute_token", "its per-minute token limit"
    return "minute_request", "its per-minute request limit"


def _calc_utilisation(entry: ModelEntry) -> float:
    ratios: list[float] = []
    if entry.minute and entry.spec.rpm:
        ratios.append(entry.minute.used / float(entry.spec.rpm))
    if entry.minute_tokens and entry.spec.tpm:
        ratios.append(entry.minute_tokens.used / float(entry.spec.tpm))
    if entry.daily and entry.spec.rpd:
        ratios.append(entry.daily.used / float(entry.spec.rpd))
    if entry.daily_tokens and entry.spec.tpd:
        ratios.append(entry.daily_tokens.used / float(entry.spec.tpd))
    return max(ratios) if ratios else 0.0


class CapacityManager:
    """Owns model capacity wait queue, token estimations, and model selection."""

    def __init__(
        self,
        pool: ProviderPool,
        settings: CapacitySettings | Callable[[], CapacitySettings] | None = None,
        clock: Clock = time.monotonic,
        has_key: Callable[[ModelEntry], bool] = lambda e: True,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        on_thought: Callable[[str], None] | None = None,
        sleep_fn: Callable[[float], Any] | None = None,
        messages: CapacityMessages | None = None,
    ) -> None:
        self.pool = pool
        self._settings_source = settings if settings is not None else CapacitySettings()
        self._clock = clock
        self._has_key = has_key
        self._on_event = on_event
        self._on_thought = on_thought
        self._sleep_fn = sleep_fn
        self.messages = messages if messages is not None else CapacityMessages()
        self._waiters: list[_Waiter] = []
        self._seq: int = 0

    @property
    def settings(self) -> CapacitySettings:
        return self._settings_source() if callable(self._settings_source) else self._settings_source

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _remove_waiter(self, waiter: _Waiter) -> None:
        if waiter in self._waiters:
            self._waiters.remove(waiter)
        if self._waiters:
            self._waiters[0].event.set()

    def wake_all(self) -> None:
        """Wake all waiting waiters (e.g. on clock advance or settings change)."""
        for w in self._waiters:
            w.event.set()

    async def acquire(
        self,
        profile: CallProfile,
        *,
        label: Label = Label.PUBLIC,
        mode: Mode = Mode.ASK,
        pin: str | None = None,
        tag: str | None = None,
        grants: GrantStore | None = None,
        task_id: str | None = None,
        payload_hash: str | None = None,
        skip: frozenset[str] = frozenset(),
        max_wait_s: float | None = None,
        steps_finished: int = 0,
    ) -> Lease:
        """Acquire a model slot according to the 7-step capacity algorithm."""
        cap_set = self.settings
        limit_wait = (
            max_wait_s
            if max_wait_s is not None
            else (cap_set.max_wait_interactive_s if profile.priority == 0 else cap_set.max_wait_background_s)
        )

        began = self._clock()
        last_reason_key: tuple[str, str] | None = None
        waiter = _Waiter(
            priority=profile.priority,
            seq=self._next_seq(),
            event=asyncio.Event(),
            task_id=task_id,
        )
        prev_head = self._waiters[0] if self._waiters else None
        # Maintain (priority, seq) ordering: lower priority number (interactive) comes first
        self._waiters.append(waiter)
        self._waiters.sort(key=lambda w: (w.priority, w.seq))
        if prev_head is not None and self._waiters[0] is not prev_head:
            # A higher priority waiter became the new head: wake prev_head so it yields
            prev_head.event.set()

        try:
            while True:
                # Step 5 check: Only head of the queue may take capacity
                if self._waiters[0] is not waiter:
                    timeout_left = max(0.001, limit_wait - (self._clock() - began))
                    try:
                        await asyncio.wait_for(waiter.event.wait(), timeout=min(0.5, timeout_left))
                        waiter.event.clear()
                    except (TimeoutError, asyncio.TimeoutError):
                        pass
                    if self._clock() - began >= limit_wait:
                        raise NoModelAvailable("Timed out waiting in capacity queue")
                    continue

                # We are at head of the queue. Evaluate models.
                now = self._clock()

                # 1. Eligible = enabled, has a key (or local), capability fits, label_access allows, matches pin/tag, not in skip.
                candidates = [
                    e for e in self.pool.entries
                    if e.spec.enabled and self._has_key(e) and e.name not in skip
                ]
                if pin:
                    candidates = [e for e in candidates if e.name == pin]
                if tag:
                    candidates = [e for e in candidates if (e.spec.quick if tag == "quick" else tag in e.spec.tags)]

                grantable: list[str] = []
                eligible: list[tuple[ModelEntry, Any]] = []  # (entry, grant)
                for e in candidates:
                    # Cap.TOOLS is advisory: do not exclude models without it
                    need_clean = profile.need & ~Cap.TOOLS
                    if (e.caps & need_clean) != need_clean:
                        continue
                    ok, grant = label_access(e, label, grants, task_id, payload_hash, mode)
                    if not ok:
                        if (
                            e.max_label < label
                            and e.ask_private
                            and mode is not Mode.LOCKED
                            and not (label is Label.SECRET and not e.local)
                            and (mode is Mode.ASK or e.trains)
                        ):
                            grantable.append(e.name)
                        continue
                    eligible.append((e, grant))

                # 2. Label check
                if not eligible:
                    if grantable:
                        raise NeedsGrant(grantable, int(label))
                    if pin:
                        raise NoModelAvailable(f"pinned model {pin!r} is unavailable")
                    if label >= Label.PERSONAL:
                        raise NoModelAvailable("no model may see this data: enable a local model or allow a model to ask")
                    raise NoModelAvailable("no model is available")

                # 3. For each eligible model compute ready_at
                ready_list: list[tuple[ModelEntry, float, Any, int, int]] = []
                for e, grant in eligible:
                    t = now
                    # Breaker
                    if not e.breaker.ready() and e.breaker._open_until:
                        t = max(t, e.breaker._open_until)
                    # In-flight slots
                    if e.inflight >= cap_set.max_inflight_per_model:
                        t = max(t, now + 1.0)
                    # RPM limit (check owner limit and learned limit if learn_limits)
                    eff_rpm, eff_rpd = e.spec.rpm, e.spec.rpd
                    if cap_set.learn_limits:
                        eff_rpm, eff_rpd = e.watch.soft_limits(e.spec.rpm, e.spec.rpd)
                    if eff_rpm and e.minute:
                        # If learned limit is lower than spec limit, check if used >= eff_rpm
                        if e.minute.used >= eff_rpm or not e.minute.would_allow():
                            t = max(t, now + e.minute.retry_after())

                    # Token estimates corrected by moving ratio
                    est_in = math.ceil(profile.est_in * e.token_ratio)
                    est_out = math.ceil(profile.est_out * e.token_ratio)
                    req_tokens = est_in + est_out

                    # TPM limit
                    if e.spec.tpm and e.minute_tokens:
                        if not e.minute_tokens.would_allow(req_tokens):
                            t = max(t, now + e.minute_tokens.retry_after(req_tokens))

                    # RPD limit
                    if eff_rpd and e.daily:
                        if e.daily.used >= eff_rpd:
                            t = max(t, now + e.daily.seconds_to_reset())

                    # TPD limit
                    if e.spec.tpd and e.daily_tokens:
                        if not e.daily_tokens.would_allow(req_tokens):
                            t = max(t, now + e.daily_tokens.seconds_to_reset())

                    ready_list.append((e, t, grant, est_in, est_out))

                # 4. Take lowest lane with ready_at <= now
                ready_now = [item for item in ready_list if item[1] <= now]
                if ready_now:
                    lowest_lane = min(item[0].spec.lane for item in ready_now)
                    in_lane = [item for item in ready_now if item[0].spec.lane == lowest_lane]
                    if cap_set.spread == "balanced":
                        # Lowest utilisation, tie-breaker total calls, then list order
                        in_lane.sort(key=lambda item: (_calc_utilisation(item[0]), item[0].tokens[0]))
                        winner, _, grant, est_in, est_out = in_lane[0]
                    else:
                        winner, _, grant, est_in, est_out = in_lane[0]

                    # Reserve capacity
                    winner.inflight += 1
                    winner.try_begin(est_in, est_out)
                    if grant and grants:
                        grants.consume(grant)

                    waited_s = now - began
                    if waited_s > 0:
                        if self._on_event:
                            self._on_event("resume", {
                                "waited_ms": int(waited_s * 1000),
                                "model": winner.name,
                            })
                        if self._on_thought:
                            self._on_thought(self.messages.resume_thought.format(
                                model=winner.name,
                                seconds=int(round(waited_s)),
                            ))

                    return Lease(entry=winner, reserved_in=est_in, reserved_out=est_out, waited_s=waited_s)

                # 5. Nothing is ready: check if min(ready_at) - now <= remaining_wait
                min_item = min(ready_list, key=lambda item: item[1])
                soonest_entry, min_ready_at, _, _, _ = min_item
                wait_needed = min_ready_at - now
                elapsed = now - began
                remaining_wait = limit_wait - elapsed

                if wait_needed > remaining_wait or remaining_wait <= 0:
                    # 6. Raise NoModelAvailable with soonest
                    soonest_sorted = sorted(ready_list, key=lambda item: item[1])
                    soonest_tuple = tuple((item[0].name, max(0.0, item[1] - now)) for item in soonest_sorted)
                    if pin:
                        lim_name = _reason_limit_desc(soonest_entry)
                        t_desc = format_wait_duration(wait_needed)
                        msg = self.messages.pinned_busy.format(model=pin, limit=lim_name, t=t_desc)
                    else:
                        desc_parts = [f"{name} in {format_wait_duration(sec)}" for name, sec in soonest_tuple[:2]]
                        soonest_desc = "; ".join(desc_parts)
                        t_soonest = format_wait_duration(soonest_tuple[0][1]) if soonest_tuple else "a moment"
                        msg = self.messages.wait_too_long.format(
                            wait=int(round(limit_wait)),
                            soonest_desc=soonest_desc,
                            n=steps_finished,
                            t_soonest=t_soonest,
                        )
                    raise NoModelAvailable(msg, soonest=soonest_tuple)

                # Emit wait event if reason changed
                reason_code, reason_text = _classify_wait_reason(soonest_entry)
                curr_key = (soonest_entry.name, reason_code)
                if curr_key != last_reason_key:
                    last_reason_key = curr_key
                    if self._on_event:
                        self._on_event("wait", {
                            "model": soonest_entry.name,
                            "reason": reason_code,
                            "scope": reason_code,
                            "seconds": round(wait_needed, 1),
                            "until": round(min_ready_at, 2),
                        })
                    if self._on_thought:
                        self._on_thought(self.messages.wait_thought.format(
                            seconds=int(round(wait_needed)),
                            model=soonest_entry.name,
                            reason=reason_text,
                        ))

                # Sleep until min_ready_at or woken
                is_inflight_only = all(e.inflight >= cap_set.max_inflight_per_model for e, _ in eligible)
                sleep_dur = min(wait_needed, remaining_wait)
                try:
                    await asyncio.wait_for(waiter.event.wait(), timeout=max(0.001, sleep_dur) if not self._sleep_fn else 0.05)
                    waiter.event.clear()
                except (TimeoutError, asyncio.TimeoutError):
                    if self._sleep_fn and not is_inflight_only:
                        await self._sleep_fn(sleep_dur)

        finally:
            self._remove_waiter(waiter)

    def release(
        self,
        lease: Lease,
        *,
        tokens_in: int = 0,
        tokens_out: int = 0,
        outcome: str = "ok",
        error: RateLimited | None = None,
    ) -> None:
        """Release lease capacity and adjust tokens/circuits."""
        entry = lease.entry
        entry.inflight = max(0, entry.inflight - 1)
        actual_tokens = tokens_in + tokens_out
        reserved_tokens = lease.reserved_in + lease.reserved_out
        diff = actual_tokens - reserved_tokens

        if outcome == "ok":
            entry.breaker.success()
            entry.watch.worked()
            entry.record_use(tokens_in, tokens_out)
            if diff != 0:
                if entry.minute_tokens:
                    entry.minute_tokens.adjust(diff)
                if entry.daily_tokens:
                    entry.daily_tokens.adjust(diff)
            if reserved_tokens > 0 and actual_tokens > 0:
                sample_ratio = actual_tokens / reserved_tokens
                entry.token_ratio = 0.8 * entry.token_ratio + 0.2 * sample_ratio
        elif outcome == "rate_limited" or isinstance(error, RateLimited):
            # 429: does NOT refund request slot
            retry_after = error.retry_after if error else None
            entry.watch.rejected(retry_after)
            cooldown = entry.watch.wait_after_refusal(retry_after)
            entry.breaker.trip(cooldown)
            scope = error.scope if error else "unknown"
            entry.last_error = f"rate limited ({scope})"
            if reserved_tokens > 0:
                if entry.minute_tokens:
                    entry.minute_tokens.adjust(-reserved_tokens)
                if entry.daily_tokens:
                    entry.daily_tokens.adjust(-reserved_tokens)
        elif outcome == "error":
            # 5xx or network: refund request slot
            if entry.minute and entry.minute._ts:
                entry.minute._ts.pop()
            if entry.daily:
                entry.daily._used = max(0, entry.daily._used - 1)
            if reserved_tokens > 0:
                if entry.minute_tokens:
                    entry.minute_tokens.adjust(-reserved_tokens)
                if entry.daily_tokens:
                    entry.daily_tokens.adjust(-reserved_tokens)
            entry.breaker.failure(error.retry_after if error else None)
        elif outcome == "cancelled":
            # Cancelled before request completed: refund everything
            if entry.minute and entry.minute._ts:
                entry.minute._ts.pop()
            if entry.daily:
                entry.daily._used = max(0, entry.daily._used - 1)
            if reserved_tokens > 0:
                if entry.minute_tokens:
                    entry.minute_tokens.adjust(-reserved_tokens)
                if entry.daily_tokens:
                    entry.daily_tokens.adjust(-reserved_tokens)
            entry.breaker.abort()

        # Wake up next waiter
        if self._waiters:
            self._waiters[0].event.set()

    def snapshot(self) -> list[CapacityRow]:
        """Live capacity status across all models."""
        rows: list[CapacityRow] = []
        now = self._clock()
        q_len = len(self._waiters)
        for e in self.pool.entries:
            ready_at = now
            if not e.breaker.ready() and e.breaker._open_until:
                ready_at = max(ready_at, e.breaker._open_until)
            if e.minute and not e.minute.would_allow():
                ready_at = max(ready_at, now + e.minute.retry_after())
            if e.minute_tokens and not e.minute_tokens.would_allow(100):
                ready_at = max(ready_at, now + e.minute_tokens.retry_after(100))
            if e.daily and not e.daily.would_allow():
                ready_at = max(ready_at, now + e.daily.seconds_to_reset())
            if e.daily_tokens and not e.daily_tokens.would_allow(100):
                ready_at = max(ready_at, now + e.daily_tokens.seconds_to_reset())

            ready_in_s = max(0.0, ready_at - now)
            resets_in_s = e.daily.seconds_to_reset() if e.daily else None
            rpm_used = e.minute.used if e.minute else None
            rpd_used = e.daily.used if e.daily else None
            tpm_used = e.minute_tokens.used if e.minute_tokens else None
            tpd_used = e.daily_tokens.used if e.daily_tokens else None

            est_tasks: int | None = None
            if e.spec.rpd:
                calls_left = max(0, e.spec.rpd - (rpd_used or 0))
                est_tasks = calls_left // 5

            rows.append(CapacityRow(
                name=e.name,
                lane=e.spec.lane,
                tags=e.spec.tags,
                rpm=e.spec.rpm,
                rpm_used=rpm_used,
                rpd=e.spec.rpd,
                rpd_used=rpd_used,
                tpm=e.spec.tpm,
                tpm_used=tpm_used,
                tpd=e.spec.tpd,
                tpd_used=tpd_used,
                breaker=e.breaker.state,
                ready_in_s=round(ready_in_s, 2),
                resets_in_s=round(resets_in_s, 1) if resets_in_s else None,
                queue_length=q_len,
                estimated_tasks_left=est_tasks,
            ))
        return rows
