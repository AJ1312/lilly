"""Presets change resource limits and nothing else: they can never widen what Lilly may do."""

from __future__ import annotations

from dataclasses import replace

import pytest

from lilly.domain.browser_policy import BrowserMode, BrowserSettings
from lilly.domain.presets import PRESETS
from lilly.domain.settings import default_settings, parse_settings, settings_to_dict

RESOURCE_KEYS = {
    "limits": {"max_running", "lanes", "local_unload_s"},
    "browser": {"idle_quit_s", "mode"},
    "devbox": {"idle_stop_s", "cpus", "memory_mb", "destroy_after_s"},
}


def loaded() -> object:
    base = default_settings()
    return replace(
        base,
        modules=base.modules | {"browser", "devbox", "computer"},
        file_roots=("/tmp/a",),
        browser=BrowserSettings(mode=BrowserMode.ALLOWLIST, allow_hosts=("example.com",)),
    )


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_a_preset_is_valid_and_changes_only_resource_settings(name: str) -> None:
    before = settings_to_dict(loaded())  # type: ignore[arg-type]
    after = settings_to_dict(PRESETS[name].apply(loaded()))  # type: ignore[arg-type,arg-type]
    assert parse_settings(after)[0] is not None
    for key, value in before.items():
        if key in RESOURCE_KEYS:
            changed = {k for k in value if value[k] != after[key][k]}
            assert changed <= RESOURCE_KEYS[key], f"{name} changed {changed} in {key}"
        else:
            assert after[key] == value, f"{name} changed {key}"


def test_no_preset_loosens_the_browsers_approval_mode() -> None:
    for preset in PRESETS.values():
        mode = preset.apply(loaded()).browser.mode  # type: ignore[attr-defined,arg-type]
        assert mode in (BrowserMode.ALLOWLIST, BrowserMode.ASK_EVERY)  # kept, or tightened, never loosened
    assert PRESETS["careful"].apply(loaded()).browser.mode is BrowserMode.ASK_EVERY  # type: ignore[attr-defined,arg-type]


def test_low_resource_runs_one_thing_at_a_time_and_fast_runs_more() -> None:
    assert PRESETS["low-resource"].apply(default_settings()).limits.max_running == 1
    assert (
        PRESETS["fast"].apply(default_settings()).limits.max_running
        > PRESETS["balanced"].apply(default_settings()).limits.max_running
    )
    assert PRESETS["balanced"].apply(PRESETS["fast"].apply(default_settings())) == default_settings()
