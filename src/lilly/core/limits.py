"""Rate limiter, daily quota and circuit breaker. Clocks are injected."""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from lilly.domain.clock import Clock


class SlidingWindowLimiter:
    """At most `limit` events per `window_s`. Memory bounded by `limit`."""

    def __init__(self, limit: int, window_s: float, clock: Clock = time.monotonic):
        self.limit, self.window_s, self._clock = limit, window_s, clock
        self._ts: deque[float] = deque()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        while self._ts and self._ts[0] <= cutoff:
            self._ts.popleft()

    def would_allow(self) -> bool:
        self._prune(self._clock())
        return len(self._ts) < self.limit

    @property
    def used(self) -> int:
        self._prune(self._clock())
        return len(self._ts)

    def commit(self) -> None:
        self._ts.append(self._clock())

    def retry_after(self) -> float:
        now = self._clock()
        self._prune(now)
        if len(self._ts) < self.limit:
            return 0.0
        return max(0.0, self._ts[0] + self.window_s - now)


class DailyQuota:
    """Per-day counter that resets at local midnight of `tz` (Gemini: Pacific)."""

    def __init__(self, limit: int, tz: str = "America/Los_Angeles",
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.limit, self._zone, self._now = limit, ZoneInfo(tz), now
        self._day = self._today()
        self._used = 0

    def _today(self) -> date:
        return self._now().astimezone(self._zone).date()

    def _roll(self) -> None:
        d = self._today()
        if d != self._day:
            self._day, self._used = d, 0

    def would_allow(self) -> bool:
        self._roll()
        return self._used < self.limit

    def commit(self) -> None:
        self._roll()
        self._used += 1

    @property
    def used(self) -> int:
        self._roll()
        return self._used

    @property
    def day(self) -> int:
        """The current quota day as a date ordinal in the quota's time zone."""
        self._roll()
        return self._day.toordinal()

    def restore(self, day: int, used: int) -> None:
        """Reload a persisted count. Counts from an earlier day are ignored, so a restart never
        resets today's usage and never carries yesterday's over."""
        if day == self._today().toordinal():
            self._day, self._used = date.fromordinal(day), used

    def seconds_to_reset(self) -> float:
        local = self._now().astimezone(self._zone)
        nxt = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(),
                               tzinfo=self._zone)
        return (nxt.astimezone(timezone.utc) - local.astimezone(timezone.utc)).total_seconds()


class LimitWatch:
    """Learns where a provider's limits are from its own rejections, so the owner does not have to look them up.

    It only suggests: a number is never applied by itself. Calls are remembered for a day (bounded), and when the
    provider says "too many requests", the calls that went through just before are what it allows. A long wait
    before trying again means a daily limit, a short one a per-minute limit."""

    DAY_S = 86_400.0
    LONG_WAIT_S = 600.0       # a retry-after longer than this means the daily limit, not the minute's
    MAX_CALLS = 5_000
    MARGIN = 0.9              # suggest a little under what was seen to work

    FIRST_WAIT_S = 5.0        # how long to leave a model alone after a refusal that says nothing about how long
    MAX_WAIT_S = 60.0         # ... doubling with each refusal in a row, up to this

    def __init__(self, clock: Clock = time.monotonic) -> None:
        self._clock = clock
        self._calls: deque[float] = deque(maxlen=self.MAX_CALLS)
        self.rpm: int | None = None
        self.rpd: int | None = None
        self._refused_in_a_row = 0

    def worked(self) -> None:
        self._refused_in_a_row = 0

    def wait_after_refusal(self, retry_after: float | None) -> float:
        """How long to keep calls away from a model that just refused for rate: what the provider said, or when it
        said nothing a short wait that grows only while the refusals keep coming, so a model whose limit has freed
        up is back in use quickly instead of sitting out a whole minute."""
        self._refused_in_a_row += 1
        if retry_after is not None and retry_after > 0:
            return retry_after
        return min(self.MAX_WAIT_S, self.FIRST_WAIT_S * float(2 ** (self._refused_in_a_row - 1)))

    def began(self) -> None:
        self._calls.append(self._clock())

    def _within(self, seconds: float) -> int:
        cutoff = self._clock() - seconds
        return sum(1 for t in self._calls if t > cutoff)

    def rejected(self, retry_after: float | None) -> None:
        """A call was refused for rate. The refused call itself is not counted as one that worked."""
        daily = retry_after is not None and retry_after > self.LONG_WAIT_S
        worked = max(0, self._within(self.DAY_S if daily else 60.0) - 1)
        if worked == 0:
            return
        value = max(1, int(worked * self.MARGIN))
        if daily:
            self.rpd = value if self.rpd is None else min(self.rpd, value)
        else:
            self.rpm = value if self.rpm is None else min(self.rpm, value)

    def soft_limits(self, set_rpm: int | None = None, set_rpd: int | None = None) -> tuple[int | None, int | None]:
        """Learned caps apply only as a lower cap than anything the owner set."""
        eff_rpm = self.rpm if (self.rpm is not None and (set_rpm is None or set_rpm > self.rpm)) else set_rpm
        eff_rpd = self.rpd if (self.rpd is not None and (set_rpd is None or set_rpd > self.rpd)) else set_rpd
        return eff_rpm, eff_rpd


