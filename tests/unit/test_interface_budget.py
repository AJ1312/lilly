"""The interface stays small and cheap: size budgets for what ships, and glass only where it was agreed."""
from __future__ import annotations

import gzip
import re
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parents[2] / "src" / "lilly" / "web" / "assets"
JS_GZIP_BUDGET = 130_000     # bytes; 1.5.0 shipped ~105 kB
CSS_GZIP_BUDGET = 14_000
GLASS_SURFACES = {".rail", ".dialog", ".toast", ".savebar"}


def one(suffix: str) -> Path:
    found = sorted(ASSETS.glob(f"*{suffix}"))
    if len(found) != 1:
        pytest.fail(f"expected exactly one built {suffix} file in {ASSETS}, found {len(found)}")
    return found[0]


def test_the_shipped_bundles_stay_inside_their_size_budget() -> None:
    assert len(gzip.compress(one(".js").read_bytes())) <= JS_GZIP_BUDGET
    assert len(gzip.compress(one(".css").read_bytes())) <= CSS_GZIP_BUDGET


def test_no_remote_resources_are_loaded_by_the_built_files() -> None:
    for path in (one(".js"), one(".css")):
        text = path.read_text()
        assert not re.search(r"""(?:src|href|url\()\s*=?\s*["']?https?://""", text), path.name


def test_blur_is_used_on_exactly_the_agreed_surfaces_and_can_be_switched_off() -> None:
    css = one(".css").read_text()
    blurred = {sel.strip() for block in re.findall(r"([^{}]+)\{[^{}]*[^-]backdrop-filter:blur", css) for sel in block.split(",")}
    assert blurred == GLASS_SURFACES, blurred
    assert "prefers-reduced-transparency" in css and "prefers-contrast" in css
    assert "@supports" in css
