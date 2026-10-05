"""Finding, starting and stopping the browser process. Its profile is a new temporary folder each time, so it holds
none of your sign-ins, history or extensions, and it is deleted when the browser quits."""
from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import sys
import tempfile
from pathlib import Path

from lilly.domain.errors import ToolError

START_TIMEOUT_S = 20.0
_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "brave-browser",
          "chrome")
_PLACES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)
FLAGS = ("--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-sync",
         "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--mute-audio",
         "--password-store=basic", "--use-mock-keychain", "--disable-features=Translate,MediaRouter",
         "--remote-allow-origins=http://127.0.0.1")


def find_browser(configured: str = "", environ: dict[str, str] | None = None) -> str:
    """The browser program to drive: the one named in Settings, `$LILLY_CHROME`, or the first Chrome-family browser."""
    env = os.environ if environ is None else environ
    for candidate in (configured, env.get("LILLY_CHROME", "")):
        if candidate:
            if Path(candidate).is_file() and os.access(candidate, os.X_OK):
                return candidate
            raise ToolError(f"the browser '{candidate}' was not found or cannot be run")
    for name in _NAMES:
        if found := shutil.which(name):
            return found
    for place in _PLACES:
        if Path(place).is_file():
            return place
    raise ToolError("no Chrome, Chromium, Edge or Brave was found; install one or set its path in Settings")


class BrowserProcess:
    """One browser in its own process group with a throwaway profile, reached over a local debugging port."""

    def __init__(self, program: str, headless: bool) -> None:
        self._program, self._headless = program, headless
        self._proc: asyncio.subprocess.Process | None = None
        self._profile: str | None = None
        self.endpoint = ""

    async def start(self) -> str:
        """Launch and return the WebSocket address of the browser. Raises ToolError if it does not come up."""
        self._profile = tempfile.mkdtemp(prefix="lilly-browser-")
        args = [f"--user-data-dir={self._profile}", "--remote-debugging-port=0", *FLAGS]
        if self._headless:
            args.append("--headless=new")
        if sys.platform != "win32" and os.geteuid() == 0:
            args.append("--no-sandbox")     # Chrome refuses to run as root otherwise
        env = {k: v for k in ("PATH", "HOME", "LANG", "DISPLAY", "XAUTHORITY", "TMPDIR", "SYSTEMROOT", "TEMP", "TMP",
                              "XDG_RUNTIME_DIR") if (v := os.environ.get(k))}
        kwargs = {"creationflags": 0x200} if sys.platform == "win32" else {"start_new_session": True}
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self._program, *args, "about:blank", stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL, env=env, **kwargs)
        except OSError as exc:
            await self.stop()
            raise ToolError("could not start the browser") from exc
        try:
            self.endpoint = await self._wait_for_port()
        except BaseException:
            await self.stop()
            raise
        return self.endpoint

    async def _wait_for_port(self) -> str:
        assert self._profile is not None and self._proc is not None
        marker = Path(self._profile) / "DevToolsActivePort"
        async with asyncio.timeout(START_TIMEOUT_S):
            while True:
                if self._proc.returncode is not None:
                    raise ToolError("the browser closed straight after starting")
                with contextlib.suppress(OSError, ValueError):
                    lines = marker.read_text().splitlines()
                    if len(lines) >= 2 and lines[0].isdigit() and lines[1].startswith("/devtools/browser/"):
                        return f"ws://127.0.0.1:{int(lines[0])}{lines[1]}"
                await asyncio.sleep(0.05)

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                if sys.platform == "win32":
                    proc.kill()
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), 5)
        profile, self._profile = self._profile, None
        if profile is not None:
            shutil.rmtree(profile, ignore_errors=True)
