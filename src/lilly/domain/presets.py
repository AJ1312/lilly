"""Settings presets: one choice that sets how much of the computer Lilly may use.

A preset changes resource limits only (how many things run at once, how long idle parts stay loaded). It can never
widen what Lilly may do: modules, folders, agents, chat apps and the devbox folder are untouched, and the browser's
approval mode can only move to the strictest setting."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from lilly.domain.browser_policy import BrowserMode
from lilly.domain.settings import Settings


@dataclass(frozen=True, slots=True)
class Preset:
    name: str
    summary: str
    apply: Callable[[Settings], Settings]


def _shape(s: Settings, *, running: int, lanes: int, unload: int, browser_idle: int, box_idle: int, box_cpus: float,
           box_mb: int, box_keep: int) -> Settings:
    return replace(
        s,
        limits=replace(s.limits, max_running=running, lanes=lanes, local_unload_s=unload),
        browser=replace(s.browser, idle_quit_s=browser_idle),
        devbox=replace(s.devbox, idle_stop_s=box_idle, cpus=box_cpus, memory_mb=box_mb, destroy_after_s=box_keep))


def _careful(s: Settings) -> Settings:
    quiet = _shape(s, running=2, lanes=1, unload=120, browser_idle=120, box_idle=300, box_cpus=1.0, box_mb=1024, box_keep=43_200)
    return replace(quiet, browser=replace(quiet.browser, mode=BrowserMode.ASK_EVERY))


PRESETS: dict[str, Preset] = {p.name: p for p in (
    Preset("low-resource", "Gentle on a small or busy computer: one task at a time, parts unload quickly.",
           lambda s: _shape(s, running=1, lanes=1, unload=60, browser_idle=60, box_idle=120, box_cpus=0.5, box_mb=512, box_keep=21_600)),
    Preset("balanced", "The defaults.",
           lambda s: _shape(s, running=3, lanes=3, unload=300, browser_idle=300, box_idle=600, box_cpus=1.0, box_mb=1024, box_keep=86_400)),
    Preset("fast", "Fastest answers: more at once, parts stay loaded longer. Uses more memory.",
           lambda s: _shape(s, running=4, lanes=4, unload=900, browser_idle=600, box_idle=1800, box_cpus=2.0, box_mb=2048, box_keep=86_400)),
    Preset("careful", "Slower and stricter: steps run one by one, and every browser action asks you first.", _careful),
)}