class TokenWindow:
    """At most `limit` tokens per `window_s`. Memory bounded by calls in window."""

    def __init__(self, limit: int, window_s: float = 60.0, clock: Clock = time.monotonic):
        self.limit, self.window_s, self._clock = limit, window_s, clock
        self._items: deque[tuple[float, int]] = deque()
        self._used: int = 0

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        while self._items and self._items[0][0] <= cutoff:
            _, tokens = self._items.popleft()
            self._used = max(0, self._used - tokens)

    def would_allow(self, tokens: int = 0) -> bool:
        self._prune(self._clock())
        return (self._used + tokens) <= self.limit

    @property
    def used(self) -> int:
        self._prune(self._clock())
        return self._used

    def commit(self, tokens: int) -> None:
        now = self._clock()
        self._prune(now)
        self._items.append((now, tokens))
        self._used += tokens

    def adjust(self, tokens_diff: int) -> None:
        """Credit (negative) or debit (positive) difference on release."""
        self._prune(self._clock())
        self._used = max(0, self._used + tokens_diff)
        if self._items and tokens_diff != 0:
            ts, last_tokens = self._items[-1]
            self._items[-1] = (ts, max(0, last_tokens + tokens_diff))

    def retry_after(self, tokens: int = 0) -> float:
        now = self._clock()
        self._prune(now)
        if (self._used + tokens) <= self.limit:
            return 0.0
        if tokens > self.limit:
            return self.window_s
        needed_relief = (self._used + tokens) - self.limit
        freed = 0
        for ts, count in self._items:
            freed += count
            if freed >= needed_relief:
                return max(0.0, ts + self.window_s - now)
        return self.window_s


class DailyTokens:
    """Per-day token counter that resets at local midnight of `tz`."""

    def __init__(self, limit: int, tz: str = "America/Los_Angeles",
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.limit, self._zone, self._now = limit, ZoneInfo(tz), now
        self._day = self._today()
        self._used = 0

    def _today(self) -> date:
        return self._now().astimezone(self._zone).date()

    def _roll(self) -> None:
        d = self._today()
        if d != self._day:
            self._day, self._used = d, 0

    def would_allow(self, tokens: int = 0) -> bool:
        self._roll()
        return (self._used + tokens) <= self.limit

    def commit(self, tokens: int) -> None:
        self._roll()
        self._used += tokens

    def adjust(self, tokens_diff: int) -> None:
        self._roll()
        self._used = max(0, self._used + tokens_diff)

    @property
    def used(self) -> int:
        self._roll()
        return self._used

    @property
    def day(self) -> int:
        self._roll()
        return self._day.toordinal()

    def restore(self, day: int, used: int) -> None:
        if day == self._today().toordinal():
            self._day, self._used = date.fromordinal(day), used

    def seconds_to_reset(self) -> float:
        local = self._now().astimezone(self._zone)
        nxt = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(),
                               tzinfo=self._zone)
        return (nxt.astimezone(timezone.utc) - local.astimezone(timezone.utc)).total_seconds()


def backoff(attempt: int, base: float = 1.0, cap: float = 60.0,
            rand: Callable[[], float] | None = None) -> float:
    """Full jitter exponential backoff."""
    import secrets
    r = rand() if rand is not None else secrets.SystemRandom().random()
    temp = min(cap, base * (2.0 ** attempt))
    return r * temp


class CircuitBreaker:
    """closed -> open (after N failures) -> half-open (one probe) -> closed/open."""

    def __init__(self, threshold: int = 3, cooldown_s: float = 60.0,
                 clock: Clock = time.monotonic):
        self.threshold, self.cooldown_s, self._clock = threshold, cooldown_s, clock
        self._fails = 0
        self._open_until: float | None = None
        self._probing = False

    @property
    def state(self) -> str:
        if self._open_until is None:
            return "closed"
        if self._probing:
            return "half-open"
        return "open" if self._clock() < self._open_until else "half-open"

    def ready(self) -> bool:
        """Pure check: could a call start now?"""
        if self._open_until is None:
            return True
        return self._clock() >= self._open_until and not self._probing

    def begin(self) -> bool:
        if not self.ready():
            return False
        if self._open_until is not None:
            self._probing = True
        return True

    def abort(self) -> None:
        """A probe call was cancelled before it finished: neither success nor failure."""
        self._probing = False

    def success(self) -> None:
        self._fails, self._open_until, self._probing = 0, None, False

    def trip(self, seconds: float) -> None:
        """Stay closed to calls for `seconds`, then let one probe through. For a provider that said how long to wait."""
        self._open_until = self._clock() + max(1.0, seconds)
        self._probing = False

    def failure(self, retry_after: float | None = None) -> None:
        self._fails += 1
        if self._probing or self._fails >= self.threshold:
            self._open_until = self._clock() + max(self.cooldown_s, retry_after or 0.0)
            self._probing = False
