"""Start Lilly at login on macOS, as a launchd LaunchAgent. Nothing here runs on other systems."""
from __future__ import annotations

import os
import plistlib
import subprocess  # nosec B404 - runs the fixed system tool `launchctl`
import sys
from pathlib import Path

from lilly.app.paths import LillyPaths
from lilly.domain.errors import ConfigurationError

LABEL = "app.lilly.agent"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def build_plist(paths: LillyPaths, port: int, python: str = sys.executable) -> bytes:
    """The LaunchAgent definition: run at login, restart if it exits, log to Lilly's own log folder."""
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [python, "-m", "lilly", "run", "--port", str(port)],
        "EnvironmentVariables": {"LILLY_HOME": str(paths.root), "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"},
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "StandardOutPath": str(paths.log / "service.out.log"),
        "StandardErrorPath": str(paths.log / "service.err.log"),
    })


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)  # nosec B603 B607


def _require_macos() -> None:
    if sys.platform != "darwin":
        raise ConfigurationError("starting at login is only available on macOS")


def install(paths: LillyPaths, port: int) -> Path:
    _require_macos()
    target = plist_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(build_plist(paths, port))
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", domain, str(target))  # replace a previous version quietly
    result = _launchctl("bootstrap", domain, str(target))
    if result.returncode != 0:
        raise ConfigurationError(f"launchctl could not load Lilly: {result.stderr.strip() or result.stdout.strip()}")
    return target


def uninstall() -> bool:
    """Remove the LaunchAgent. Returns False when it was not installed."""
    _require_macos()
    target = plist_path()
    if not target.exists():
        return False
    _launchctl("bootout", f"gui/{os.getuid()}", str(target))
    target.unlink()
    return True
