"""The Laya add-on as the running app sees it: what is installed, the worker process, and the install job.

Installing downloads about a gigabyte, so it runs in the background, one at a time, with progress lines the
interface can show. Asking for the decider never blocks: it is None until an install has finished."""
from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lilly.decide import laya_install
from lilly.decide.laya_decider import LayaDecider
from lilly.decide.laya_pins import DOWNLOAD_BYTES
from lilly.decide.laya_selftest import Report, self_test
from lilly.domain.errors import ConflictError

log = logging.getLogger("lilly.laya")
MAX_LINES = 30

Installer = Callable[..., None]
Checker = Callable[[Path], list[laya_install.Check]]
Maker = Callable[[Path], LayaDecider | None]


class LayaService:
    def __init__(self, addon: Path, installer: Installer = laya_install.install, *,
                 checker: Checker = laya_install.preflight, maker: Maker = LayaDecider.from_install) -> None:
        self._addon, self._installer, self._checker, self._maker = addon, installer, checker, maker
        self._testing = False
        self._decider: LayaDecider | None = None
        self._stamp: int | None = None            # the marker file's modification time when the decider was made
        self._job: asyncio.Task[None] | None = None
        self._lines: deque[str] = deque(maxlen=MAX_LINES)
        self._error: str | None = None
        self._stop = False

    # ---- the decider ------------------------------------------------------------------------------
    @property
    def decider(self) -> LayaDecider | None:
        """The decider for the current install, or None. Follows the files, so an install finished by this
        service or by `lilly laya install` is picked up without a restart."""
        try:
            stamp: int | None = os.stat(self._addon / laya_install.MARKER).st_mtime_ns
        except OSError:
            stamp = None
        if stamp != self._stamp:
            self._stamp = stamp
            self._retire()
            self._decider = LayaDecider.from_install(self._addon) if stamp is not None else None
        return self._decider

    def _retire(self) -> None:
        if self._decider is not None:
            asyncio.get_running_loop().create_task(self._decider.aclose())
            self._decider = None

    # ---- the interface's view ---------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        installed = laya_install.is_installed(self._addon)
        host = laya_install.this_host()
        installing = self._job is not None and not self._job.done()
        decider = self.decider
        return {"installed": installed, "installing": installing, "progress": list(self._lines),
                "error": self._error or (None if installed else laya_install.last_failure(self._addon)),
                "download_mb": DOWNLOAD_BYTES // 10**6,
                "worker": decider.state if decider is not None else "off",
                "note": ("Intel Macs need Python 3.12 or older for Laya; Lilly looks for one when installing."
                         if host.old_torch_only else None)}

    async def check(self) -> list[laya_install.Check]:
        """What this computer can do, found out without downloading anything."""
        return await asyncio.to_thread(self._checker, self._addon)

    async def test(self) -> Report:
        """Prove the installed model works. It uses a decider of its own, so the live one (and whether Laya is on)
        is untouched, and lets the model go again as soon as it has answered. One test at a time."""
        if self._testing:
            raise ConflictError("A Laya test is already running")
        if not laya_install.is_installed(self._addon) or (decider := self._maker(self._addon)) is None:
            raise ConflictError("Laya is not installed yet")
        self._testing = True
        try:
            return await self_test(decider)
        finally:
            self._testing = False
            await asyncio.shield(decider.aclose())

    # ---- changes ------------------------------------------------------------------------------------
    def install(self) -> None:
        if self._job is not None and not self._job.done():
            raise ConflictError("Laya is already being installed")
        self._error, self._stop = None, False
        self._lines.clear()
        self._job = asyncio.create_task(self._run(), name="lilly-laya-install")

    def _say(self, line: str) -> None:        # called from the install thread
        if self._stop:
            raise laya_install.LayaInstallError("the install was stopped")
        self._lines.append(line)

    async def _run(self) -> None:
        try:
            await asyncio.to_thread(self._installer, self._addon, self._say)
        except laya_install.LayaInstallError as exc:
            self._error = str(exc)
        except Exception:
            log.exception("laya install failed")
            self._error = "Laya could not be installed. Details are in Lilly's log."
        else:
            self._lines.append("Laya is installed.")

    async def remove(self) -> bool:
        if self._job is not None and not self._job.done():
            raise ConflictError("Laya is being installed; wait for that to finish")
        if self._testing:
            raise ConflictError("Laya is being tested; wait for that to finish")
        if self._decider is not None:
            await self._decider.aclose()
            self._decider = None
        self._stamp = None
        self._error = None
        return await asyncio.to_thread(laya_install.remove, self._addon)

    async def aclose(self) -> None:
        self._stop = True
        if self._job is not None and not self._job.done():
            self._job.cancel()
            await asyncio.gather(self._job, return_exceptions=True)
        if self._decider is not None:
            await self._decider.aclose()
            self._decider = None
