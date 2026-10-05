"""Keep the Mac awake while Lilly is working, by holding `caffeinate` only as long as needed."""
from __future__ import annotations

import contextlib
import shutil
import subprocess  # nosec B404 - runs the fixed system tool `caffeinate`


class Caffeinate:
    def __init__(self) -> None:
        self._proc: subprocess.Popen[bytes] | None = None

    @property
    def holding(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def sync(self, hold: bool) -> None:
        """Start or stop holding so that it matches `hold`. Does nothing where caffeinate does not exist."""
        if hold and not self.holding:
            binary = shutil.which("caffeinate")
            if binary:
                with contextlib.suppress(OSError):
                    self._proc = subprocess.Popen([binary, "-i", "-s"], stdout=subprocess.DEVNULL,  # nosec B603
                                                  stderr=subprocess.DEVNULL)
        elif not hold:
            self.release()

    def release(self) -> None:
        if self._proc is not None:
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                self._proc.terminate()
                self._proc.wait(timeout=2.0)
            self._proc = None
