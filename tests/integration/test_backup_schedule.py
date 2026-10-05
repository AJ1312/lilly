"""When backups happen: not at every start, never at the cost of good copies, and not in a tight retry loop."""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import httpx
import pytest

from lilly.app.paths import LillyPaths, init_paths
from lilly.app.runtime import Runtime
from lilly.store import snapshot
from tests.helpers import MemoryKeyStore


@pytest.fixture
def paths(tmp_path: Path) -> LillyPaths:
    return init_paths(tmp_path)


def old_backups(paths: LillyPaths, count: int, age_s: float) -> list[Path]:
    now = time.time()
    made = []
    for i in range(count):
        f = paths.backups / f"lilly-{i}.db"
        f.write_bytes(b"x")
        os.utime(f, (now - age_s + i, now - age_s + i))
        made.append(f)
    return made


async def start(paths: LillyPaths) -> Runtime:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    return await Runtime.create(paths, client=client, keys=MemoryKeyStore())


async def test_a_restart_does_not_take_another_backup_when_a_recent_one_exists(paths: LillyPaths) -> None:
    files = old_backups(paths, 2, age_s=600)
    rt = await start(paths)
    try:
        await asyncio.sleep(0.2)                        # housekeeping has had its first pass
        assert rt.maintenance.last_backup == pytest.approx(files[-1].stat().st_mtime)
        assert rt.maintenance.last_backup_file == files[-1].name
        assert sorted(p.name for p in paths.backups.glob("*.db")) == [f.name for f in files]
    finally:
        await rt.close()


async def test_a_damaged_database_never_pushes_good_backups_out(paths: LillyPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    files = old_backups(paths, snapshot.MAX_BACKUPS, age_s=3 * 86400)
    monkeypatch.setattr(snapshot, "integrity_ok", lambda con: False)
    rt = await start(paths)
    try:
        await rt.backup()
        assert all(f.exists() for f in files)
        assert rt.maintenance.integrity_ok is False
    finally:
        await rt.close()


async def test_a_failing_backup_is_not_retried_every_few_seconds(paths: LillyPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    async def failing(self: Runtime) -> Path:
        nonlocal attempts
        attempts += 1
        raise OSError("disk full")

    async def quick(self: Runtime) -> None:
        await asyncio.sleep(0.01)

    monkeypatch.setattr(Runtime, "backup", failing)
    monkeypatch.setattr(Runtime, "_sleep_until_needed", quick)
    rt = await start(paths)
    try:
        await asyncio.sleep(0.3)
        assert attempts == 1
    finally:
        await rt.close()
