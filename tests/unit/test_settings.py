"""User-edited settings are validated; secrets and unsafe roots are refused."""
from __future__ import annotations

from pathlib import Path

from lilly.domain.settings import default_settings, load_settings, parse_settings, save_settings, settings_to_dict

MODEL = {"name": "m", "provider": "mistral", "model_id": "x"}


def parse(**over: object) -> tuple[object, list[str]]:
    return parse_settings({"models": [MODEL], **over})


def test_defaults_round_trip_through_json_form() -> None:
    parsed, errs = parse_settings(settings_to_dict(default_settings()))
    assert not errs and parsed == default_settings()


def test_secrets_in_settings_are_rejected() -> None:
    _, errs = parse_settings({"models": [{**MODEL, "api_key": "sk-123"}]})
    assert any("secrets must not be stored" in e for e in errs)


def test_remote_models_cannot_have_standing_private_access() -> None:
    _, errs = parse_settings({"models": [{**MODEL, "max_label": "PERSONAL"}]})
    assert any("PUBLIC only" in e for e in errs)


def test_whole_disk_home_and_relative_roots_are_rejected(tmp_path: Path) -> None:
    assert parse(file_roots=["/"])[1]
    assert parse(file_roots=["~"])[1]
    assert parse(file_roots=["relative/folder"])[1]
    assert not parse(file_roots=[str(tmp_path)])[1]


def test_bad_values_are_reported_together() -> None:
    _, errs = parse_settings({"models": [MODEL, MODEL], "modules": ["files", "voice"], "default_mode": "YOLO",
                              "retention_days": -1, "network": {"allowed_hosts": ["a/b"]},
                              "search": {"engine": "searxng"}})
    assert len(errs) >= 6


def test_save_is_atomic_private_and_loads_back(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_settings(path, default_settings())
    assert path.stat().st_mode & 0o777 == 0o600
    loaded, errs = load_settings(path)
    assert not errs and loaded == default_settings()


def test_corrupt_file_falls_back_to_defaults_with_a_message(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    loaded, errs = load_settings(path)
    assert loaded == default_settings() and errs


def test_a_name_with_a_trailing_newline_is_not_a_valid_model_or_host_name() -> None:
    _, errs = parse_settings({"models": [{**MODEL, "name": "m\n"}]})
    assert any("invalid model name" in e for e in errs)
    _, errs = parse_settings({"models": [MODEL], "network": {"allowed_hosts": ["box.example\n"]}})
    assert errs


def test_an_unusable_settings_file_is_kept_beside_the_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"models": [{"name": "nas", "provider": "ollama", "model_id": "m", "local": true, '
                    '"max_label": "PERSONAL", "base_url": "http://nas.example:11434"}]}')
    settings, problems = load_settings(path)
    assert settings == default_settings() and any("private network" in p for p in problems)
    kept = tmp_path / "settings.json.invalid"
    assert "nas.example" in kept.read_text() and (kept.stat().st_mode & 0o777) == 0o600
    path.write_text("not json at all")
    load_settings(path)
    assert "nas.example" in kept.read_text()          # the first copy is never replaced by a worse one


def test_a_valid_file_leaves_nothing_behind(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_settings(path, default_settings())
    assert load_settings(path)[1] == [] and not (tmp_path / "settings.json.invalid").exists()
