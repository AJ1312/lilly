from __future__ import annotations

import json
from pathlib import Path

import pytest

from lilly.app.paths import init_paths
from lilly.daemon import cli, doctor


def results(tmp_path: Path, up: bool = False) -> dict[str, doctor.Check]:
    return {c.name: c for c in doctor.run_checks(init_paths(tmp_path / "home"), lambda: up)}


def test_a_fresh_install_passes(tmp_path: Path) -> None:
    found = results(tmp_path)
    assert all(c.ok for c in found.values()), found
    assert found["Lilly"].detail == "not running" and results(tmp_path, up=True)["Lilly"].detail == "running"


def test_an_open_data_folder_is_reported_with_the_fix(tmp_path: Path) -> None:
    paths = init_paths(tmp_path / "home")
    paths.root.chmod(0o750)
    check = {c.name: c for c in doctor.run_checks(paths, lambda: False)}["Data folder"]
    assert not check.ok and "chmod 700" in check.detail


def test_a_damaged_database_and_bad_settings_are_reported(tmp_path: Path) -> None:
    paths = init_paths(tmp_path / "home")
    paths.db.write_bytes(b"not a database" * 100)
    paths.settings.write_text("{broken")
    found = {c.name: c for c in doctor.run_checks(paths, lambda: False)}
    assert not found["Database"].ok and not found["Settings"].ok


def test_missing_folders_and_engine_are_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = init_paths(tmp_path / "home")
    paths.settings.write_text(json.dumps({"modules": ["files", "devbox"], "file_roots": [str(tmp_path / "gone")]}))
    monkeypatch.setattr(doctor, "find_engine", lambda wanted: None)
    found = {c.name: c for c in doctor.run_checks(paths, lambda: False)}
    assert not found["Folders Lilly may use"].ok and not found["Container engine"].ok


def test_the_command_exits_nonzero_only_when_something_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LILLY_HOME", str(tmp_path / "h"))
    assert cli.main(["doctor", "--port", "1"]) == 0
    assert "Everything checks out." in capsys.readouterr().out
    init_paths(tmp_path / "h").settings.write_text("{broken")
    assert cli.main(["doctor", "--port", "1"]) == 1
    assert "FAIL  Settings" in capsys.readouterr().out


# ---- the optional Laya add-on ---------------------------------------------------------------------------
def laya_line(tmp_path: Path) -> doctor.Check:
    return results(tmp_path)["Laya"]


def install_marker(tmp_path: Path, **marker: str) -> None:
    from lilly.decide import laya_install
    from lilly.decide.laya_pins import LAYA_VERSION, REVISION

    addon = tmp_path / "home" / "addons" / "laya"
    laya_install.python_of(addon).parent.mkdir(parents=True)
    laya_install.python_of(addon).write_text("")
    (addon / laya_install.MARKER).write_text(json.dumps({"revision": REVISION, "laya": LAYA_VERSION, **marker}))


def test_laya_not_being_installed_is_fine_and_says_how_to_start(tmp_path: Path) -> None:
    line = laya_line(tmp_path)
    assert line.ok and "not installed" in line.detail and "works fully without it" in line.detail and "lilly laya check" in line.detail


def test_an_installed_laya_is_reported_as_off_until_it_is_turned_on(tmp_path: Path) -> None:
    install_marker(tmp_path)
    line = laya_line(tmp_path)
    assert line.ok and "installed" in line.detail and "off" in line.detail


def test_an_installed_laya_that_is_on_says_for_which_questions(tmp_path: Path) -> None:
    from dataclasses import replace

    from lilly.domain.decisions import with_laya
    from lilly.domain.settings import default_settings, save_settings

    install_marker(tmp_path)
    paths = init_paths(tmp_path / "home")
    save_settings(paths.settings, replace(default_settings(), decisions=with_laya(default_settings().decisions, True)))
    line = laya_line(tmp_path)
    assert line.ok and "on" in line.detail and "loop" in line.detail and "pick" in line.detail


def test_an_install_of_other_versions_than_this_lilly_expects_is_a_problem_with_the_fix(tmp_path: Path) -> None:
    install_marker(tmp_path, revision="old")
    line = laya_line(tmp_path)
    assert not line.ok and "lilly laya install" in line.detail


def test_laya_turned_on_but_not_installed_is_a_problem(tmp_path: Path) -> None:
    from dataclasses import replace

    from lilly.domain.decisions import with_laya
    from lilly.domain.settings import default_settings, save_settings

    paths = init_paths(tmp_path / "home")
    save_settings(paths.settings, replace(default_settings(), decisions=with_laya(default_settings().decisions, True)))
    line = laya_line(tmp_path)
    assert not line.ok and "not installed" in line.detail and "lilly laya disable" in line.detail
