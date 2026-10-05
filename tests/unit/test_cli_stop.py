"""`lilly stop` waits for the server to exit and never signals a process that is not Lilly."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from lilly.app.paths import init_paths
from lilly.daemon import cli
from lilly.daemon.main import pid_file

# a stand-in whose command line carries "lilly" and which needs a moment to shut down
SERVER = "import signal,sys,time\nsignal.signal(signal.SIGTERM, lambda *a: (time.sleep(0.5), sys.exit(0)))\nwhile True: time.sleep(0.1)\n"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LILLY_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def _spawn(name: str) -> subprocess.Popen[bytes]:
    p = subprocess.Popen([sys.executable, "-c", SERVER, name])
    time.sleep(0.3)         # let it install its handler
    return p


def test_stop_returns_only_after_the_process_has_exited(home: Path) -> None:
    p = _spawn("lilly")
    pid_file(init_paths()).write_text(str(p.pid))
    reaper = psutil.Process(p.pid)
    try:
        assert cli.cmd_stop(argparse.Namespace()) == 0
        p.wait(timeout=0)       # already gone: stop waited for it
        assert not reaper.is_running() or reaper.status() == psutil.STATUS_ZOMBIE
    finally:
        p.kill()
        p.wait()


def test_a_stale_pid_that_belongs_to_something_else_is_not_signalled(home: Path) -> None:
    p = _spawn("unrelated")
    pid_file(init_paths()).write_text(str(p.pid))
    try:
        assert cli.cmd_stop(argparse.Namespace()) == 1
        assert p.poll() is None
        assert not pid_file(init_paths()).exists()
    finally:
        p.kill()
        p.wait()


def test_no_pid_file_means_not_running(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.cmd_stop(argparse.Namespace()) == 1
    assert "not running" in capsys.readouterr().out
