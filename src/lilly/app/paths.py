"""The ~/.lilly folder layout, created private (0700) and refused if others can write to it."""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from lilly.domain.errors import ConfigurationError

DEFAULT_DIR_MODE = 0o700


@dataclass(frozen=True, slots=True)
class LillyPaths:
    root: Path
    log: Path
    backups: Path
    config: Path
    db: Path
    settings: Path
    token: Path       # the access token that signs you in to the UI
    secret: Path      # signs session cookies; replacing it signs everyone out


def init_paths(root: Path | str | None = None) -> LillyPaths:
    """Initialize and verify the ~/.lilly directory structure.

    Refuses to start if the root directory is group- or world-writable.
    All directories are created with mode 0700.
    """
    if root is None:
        raw_home = os.environ.get("LILLY_HOME")
        root_path = Path(raw_home).expanduser().resolve() if raw_home else (Path.home() / ".lilly").resolve()
    else:
        root_path = Path(root).expanduser().resolve()

    if root_path.exists():
        st = root_path.stat()
        if not stat.S_ISDIR(st.st_mode):
            raise ConfigurationError(f"Root path is not a directory: {root_path}")
        # Refuse if group-writable or world-writable
        if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            mode_str = oct(st.st_mode & 0o777)
            raise ConfigurationError(
                f"Directory {root_path} is group- or world-writable (mode {mode_str}), refusing to start"
            )
    else:
        root_path.mkdir(mode=DEFAULT_DIR_MODE, parents=True, exist_ok=True)
        os.chmod(root_path, DEFAULT_DIR_MODE)

    log = root_path / "log"
    backups = root_path / "backups"
    config = root_path / "config"

    for sub in (log, backups, config):
        if not sub.exists():
            sub.mkdir(mode=DEFAULT_DIR_MODE, exist_ok=True)
            os.chmod(sub, DEFAULT_DIR_MODE)

    return LillyPaths(
        root=root_path,
        log=log,
        backups=backups,
        config=config,
        db=root_path / "lilly.db",
        settings=config / "settings.json",
        token=config / "access-token",
        secret=config / "secret.key",
    )
