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
    block = text[text.index('if [ "$LAYA" = 1 ]'):text.index("# 4. macOS")]
    assert block.index("laya check") < block.index("laya install") < block.index("laya test") < block.index("laya enable")
    assert "else" in block and "exit" not in block and "die " not in block   # a failure only prints a note
