"""`lilly doctor`: check this installation and say what to fix. Changes nothing."""
from __future__ import annotations

import shutil
import sqlite3
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lilly.app.paths import LillyPaths
from lilly.decide import laya_install
from lilly.domain.decisions import laya_kinds
from lilly.domain.settings import load_settings
from lilly.store.connection import open_reader
from lilly.tools.devbox.engines import find_engine

MIN_FREE_MB = 500
MIN_PYTHON = (3, 12)


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str


def _python() -> Check:
    have = sys.version_info[:2]
    return Check("Python", have >= MIN_PYTHON, f"{have[0]}.{have[1]}" + ("" if have >= MIN_PYTHON else f" (needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+)"))


def _home(paths: LillyPaths) -> Check:
    mode = stat.S_IMODE(paths.root.stat().st_mode)
    return Check("Data folder", mode & 0o077 == 0, f"{paths.root}" + ("" if mode & 0o077 == 0 else f" is open to others (mode {mode:o}); run: chmod 700 {paths.root}"))


def _disk(paths: LillyPaths) -> Check:
    free = shutil.disk_usage(paths.root).free // 2**20
    return Check("Free disk", free >= MIN_FREE_MB, f"{free} MB free" + ("" if free >= MIN_FREE_MB else f" (backups and the log need room; keep {MIN_FREE_MB} MB)"))


def _database(paths: LillyPaths) -> Check:
    if not paths.db.exists():
        return Check("Database", True, "not created yet (first start does that)")
    try:
        con = open_reader(paths.db)
        try:
            verdict = str(con.execute("PRAGMA quick_check").fetchone()[0])
        finally:
            con.close()
    except sqlite3.Error as exc:
        return Check("Database", False, f"cannot be read: {exc}")
    return Check("Database", verdict == "ok", "intact" if verdict == "ok" else f"damaged: {verdict}; restore from {paths.backups}")


def _settings(paths: LillyPaths) -> tuple[Check, list[Check]]:
    settings, problems = load_settings(paths.settings)
    head = Check("Settings", not problems, "valid" if not problems else "; ".join(problems))
    extra: list[Check] = []
    missing = [r for r in settings.file_roots if not Path(r).is_dir()]
    if settings.file_roots:
        extra.append(Check("Folders Lilly may use", not missing, "all exist" if not missing else "missing: " + ", ".join(missing)))
    if "devbox" in settings.modules:
        found = find_engine(settings.devbox.runtime)
        extra.append(Check("Container engine", found is not None, found[0] if found else "Docker or Podman is not installed, so the devbox cannot run"))
    return head, extra


def _laya(paths: LillyPaths) -> Check:
    """Laya is an add-on: absent is fine. A broken install, or Laya turned on without one, is not."""
    addon = paths.root / "addons" / "laya"
    turned_on = laya_kinds(load_settings(paths.settings)[0].decisions)
    if laya_install.is_installed(addon):
        return Check("Laya", True, ("installed and on for " + ", ".join(turned_on)) if turned_on
                     else "installed, off (turn it on in Settings → Quick decisions, or 'lilly laya enable')")
    if (addon / laya_install.MARKER).exists():
        return Check("Laya", False, "an install is there but is not the version this Lilly expects, or is "
                     "incomplete; run 'lilly laya install' to repair it, or 'lilly laya remove'")
    if turned_on:
        return Check("Laya", False, "turned on in settings but not installed, so it is skipped; run "
                     "'lilly laya install', or 'lilly laya disable'")
    return Check("Laya", True, "not installed (Lilly works fully without it; 'lilly laya install' sets it up to save tokens, "
                 "'lilly laya check' shows whether this computer can run it)")


def run_checks(paths: LillyPaths, running: Callable[[], bool]) -> list[Check]:
    """Every check, in the order a person would fix them. `running` says whether Lilly answers on its port."""
    head, extra = _settings(paths)
    return [_python(), _home(paths), _disk(paths), _database(paths), head, *extra,
            _laya(paths), Check("Lilly", True, "running" if running() else "not running")]
