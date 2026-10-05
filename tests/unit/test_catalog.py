"""Tests for provider catalog loader, validation, and settings generation.

CAT-01..04:
- CAT-01: Every entry has source_url, verified_on, confidence
- CAT-02: Unknown fields stay unset
- CAT-03: Starter entries generate settings
- CAT-04: Loader rejects entries without a source
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lilly.domain.errors import ConfigurationError
from lilly.providers.catalog import _parse_entry, default_settings_from_catalog, load_catalog


def test_cat_01_every_entry_has_source_verified_confidence() -> None:
    """CAT-01: Every entry has source_url, verified_on, confidence."""
    entries = load_catalog()
    assert len(entries) >= 5, "Catalog should have at least 5 default providers"
    for e in entries:
        assert e.source_url.startswith("http"), f"Entry {e.id} missing valid source_url: {e.source_url}"
        assert e.verified_on is not None and len(e.verified_on) == 10, f"Entry {e.id} missing verified_on date"
        assert e.confidence in ("documented", "observed", "unknown"), f"Entry {e.id} invalid confidence: {e.confidence}"


def test_cat_02_unknown_fields_stay_unset() -> None:
    """CAT-02: Unknown or unverified fields stay unset/default."""
    raw = {
        "id": "test-custom",
        "provider": "openai",
        "model_id": "test-model",
        "base_url": "https://example.com/v1",
        "source_url": "https://example.com/docs",
        "confidence": "unknown",
        "unrecognized_field_xyz": 12345,
    }
    entry = _parse_entry(raw)
    assert entry.id == "test-custom"
    assert entry.free_tier.rpm is None
    assert entry.free_tier.tpm is None
    assert entry.tools == "unknown"
    assert not hasattr(entry, "unrecognized_field_xyz")


def test_cat_03_starter_entries_generate_settings() -> None:
    """CAT-03: Starter entries generate settings via default_settings_from_catalog."""
    settings = default_settings_from_catalog()
    assert len(settings.models) > 0
    starter_names = {m.name for m in settings.models}
    assert "mistral-small" in starter_names or "gemini-flash" in starter_names
    # Check that settings defaults are reasonable
    for m in settings.models:
        assert m.lane >= 1
        assert m.tools in ("native", "protocol", "none", "unknown")


def test_cat_04_loader_rejects_entries_without_source(tmp_path: Path) -> None:
    """CAT-04: Loader rejects entries without a source."""
    bad_data = [
        {
            "id": "missing-source",
            "provider": "openai",
            "model_id": "bad",
            "base_url": "https://example.com",
            "confidence": "documented",
            # missing source_url
        }
    ]
    bad_file = tmp_path / "bad_catalog.json"
    bad_file.write_text(json.dumps(bad_data), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="missing required source_url"):
        load_catalog(bad_file)
