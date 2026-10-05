"""The `lilly` command."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sqlite3
import subprocess  # nosec B404 - starts Lilly itself in the background
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import TypeVar

import psutil

from lilly import __version__
from lilly.app.paths import LillyPaths, init_paths
from lilly.core.calibration import MIN_LABELLED, calibrate
from lilly.daemon import doctor, service
from lilly.daemon.main import DEFAULT_PORT, HOST, pid_file, serve
from lilly.decide import laya_install, laya_selftest
from lilly.decide.laya_decider import LayaDecider
from lilly.domain.decisions import DEFAULT_MIN_CONFIDENCE, Kind, laya_kinds, with_laya
from lilly.domain.errors import ConfigurationError
from lilly.domain.settings import load_settings, save_settings
from lilly.store import decisions
from lilly.store.connection import open_reader
from lilly.ui.security import Auth

T = TypeVar("T")


def _port(args: argparse.Namespace) -> int:
    return int(args.port or os.environ.get("LILLY_PORT") or DEFAULT_PORT)


# Talk to Lilly directly: a system or corporate HTTP proxy must never sit between this command and 127.0.0.1.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _is_up(port: int) -> bool:
    try:
        with _DIRECT.open(f"http://{HOST}:{port}/healthz", timeout=1.5) as r:  # nosec B310 - fixed local URL
            return bool(json.load(r).get("app") == "lilly")
    except (OSError, ValueError, urllib.error.URLError):
        return False


def _log_tail(path: Path, lines: int = 15) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def _start_in_background(paths: LillyPaths, port: int) -> None:
    """Start Lilly detached and wait until it answers. On failure, say why instead of just where to look."""
    log_file = paths.log / "lilly.out.log"
    with open(log_file, "ab") as out:
        proc = subprocess.Popen(  # nosec B603 - fixed argument list, our own interpreter, no shell
            [sys.executable, "-m", "lilly", "run", "--port", str(port)], stdout=out, stderr=out,
            stdin=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if _is_up(port):
            return
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    else:
        proc.terminate()  # still not answering: do not leave a half-started process behind
    detail = _log_tail(log_file)
    raise ConfigurationError(f"Lilly did not start. Last lines of {log_file}:\n{detail or '(the log is empty)'}")


def cmd_run(args: argparse.Namespace) -> int:
    paths, port = init_paths(), _port(args)
    Auth(paths.token, paths.secret)  # create the access token before anyone needs it
    print(f"Lilly {__version__} is starting on http://{HOST}:{port}   (stop with Ctrl-C)", flush=True)
    print("Open it with `lilly open`.", flush=True)
    asyncio.run(serve(paths, port))
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    paths, port = init_paths(), _port(args)
    if not _is_up(port):
        print("Starting Lilly...")
        _start_in_background(paths, port)
    auth = Auth(paths.token, paths.secret)
    url = f"http://{HOST}:{port}/login?token={auth.token}"
    if not webbrowser.open(url):
        print(f"Open this in your browser:\nhttp://{HOST}:{port}   then paste your access token (`lilly token`).")
    return 0


def cmd_token(args: argparse.Namespace) -> int:
    paths = init_paths()
    print(Auth(paths.token, paths.secret).token)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    port = _port(args)
    up = _is_up(port)
    print(f"Lilly is {'running' if up else 'not running'} on http://{HOST}:{port}")
    return 0 if up else 1


STOP_WAIT_S = 15.0


def _is_lilly(pid: int) -> bool:
    """Whether `pid` is a Lilly server, so a stale pid file can never make us signal an unrelated process."""
    try:
        return any("lilly" in part.lower() for part in psutil.Process(pid).cmdline()[1:])   # not the interpreter path
    except psutil.Error:
        return False


def cmd_stop(args: argparse.Namespace) -> int:
    """Ask the server to stop and wait until it has, so a following `lilly start` finds the port free."""
    pidfile = pid_file(init_paths())
    try:
        pid = int(pidfile.read_text())
    except (FileNotFoundError, ValueError):
        print("Lilly is not running.")
        return 1
    if not _is_lilly(pid):
        pidfile.unlink(missing_ok=True)
        print("Lilly is not running.")
        return 1
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + STOP_WAIT_S
    while time.monotonic() < deadline:
        if not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
            print("Lilly has stopped.")
            return 0
        time.sleep(0.1)
    print(f"Lilly did not stop within {STOP_WAIT_S:.0f} seconds (process {pid}).", file=sys.stderr)
    return 1


def cmd_install_service(args: argparse.Namespace) -> int:
    target = service.install(init_paths(), _port(args))
    print(f"Lilly will now start whenever you log in. ({target})")
    return 0


def cmd_uninstall_service(args: argparse.Namespace) -> int:
    print("Removed the login item." if service.uninstall() else "The login item was not installed.")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    port = _port(args)
    checks = doctor.run_checks(init_paths(), lambda: _is_up(port))
    for c in checks:
        print(f"{'ok  ' if c.ok else 'FAIL'}  {c.name}: {c.detail}")
    bad = sum(not c.ok for c in checks)
    print("Everything checks out." if not bad else f"{bad} problem{'s' if bad > 1 else ''} to fix.")
    return 1 if bad else 0


def _percent(share: float | None) -> str:
    return "n/a" if share is None else f"{share:.0%}"


def _from_log(paths: LillyPaths, read: Callable[[sqlite3.Connection], T]) -> T | None:
    """Read the decision log read-only. None when there is nothing to read yet (no database, or one from before
    the log existed)."""
    try:
        con = open_reader(paths.db)
    except sqlite3.Error:
        return None
    try:
        return read(con)
    except sqlite3.Error:
        return None
    finally:
        con.close()


def cmd_decisions_report(args: argparse.Namespace) -> int:
    rows = _from_log(init_paths(), decisions.summary) or []
    if not rows:
        print("No decisions have been logged yet.")
        return 0
    print(f"{'question':<14}{'decider':<13}{'decisions':>9}{'answered':>10}{'shadow':>8}{'right':>8}   (right: accepted, of those known)")
    for r in rows:
        known = r.accepted + r.corrected
        print(f"{r.kind:<14}{r.decider or '(none)':<13}{r.decisions:>9}{_percent(r.answered / r.decisions):>10}"
              f"{r.shadow:>8}{_percent(r.accepted / known if known else None):>8}   {known} known")
    return 0


def cmd_decisions_calibrate(args: argparse.Namespace) -> int:
    """Suggest a min_confidence for each decider from the outcomes in the log. Reads only; changes nothing."""
    if not 0.0 < args.target <= 1.0:
        raise ConfigurationError("--target must be above 0 and at most 1")
    paths = init_paths()
    samples: dict[tuple[str, str], list[tuple[float, bool]]] = {}
    for kind, decider, confidence, right in (_from_log(paths, decisions.labelled) or []):
        samples.setdefault((kind, decider), []).append((confidence, right))
    if not samples:
        print("No answers with a known outcome yet, so there is nothing to calibrate.")
        return 0
    settings, _ = load_settings(paths.settings)
    for (kind, decider), rows in sorted(samples.items()):
        steps = {s.decider: s.min_confidence for s in settings.decisions.for_kind(Kind(kind)).chain}
        now = steps.get(decider, DEFAULT_MIN_CONFIDENCE[decider])
        c = calibrate(rows, args.target, now)
        head = f"{kind} / {decider}: {c.labelled} answers with a known outcome, min_confidence now {now:.2f}"
        if c.threshold is None:
            why = "too few outcomes yet." if c.labelled < MIN_LABELLED else f"no threshold reaches {args.target:.0%} precision."
            print(f"{head}\n  no suggestion: {why}")
            continue
        print(f"{head}\n  suggested {c.threshold:.2f}: keeps {_percent(c.coverage_after)} of answers "
              f"(now {_percent(c.coverage_before)}), right {_percent(c.precision_after)} of the time "
              f"(now {_percent(c.precision_before)})")
    print("Nothing was changed. Edit decisions.<question>.min_confidence in Settings to apply a suggestion.")
    return 0


def _laya_dir(paths: LillyPaths) -> Path:
    return paths.root / "addons" / "laya"


def cmd_laya_install(args: argparse.Namespace) -> int:
    addon = _laya_dir(init_paths())
    try:
        laya_install.install(addon, lambda line: print(line, flush=True))
    except laya_install.LayaInstallError as exc:
        print(f"Laya was not installed: {exc}\nLilly works the same without it. Run 'lilly laya install' to try again.",
              file=sys.stderr)
        return 1
    print("Laya is installed. Turn it on with 'lilly laya enable'.")
    return 0


def _set_laya(on: bool, port: int = DEFAULT_PORT) -> int:
    paths = init_paths()
    if _is_up(port):    # a running Lilly keeps its own copy of the settings and would write this change away
        raise ConfigurationError("Lilly is running: change this in Settings → Quick decisions, or run 'lilly stop' first")
    if on and not laya_install.is_installed(_laya_dir(paths)):
        raise ConfigurationError("Laya is not installed; run 'lilly laya install' first")
    settings, problems = load_settings(paths.settings)
    if problems:
        raise ConfigurationError("your settings file has problems, so it was not changed: " + "; ".join(problems))
    save_settings(paths.settings, replace(settings, decisions=with_laya(settings.decisions, on)))
    scope = ("loop, instruction and pick-one questions, and watches whether simple questions need tools"
             if on else "every question, the assist checks included")
    print(f"Laya is {'on' if on else 'off'} for {scope}.")
    return 0


def cmd_laya_check(args: argparse.Namespace) -> int:
    found = laya_install.preflight(_laya_dir(init_paths()))
    for c in found:
        print(f"{'ok  ' if c.ok else 'FAIL'}  {c.name}: {c.detail}")
    if all(c.ok for c in found):
        print("This computer can run Laya. Next: 'lilly laya install' (see docs/LAYA.md).")
        return 0
    print("Fix the lines marked FAIL, then run this again. Lilly works fully without Laya.")
    return 1


def cmd_laya_test(args: argparse.Namespace) -> int:
    decider = LayaDecider.from_install(_laya_dir(init_paths()))
    if decider is None:
        raise ConfigurationError("Laya is not installed; run 'lilly laya install' first")
    print("Loading Laya and asking three questions with known answers (the first load can take a minute)...", flush=True)
    report = asyncio.run(_run_self_test(decider))
    for r in report.results:
        print(f"{'ok  ' if r.ok else 'FAIL'}  {r.name}: expected {r.expected}, got {r.got or 'no answer'}"
              + (f" ({r.confidence:.0%} sure)" if r.confidence is not None else "") + f", {r.ms} ms")
    if report.loaded:
        print(f"Laya loaded in {report.load_ms / 1000:.1f} s.")
    if report.ok:
        print("Laya works. This test did not turn it on; use 'lilly laya enable' or Settings → Quick decisions.")
        return 0
    print(report.error)
    return 1


async def _run_self_test(decider: LayaDecider) -> laya_selftest.Report:
    try:
        return await laya_selftest.self_test(decider)
    finally:
        await decider.aclose()


def cmd_laya_status(args: argparse.Namespace) -> int:
    paths = init_paths()
    addon = _laya_dir(paths)
    settings, _ = load_settings(paths.settings)
    chains = laya_kinds(settings.decisions)
    print(f"installed: {'yes' if laya_install.is_installed(addon) else 'no'}")
    print(f"turned on for: {', '.join(chains) if chains else 'nothing'}")
    return 0


def cmd_laya_remove(args: argparse.Namespace) -> int:
    paths = init_paths()
    _set_laya(False, _port(args))
    print("Removed." if laya_install.remove(_laya_dir(paths)) else "Laya was not installed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lilly", description="Lilly: a private AI assistant that runs on your computer.")
    parser.add_argument("--version", action="version", version=f"lilly {__version__}")
    parser.add_argument("--port", type=int, help=f"port for the interface (default {DEFAULT_PORT}, or $LILLY_PORT)")
    commands = parser.add_subparsers(dest="command")
    for name, fn, help_ in (
        ("run", cmd_run, "run Lilly in this terminal (the default)"),
        ("open", cmd_open, "start Lilly if needed and open it, signed in, in your browser"),
        ("token", cmd_token, "print the access token"),
        ("doctor", cmd_doctor, "check this installation and say what to fix"),
        ("status", cmd_status, "say whether Lilly is running"),
        ("stop", cmd_stop, "stop a running Lilly"),
        ("install-service", cmd_install_service, "macOS: start Lilly automatically at login"),
        ("uninstall-service", cmd_uninstall_service, "macOS: stop starting Lilly at login"),
    ):
        sub = commands.add_parser(name, help=help_)
        sub.add_argument("--port", type=int, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        sub.set_defaults(handler=fn)
    decide = commands.add_parser("decisions", help="how the quick deciders have been doing")
    actions = decide.add_subparsers(dest="action", required=True)
    actions.add_parser("report", help="what was asked, answered and right, per question and decider"
                       ).set_defaults(handler=cmd_decisions_report)
    calibrate_cmd = actions.add_parser("calibrate", help="suggest confidence thresholds from the log (changes nothing)")
    calibrate_cmd.add_argument("--target", type=float, default=0.95, help="precision to aim for (default 0.95)")
    calibrate_cmd.set_defaults(handler=cmd_decisions_calibrate)
    laya = commands.add_parser("laya", help="the Laya helper model that saves tokens on small decisions")
    laya_actions = laya.add_subparsers(dest="action", required=True)
    for name, fn, help_ in (("check", cmd_laya_check, "see whether this computer can run Laya (downloads nothing)"),
                            ("test", cmd_laya_test, "load Laya and prove it answers three known questions"),
                            ("install", cmd_laya_install, "download the pinned model into its own environment"),
                            ("enable", lambda a: _set_laya(True, _port(a)), "use Laya for quick decisions (the token-saving shortcut starts watch-only)"),
                            ("disable", lambda a: _set_laya(False, _port(a)), "stop using Laya (keeps the files)"),
                            ("status", cmd_laya_status, "say whether Laya is installed and turned on"),
                            ("remove", cmd_laya_remove, "turn Laya off and delete its files")):
        laya_actions.add_parser(name, help=help_).set_defaults(handler=fn)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", cmd_run)
    try:
        return int(handler(args))
    except ConfigurationError as exc:
        print(f"lilly: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
