"""Install the Laya add-on: its own Python environment and the pinned model, under ~/.lilly/addons/laya.

Nothing here runs inside Lilly's own environment. The package is installed from wheels only (no build scripts run),
and the model is fetched over HTTPS from one host, one file at a time, and kept only if its size and hashes match
the pins. A failed or partial install leaves nothing that looks installed."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import shutil
import subprocess  # nosec B404 - fixed argument lists, never a shell
import sys
import urllib.error
import urllib.request  # nosec B310 - every URL is built here and is https on one host
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lilly.decide.laya_pins import DOWNLOAD_BYTES, FILES, LAYA_VERSION, REPO, REVISION, PinnedFile

HOST = "https://huggingface.co"
FREE_SPACE_NEEDED = 5 * 1024**3       # the model, the package and the packages it needs
CHUNK = 1 << 20
READ_TIMEOUT_S = 60.0
MARKER = "installed.json"
MODEL_DIR = "model"
ENV_DIR = "venv"


class LayaInstallError(Exception):
    """The install stopped. The message is plain words for the person running it."""


@dataclass(frozen=True, slots=True)
class Host:
    system: str      # sys.platform: "darwin", "linux", "win32"
    machine: str     # lower-case architecture: "x86_64", "arm64", ...

    @property
    def old_torch_only(self) -> bool:
        """Intel Macs: PyTorch stopped publishing wheels for them after 2.2.2, which needs Python 3.12 or older,
        NumPy 1 and a transformers release that still supports it."""
        return self.system == "darwin" and self.machine in ("x86_64", "amd64")


def this_host() -> Host:
    return Host(sys.platform, platform.machine().lower())


MIN_PYTHON = (3, 10)                  # what the Laya package asks for
MAX_PYTHON_OLD_TORCH = (3, 12)        # the last Python PyTorch 2.2.2 was built for
OLD_TORCH_PINS = ("numpy<2", "transformers>=4.48,<5")   # 4.48 added ModernBERT; 5 needs a newer PyTorch
PYTHON_NAMES = ("python3.12", "python3.11", "python3.10")


def python_fits(version: tuple[int, int], host: Host) -> bool:
    return MIN_PYTHON <= version and (not host.old_torch_only or version <= MAX_PYTHON_OLD_TORCH)


def _version_of(python: str, run: Callable[..., subprocess.CompletedProcess[str]]) -> tuple[int, int] | None:
    try:
        done = run([python, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                   capture_output=True, text=True, check=False, timeout=20)
        major, minor = done.stdout.split()
        return int(major), int(minor)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def choose_python(host: Host, base_python: str, run: Callable[..., subprocess.CompletedProcess[str]],
                  which: Callable[[str], str | None] = shutil.which) -> str:
    """A Python this computer can run Laya's packages on: Lilly's own when it fits, otherwise another one found
    on the PATH. Says what to install when there is none, before anything large has been downloaded."""
    for candidate in (base_python, *(which(name) for name in PYTHON_NAMES)):
        if candidate and (version := _version_of(candidate, run)) is not None and python_fits(version, host):
            return candidate
    if host.old_torch_only:
        raise LayaInstallError("Laya's machine-learning library supports Intel Macs only up to Python 3.12, and "
                               "no Python 3.10 to 3.12 was found. Install Python 3.12 (python.org or "
                               "'brew install python@3.12'), then try again.")
    raise LayaInstallError("Laya needs Python 3.10 or newer, and none was found.")


@dataclass(frozen=True, slots=True)
class Check:
    """One thing found out about this computer before installing, in plain words."""

    name: str
    ok: bool
    detail: str


SYSTEMS = {"darwin": "macOS", "linux": "Linux", "win32": "Windows"}


def _gb(size: int) -> str:
    return f"{size / 1024**3:.1f} GB"


def _existing(path: Path) -> Path:
    while not path.exists() and path.parent != path:
        path = path.parent
    return path


def preflight(addon: Path, *, host: Host | None = None, base_python: str = sys.executable,
              run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
              which: Callable[[str], str | None] = shutil.which,
              free_bytes: Callable[[Path], int] = lambda p: shutil.disk_usage(p).free) -> list[Check]:
    """Everything that could stop an install, found out without downloading anything. Changes nothing."""
    host = host or this_host()
    system = SYSTEMS.get(host.system)
    computer = Check("This computer", system is not None, (
        f"{system} ({host.machine})" + (". Intel Macs can run Laya only with Python 3.12 or older." if host.old_torch_only
                                        else "") if system else
        f"{host.system} ({host.machine}) is not supported: Laya's machine-learning library is published for "
        "macOS, Linux and Windows."))
    try:
        chosen = choose_python(host, base_python, run, which)
        found = _version_of(chosen, run) or (0, 0)
        python = Check("Python", True, f"Python {found[0]}.{found[1]} at {chosen} will be used for Laya's own environment.")
    except LayaInstallError as exc:
        python = Check("Python", False, str(exc))
    free = free_bytes(_existing(addon))
    disk = Check("Disk space", free >= FREE_SPACE_NEEDED, f"{_gb(free)} free; about {_gb(FREE_SPACE_NEEDED)} is needed "
                 "(the model, the package and the libraries it needs).")
    download = Check("Download", True, f"About {DOWNLOAD_BYTES // 10**6} MB for the model from huggingface.co, plus "
                     "Python packages (several hundred MB more) from pypi.org. This computer must be online and "
                     "able to reach both sites.")
    return [computer, python, disk, download]


def model_dir(addon: Path) -> Path:
    return addon / MODEL_DIR


def python_of(addon: Path) -> Path:
    return addon / ENV_DIR / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def is_installed(addon: Path) -> bool:
    """True only for a finished install of exactly the pinned versions."""
    try:
        data = json.loads((addon / MARKER).read_text())
    except (OSError, ValueError):
        return False
    return (isinstance(data, dict) and data.get("revision") == REVISION and data.get("laya") == LAYA_VERSION
            and python_of(addon).is_file())


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    """Follow redirects (the model is served from a CDN) but never to anything but https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if not newurl.lower().startswith("https://"):
            raise urllib.error.URLError("refused a redirect to a non-https address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


Opener = Callable[[str], AbstractContextManager[Any]]   # opens a URL; the result is read in chunks


def _open(url: str):  # type: ignore[no-untyped-def]
    opener = urllib.request.build_opener(_HttpsOnly)
    return opener.open(urllib.request.Request(url, headers={"User-Agent": "lilly-laya-installer"}),  # noqa: S310
                       timeout=READ_TIMEOUT_S)


def _fetch(pin: PinnedFile, dest: Path, say: Callable[[str], None], opener: Opener) -> None:
    """Download one pinned file to `dest`, keeping it only when it is exactly the file that was reviewed."""
    url = f"{HOST}/{REPO}/resolve/{REVISION}/{pin.path}"
    part = dest.with_name(dest.name + ".part")
    sha256, git = hashlib.sha256(), hashlib.sha1(f"blob {pin.size}\0".encode(), usedforsecurity=False)  # git's format
    got = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with opener(url) as resp, part.open("wb") as out:
            while chunk := resp.read(CHUNK):
                got += len(chunk)
                if got > pin.size:
                    raise LayaInstallError(f"{pin.path} is larger than the reviewed file; stopped")
                sha256.update(chunk)
                git.update(chunk)
                out.write(chunk)
                if pin.size > 10 * CHUNK and (got // CHUNK) % 100 == 0:
                    say(f"  {pin.path}: {got * 100 // pin.size}%")
        if got != pin.size:
            raise LayaInstallError(f"{pin.path} ended early ({got} of {pin.size} bytes)")
        if git.hexdigest() != pin.git_blob:
            raise LayaInstallError(f"{pin.path} is not the reviewed file (git id {git.hexdigest()}); nothing was kept")
        if pin.sha256 and sha256.hexdigest() != pin.sha256:
            raise LayaInstallError(f"{pin.path} is not the reviewed file (sha256 {sha256.hexdigest()}); "
                                   "nothing was kept")
        os.replace(part, dest)
    except OSError as exc:   # URLError and timeouts are OSErrors too
        raise LayaInstallError(f"could not download {pin.path}: {getattr(exc, 'reason', None) or exc}") from exc
    finally:
        part.unlink(missing_ok=True)


def _pip(addon: Path, run: Callable[..., subprocess.CompletedProcess[str]], host: Host) -> None:
    py = str(python_of(addon))
    pins = OLD_TORCH_PINS if host.old_torch_only else ()
    done = run([py, "-m", "pip", "install", "--quiet", "--only-binary=:all:", "--disable-pip-version-check",
                f"laya=={LAYA_VERSION}", *pins], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()[-3:]
        raise LayaInstallError("pip could not install Laya and the packages it needs on this computer: "
                               + " | ".join(tail))


FAILURE_FILE = "laya-last-error.txt"      # beside the add-on, so Settings can say why an install made outside it failed


def _failure_path(addon: Path) -> Path:
    return addon.parent / FAILURE_FILE


def last_failure(addon: Path) -> str | None:
    """Why the last install attempt failed (by the installer, the command or Settings), until one succeeds."""
    try:
        return _failure_path(addon).read_text().strip() or None
    except OSError:
        return None


def install(addon: Path, say: Callable[[str], None] = print, **kwargs: Any) -> None:
    """Install or repair the add-on, remembering why it failed when it does. See `_install`."""
    try:
        _install(addon, say, **kwargs)
    except LayaInstallError as exc:
        with contextlib.suppress(OSError):
            _failure_path(addon).write_text(str(exc)[:500])
        raise
    _failure_path(addon).unlink(missing_ok=True)


def _install(addon: Path, say: Callable[[str], None] = print, *, opener: Opener = _open,
             run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run, base_python: str = sys.executable,
             files: tuple[PinnedFile, ...] = FILES, host: Host | None = None,
             which: Callable[[str], str | None] = shutil.which) -> None:
    """Install or repair the add-on. Raises LayaInstallError with a plain reason; leaves no marker on failure.
    Everything that could rule this computer out is checked before the large download starts."""
    host = host or this_host()
    addon.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if shutil.disk_usage(addon.parent).free < FREE_SPACE_NEEDED:
        raise LayaInstallError("there is not enough free disk space (about 5 GB is needed)")
    base = choose_python(host, base_python, run, which)
    addon.mkdir(mode=0o700, exist_ok=True)
    (addon / MARKER).unlink(missing_ok=True)
    say(f"Setting up Laya's own Python environment (the model is about {DOWNLOAD_BYTES // 10**6} MB).")
    have = python_of(addon)
    if have.is_file() and ((v := _version_of(str(have), run)) is None or not python_fits(v, host)):
        shutil.rmtree(addon / ENV_DIR)      # made by a Python that cannot run it: start again
    if not python_of(addon).is_file():
        made = run([base, "-m", "venv", str(addon / ENV_DIR)], capture_output=True, text=True, check=False)
        if made.returncode != 0:
            raise LayaInstallError("could not create the environment: " + (made.stderr or "").strip()[-200:])
    say("Installing the Laya package (wheels only).")
    _pip(addon, run, host)
    for pin in files:
        target = model_dir(addon) / pin.path
        if target.is_file() and target.stat().st_size == pin.size and _matches(target, pin):
            continue
        say(f"Downloading {pin.path}")
        _fetch(pin, target, say, opener)
    (addon / MARKER).write_text(json.dumps({"revision": REVISION, "laya": LAYA_VERSION, "repo": REPO}))


def _matches(path: Path, pin: PinnedFile) -> bool:
    git = hashlib.sha1(f"blob {pin.size}\0".encode(), usedforsecurity=False)   # git's format, not for security
    sha256 = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            git.update(chunk)
            sha256.update(chunk)
    return git.hexdigest() == pin.git_blob and (pin.sha256 is None or sha256.hexdigest() == pin.sha256)


def remove(addon: Path) -> bool:
    """Delete the add-on completely. False when there was nothing to delete."""
    _failure_path(addon).unlink(missing_ok=True)
    if not addon.exists():
        return False
    shutil.rmtree(addon)
    return True
