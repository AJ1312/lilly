"""`lilly laya ...`: install, turn on and off, status, remove."""
from __future__ import annotations

from pathlib import Path

import pytest

from lilly.daemon import cli
from lilly.daemon.cli import main
from lilly.decide import laya_install
from lilly.domain.settings import load_settings


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LILLY_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def installed(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(laya_install, "is_installed", lambda addon: True)


def test_turning_laya_on_needs_it_installed(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["laya", "enable"]) == 2
    assert "run 'lilly laya install' first" in capsys.readouterr().err


def test_enable_and_disable_change_the_saved_settings(home: Path, monkeypatch: pytest.MonkeyPatch,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    installed(home, monkeypatch)
    assert main(["laya", "enable"]) == 0 and "watches whether simple questions" in capsys.readouterr().out
    settings, problems = load_settings(home / "config" / "settings.json")
    assert problems == [] and "laya" in [s.decider for s in settings.decisions.kinds["instructions"].chain]
    assert main(["laya", "status"]) == 0
    assert "installed: yes" in capsys.readouterr().out
    assert main(["laya", "disable"]) == 0
    assert "assist checks" in capsys.readouterr().out
    settings, _ = load_settings(home / "config" / "settings.json")
    assert all(s.decider != "laya" for k in settings.decisions.kinds.values() for s in k.chain)
    main(["laya", "status"])
    assert "turned on for: nothing" in capsys.readouterr().out


def test_a_settings_file_with_problems_is_not_overwritten(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installed(home, monkeypatch)
    cfg = home / "config"
    cfg.mkdir(parents=True)
    (cfg / "settings.json").write_text('{"modules": "nope"}')
    assert main(["laya", "enable"]) == 2
    assert (cfg / "settings.json").read_text() == '{"modules": "nope"}'


def test_a_failed_install_says_so_plainly_and_exits_nonzero(monkeypatch: pytest.MonkeyPatch,
                                                            capsys: pytest.CaptureFixture[str]) -> None:
    def fail(addon: Path, say: object) -> None:
        raise laya_install.LayaInstallError("could not download model.safetensors: offline")

    monkeypatch.setattr(laya_install, "install", fail)
    assert main(["laya", "install"]) == 1
    err = capsys.readouterr().err
    assert "was not installed" in err and "works the same without it" in err


def test_a_good_install_points_to_the_next_step(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(laya_install, "install", lambda addon, say: say("working"))
    assert main(["laya", "install"]) == 0
    assert "lilly laya enable" in capsys.readouterr().out


def test_remove_deletes_the_files_and_turns_laya_off(home: Path, monkeypatch: pytest.MonkeyPatch,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    addon = home / "addons" / "laya"
    addon.mkdir(parents=True)
    (addon / "x").write_text("1")
    assert main(["laya", "remove"]) == 0
    assert not addon.exists() and "Removed." in capsys.readouterr().out
    assert main(["laya", "remove"]) == 0 and "was not installed" in capsys.readouterr().out
    assert cli._laya_dir(cli.init_paths()) == addon


# ---- check and test --------------------------------------------------------------------------------------
def checks(monkeypatch: pytest.MonkeyPatch, *found: laya_install.Check) -> None:
    monkeypatch.setattr(laya_install, "preflight", lambda addon: list(found))


def test_check_lists_every_finding_and_exits_zero_when_all_is_well(monkeypatch: pytest.MonkeyPatch,
                                                                     capsys: pytest.CaptureFixture[str]) -> None:
    checks(monkeypatch, laya_install.Check("Python", True, "Python 3.12 will be used"),
           laya_install.Check("Disk space", True, "50.0 GB free"))
    assert main(["laya", "check"]) == 0
    out = capsys.readouterr().out
    assert "ok    Python: Python 3.12 will be used" in out and "ok    Disk space" in out and "can run Laya" in out


def test_check_exits_one_and_says_what_to_fix_when_something_fails(monkeypatch: pytest.MonkeyPatch,
                                                                    capsys: pytest.CaptureFixture[str]) -> None:
    checks(monkeypatch, laya_install.Check("Python", False, "Laya needs Python 3.10 or newer, and none was found."))
    assert main(["laya", "check"]) == 1
    out = capsys.readouterr().out
    assert "FAIL  Python: Laya needs Python 3.10" in out and "Fix" in out


def test_test_needs_laya_installed(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["laya", "test"]) == 2
    assert "run 'lilly laya install' first" in capsys.readouterr().err


def test_test_prints_each_answer_and_exits_zero_when_all_are_as_expected(
        home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from lilly.decide.laya_decider import LayaDecider
    from tests.unit.test_laya_decider import decider

    installed(home, monkeypatch)
    monkeypatch.setattr(LayaDecider, "from_install", classmethod(lambda cls, addon: decider()))
    assert main(["laya", "test"]) == 0
    out = capsys.readouterr().out
    assert out.count("ok  ") >= 3 and "loaded in" in out and "Laya works" in out
    assert "did not turn it on" in out


def test_test_exits_one_with_help_when_laya_does_not_start(home: Path, monkeypatch: pytest.MonkeyPatch,
                                                           capsys: pytest.CaptureFixture[str]) -> None:
    from lilly.decide.laya_decider import LayaDecider
    from tests.unit.test_laya_decider import decider

    installed(home, monkeypatch)
    monkeypatch.setattr(LayaDecider, "from_install", classmethod(lambda cls, addon: decider(command=["/nope"])))
    assert main(["laya", "test"]) == 1
    assert "lilly laya install" in capsys.readouterr().out


def test_a_running_lilly_is_not_changed_behind_its_back(home: Path, monkeypatch: pytest.MonkeyPatch,
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    installed(home, monkeypatch)
    monkeypatch.setattr("lilly.daemon.cli._is_up", lambda port: True)
    assert main(["laya", "enable"]) == 2
    err = capsys.readouterr().err
    assert "Lilly is running" in err and "lilly stop" in err and "Settings" in err
    assert not (home / "config" / "settings.json").exists() or "laya" not in (home / "config" / "settings.json").read_text()
