"""The devbox: a small locked-down container where an agent may run commands and code.

What the box can do is fixed here, in code, and cannot be widened by an agent or a plan:
  - no network at all (so nothing in it can send anything out, and nothing outside can reach it)
  - no Docker or Podman socket, no host paths other than ONE shared folder, no extra privileges (all capabilities
    dropped, no setuid, no new privileges), a read-only root file system with a small scratch area
  - a ceiling on CPU, memory and processes, a time limit on every command, a cap on how much output is kept
  - it starts when a task needs it, stops after a quiet spell and is destroyed after a longer one
Only the numbers in DevboxSettings are the owner's to choose, and only inside the bounds below. These are pure rules;
running the container lives in `lilly.tools.devbox`."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

CONTAINER_NAME = "lilly-devbox"
LABEL = "lilly.devbox=1"
WORK_DIR = "/work"
SCRATCH = "/tmp"                       # nosec B108 - a path inside the container, not on this computer
MAX_OUTPUT_CHARS = 60_000              # the tail of a command's output that is kept
MAX_COMMAND_CHARS = 8_000
DEFAULT_IMAGE = "python:3.12-slim"
IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}(?::[A-Za-z0-9._-]{1,128})?(?:@sha256:[0-9a-f]{64})?$")
BAD_PATH_CHARS = frozenset(",:;\"'`$\\")      # these can change what a mount or a command line means
RELATIVE = re.compile(r"^[A-Za-z0-9._ -]+(?:/[A-Za-z0-9._ -]+){0,8}$")

BOUNDS: dict[str, tuple[float, float]] = {
    "cpus": (0.25, 4.0), "memory_mb": (128, 8192), "pids": (16, 1024),
    "idle_stop_s": (60, 3600), "destroy_after_s": (3600, 604_800), "command_timeout_s": (5, 600),
}
_KEYS = frozenset({"runtime", "image", "shared_folder", *BOUNDS})


class Engine(StrEnum):
    AUTO = "auto"
    DOCKER = "docker"
    PODMAN = "podman"


@dataclass(frozen=True, slots=True)
class DevboxSettings:
    """Off until the `devbox` module is switched on and a shared folder is chosen."""

    runtime: Engine = Engine.AUTO
    image: str = DEFAULT_IMAGE
    shared_folder: str = ""                # the only part of this computer the box can see (and change)
    cpus: float = 1.0
    memory_mb: int = 1024
    pids: int = 256
    idle_stop_s: int = 600                 # stop after this long unused (it starts again on demand)
    destroy_after_s: int = 86_400          # remove after this long unused
    command_timeout_s: int = 120


def parse_devbox(raw: object) -> tuple[DevboxSettings | None, list[str]]:
    if not isinstance(raw, dict):
        return None, ["devbox must be an object"]
    errs = [f"devbox: unknown setting {k!r}" for k in sorted(raw.keys() - _KEYS)]
    d = DevboxSettings()
    try:
        engine = Engine(raw.get("runtime", d.runtime.value))
    except ValueError:
        errs.append("devbox.runtime must be auto, docker or podman")
        engine = d.runtime
    image = raw.get("image", d.image)
    if not isinstance(image, str) or not IMAGE.fullmatch(image):
        errs.append("devbox.image must be an image name such as python:3.12-slim")
    folder = raw.get("shared_folder", d.shared_folder)
    if not isinstance(folder, str):
        errs.append("devbox.shared_folder must be a folder path")
    elif folder and (problem := folder_problem(folder)):
        errs.append(f"devbox.shared_folder {problem}")
    numbers: dict[str, float] = {}
    for key, (lo, hi) in BOUNDS.items():
        v = raw.get(key, getattr(d, key))
        whole = key != "cpus"
        if isinstance(v, bool) or not isinstance(v, int | float) or (whole and v != int(v)) or not lo <= v <= hi:
            errs.append(f"devbox.{key} must be {'a whole number' if whole else 'a number'} from {lo:g} to {hi:g}")
        else:
            numbers[key] = int(v) if whole else float(v)
    if errs:
        return None, errs
    return DevboxSettings(engine, str(image), str(folder), **numbers), []  # type: ignore[arg-type]


def devbox_to_dict(s: DevboxSettings) -> dict[str, object]:
    return {"runtime": s.runtime.value, "image": s.image, "shared_folder": s.shared_folder, "cpus": s.cpus,
            "memory_mb": s.memory_mb, "pids": s.pids, "idle_stop_s": s.idle_stop_s,
            "destroy_after_s": s.destroy_after_s, "command_timeout_s": s.command_timeout_s}


def folder_problem(path: str) -> str | None:
    """Why this cannot be the shared folder, judged from the text alone (where it points is checked later).
    Mac and Linux paths only: the box is not offered on Windows."""
    if not path.startswith("/") or len(path) > 1000:
        return "must be a full folder path starting with /"
    if any(c in BAD_PATH_CHARS or ord(c) < 32 for c in path):
        return "contains a character that is not allowed (, : ; quotes, $, a backslash or a control character)"
    return None


def relative_problem(rel: str) -> str | None:
    """Why this is not a folder inside the shared folder. Plain names only: no '..', no absolute paths."""
    if rel in ("", "."):
        return None
    if not RELATIVE.fullmatch(rel) or any(part in ("", ".", "..") for part in rel.split("/")):
        return "the folder must be a plain relative path inside the shared folder"
    return None


def create_args(s: DevboxSettings, folder: str, uid: int, gid: int) -> list[str]:
    """The arguments for creating (not starting) the box. Every line here is a limit; none depends on a plan."""
    memory = f"{s.memory_mb}m"
    return [
        "create", "--name", CONTAINER_NAME, "--label", LABEL, "--hostname", "devbox",
        "--network", "none",
        "--read-only", "--tmpfs", f"{SCRATCH}:rw,nosuid,nodev,size=256m",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", str(s.pids), "--memory", memory, "--memory-swap", memory, "--cpus", f"{s.cpus:g}",
        "--ulimit", "nofile=1024:1024", "--ulimit", "core=0",
        "--user", f"{uid}:{gid}", "--init", "--env", f"HOME={SCRATCH}",
        "--mount", f"type=bind,source={folder},target={WORK_DIR}",
        "--workdir", WORK_DIR, "--entrypoint", "sleep", s.image, "infinity",
    ]


def exec_args(rel_dir: str, command: str) -> list[str]:
    """Run one shell command in the box. The shell is the box's, so pipes and redirects are fine there."""
    where = WORK_DIR if rel_dir in ("", ".") else f"{WORK_DIR}/{rel_dir}"
    return ["exec", "--workdir", where, CONTAINER_NAME, "sh", "-c", command]


@dataclass(frozen=True, slots=True)
class RunResult:
    exit_code: int | None                  # None when it was cut short
    output: str
    truncated: bool = False                # the start of a long output was dropped
    timed_out: bool = False


OutputSink = Callable[[str], None]       # told the whole output so far, like a streaming reply


class Engines(Protocol):
    """What the devbox needs from Docker or Podman. The real one runs the command line; tests use a fake."""

    name: str

    async def image_present(self, image: str) -> bool: ...
    async def pull(self, image: str) -> None: ...
    async def state(self) -> str: ...                  # "missing", "stopped" or "running"
    async def create(self, args: list[str]) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def remove(self) -> None: ...
    async def run(self, args: list[str], timeout_s: float, on_output: OutputSink | None) -> RunResult: ...


