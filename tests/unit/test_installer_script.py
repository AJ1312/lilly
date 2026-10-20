"""install.sh: Laya is part of the install by default, can be skipped, and never makes the install fail."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "install.sh"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, check=False, timeout=20)


def test_the_script_is_valid_bash() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0


def test_help_offers_the_skip_flag_and_points_at_the_guided_setup() -> None:
    done = run("--help")
    assert done.returncode == 0
    assert "--no-laya" in done.stdout and "--laya" not in done.stdout.replace("--no-laya", "")
    assert "Settings → Quick decisions" in done.stdout and "lilly laya check" in done.stdout


def test_an_unknown_option_is_refused() -> None:
    done = run("--laya")
    assert done.returncode == 2 and "Unknown option: --laya" in done.stderr


def test_laya_is_on_by_default_is_checked_first_and_cannot_fail_the_install() -> None:
    text = SCRIPT.read_text()
    assert "\nLAYA=1\n" in text and "--no-laya) LAYA=0" in text
    block = text[text.index('if [ "$LAYA" = 1 ]') : text.index("# 4. macOS")]
    assert (
        block.index("laya check") < block.index("laya install") < block.index("laya test") < block.index("laya enable")
    )
    assert "else" in block and "exit" not in block and "die " not in block  # a failure only prints a note


UNINSTALL_SCRIPT = Path(__file__).resolve().parents[2] / "uninstall.sh"


def test_uninstall_script_is_valid_bash() -> None:
    assert subprocess.run(["bash", "-n", str(UNINSTALL_SCRIPT)], check=False).returncode == 0


def test_uninstall_script_preserves_data_by_default(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "marker.txt").write_text("app")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    symlink = bin_dir / "lilly"
    symlink.symlink_to(app_dir / "marker.txt")

    home_dir = tmp_path / "lilly_home"
    home_dir.mkdir()
    (home_dir / "data.db").write_text("precious user data")

    env = {
        "PATH": subprocess.os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "LILLY_APP_DIR": str(app_dir),
        "LILLY_BIN_DIR": str(bin_dir),
        "LILLY_HOME": str(home_dir),
    }

    res = subprocess.run(
        ["bash", str(UNINSTALL_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert not app_dir.exists(), "App directory should be removed"
    assert not symlink.exists(), "Symlink should be removed"
    assert home_dir.exists(), "User data directory must be preserved by default"
    assert (home_dir / "data.db").read_text() == "precious user data"
    assert "Your data is still in" in res.stdout


def test_uninstall_script_purges_data_with_flag(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    home_dir = tmp_path / "lilly_home"
    home_dir.mkdir()
    (home_dir / "data.db").write_text("precious user data")

    env = {
        "PATH": subprocess.os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "LILLY_APP_DIR": str(app_dir),
        "LILLY_BIN_DIR": str(tmp_path / "bin"),
        "LILLY_HOME": str(home_dir),
    }

    res = subprocess.run(
        ["bash", str(UNINSTALL_SCRIPT), "--purge-data"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert not app_dir.exists()
    assert not home_dir.exists(), "User data should be purged with --purge-data"
    assert "Lilly and all of its data were removed" in res.stdout
