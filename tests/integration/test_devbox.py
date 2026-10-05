"""The devbox manager and tool, against a fake engine: lifecycle, limits, idle clean-up, warm start, safety."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from lilly.domain.devbox import DevboxSettings
from lilly.domain.errors import ToolError, ValidationFailed
from lilly.domain.labels import Label
from lilly.domain.policy import PathScope
from lilly.domain.ports import ToolContext
from lilly.tools.devbox.manager import DevboxManager
from lilly.tools.devbox.tool import DevboxRunTool
from tests.fake_engine import FakeEngine
from tests.helpers import Clock

pytestmark = pytest.mark.asyncio


class Box:
    def __init__(self, tmp_path: Path) -> None:
        self.folder = tmp_path / "share" / "box"
        self.folder.mkdir(parents=True)
        self.cfg = DevboxSettings(shared_folder=str(self.folder))
        self.engine: FakeEngine | None = FakeEngine()
        self.clock = Clock(1000.0)
        self.scope = PathScope([str(tmp_path / "share")])
        self.manager = DevboxManager(lambda: self.cfg, lambda: self.scope, lambda c: self.engine, self.clock, ids=(501, 20))


@pytest.fixture
async def box(tmp_path: Path):
    b = Box(tmp_path)
    yield b
    await b.manager.close_all()


async def test_the_first_command_makes_and_starts_the_box_and_later_ones_reuse_it(box: Box) -> None:
    out = await box.manager.run("", "echo hello")
    assert out.exit_code == 0 and out.output == "hello\n"
    await box.manager.run("src", "ls")
    assert box.engine.calls == ["create", "start", "run", "run"]
    assert box.engine.ran[1][2] == "/work/src"


async def test_the_box_is_created_with_the_limits_and_only_the_shared_folder(box: Box) -> None:
    await box.manager.run("", "x")
    args = box.engine.created_with[0]
    assert "--network" in args and args[args.index("--network") + 1] == "none"
    assert f"type=bind,source={box.folder.resolve()},target=/work" in args and "--user" in args


async def test_it_will_not_start_without_a_downloaded_image(box: Box) -> None:
    box.engine.image_ready = False
    with pytest.raises(ToolError, match="Prepare"):
        await box.manager.run("", "x")
    assert box.engine.calls == []              # nothing was created, and nothing was downloaded behind the owner's back
    await box.manager.prepare()
    assert box.engine.calls == ["pull"]


@pytest.mark.parametrize("folder,message", [("", "choose a shared folder"), ("/etc", "inside a folder you have shared"),
                                            ("MISSING", "does not exist")])
async def test_a_bad_shared_folder_stops_it_before_anything_starts(box: Box, tmp_path: Path, folder: str, message: str) -> None:
    box.cfg = replace(box.cfg, shared_folder=str(tmp_path / "share" / "nope") if folder == "MISSING" else folder)
    with pytest.raises(ToolError, match=message):
        await box.manager.run("", "x")
    assert box.engine.calls == []


async def test_a_folder_that_is_a_link_out_of_the_shared_area_is_refused(box: Box, tmp_path: Path) -> None:
    outside = tmp_path / "private"
    outside.mkdir()
    link = tmp_path / "share" / "link"
    link.symlink_to(outside)
    box.cfg = replace(box.cfg, shared_folder=str(link))
    with pytest.raises(ToolError, match="inside a folder you have shared"):
        await box.manager.run("", "x")


async def test_a_link_to_a_folder_whose_real_name_has_a_comma_is_refused(box: Box, tmp_path: Path) -> None:
    real = tmp_path / "share" / "a,readonly=false"
    real.mkdir()
    link = tmp_path / "share" / "link"
    link.symlink_to(real)
    box.cfg = replace(box.cfg, shared_folder=str(link))                      # the text is clean, where it points is not
    with pytest.raises(ToolError, match="not allowed"):
        await box.manager.run("", "x")
    assert box.engine.calls == []


async def test_without_docker_or_podman_it_says_so(box: Box) -> None:
    box.engine = None
    with pytest.raises(ToolError, match="Docker or Podman"):
        await box.manager.run("", "x")
    assert (await box.manager.status())["state"] == "unavailable"


@pytest.mark.parametrize("rel,command", [("../etc", "ls"), ("/etc", "ls"), ("a;b", "ls"), ("", ""), ("", "  "),
                                         ("", "x" * 9000)])
async def test_bad_folders_and_commands_are_refused_up_front(box: Box, rel: str, command: str) -> None:
    with pytest.raises(ValidationFailed):
        await box.manager.run(rel, command)
    assert box.engine.calls == []


async def test_a_command_that_runs_out_of_time_destroys_the_box_and_the_next_one_gets_a_fresh_box(box: Box) -> None:
    box.engine.hang = True
    result = await box.manager.run("", "sleep 999")
    assert result.timed_out and box.engine.box == "missing"
    box.engine.hang = False
    await box.manager.run("", "echo")
    assert box.engine.calls.count("create") == 2


async def test_changed_settings_rebuild_the_box_instead_of_keeping_the_old_limits(box: Box) -> None:
    await box.manager.run("", "x")
    box.cfg = replace(box.cfg, memory_mb=256)
    await box.manager.run("", "x")
    assert box.engine.calls.count("remove") == 1 and "256m" in box.engine.created_with[-1]


async def test_a_box_left_by_an_earlier_run_is_never_trusted(tmp_path: Path) -> None:
    b = Box(tmp_path)
    b.engine = FakeEngine(state="running")
    await b.manager.run("", "x")
    assert b.engine.calls[:2] == ["remove", "create"]
    await b.manager.close_all()


async def test_commands_run_one_at_a_time(box: Box) -> None:
    box.engine.delay = 0.05
    await asyncio.gather(*(box.manager.run("", f"c{i}") for i in range(4)))
    assert box.engine.peak == 1 and len(box.engine.ran) == 4


async def test_a_quiet_box_is_stopped_then_destroyed_and_wakes_quickly_when_stopped(box: Box) -> None:
    await box.manager.run("", "x")
    box.clock.advance(300)
    await box.manager.reap_once()
    assert box.engine.box == "running"                       # not idle long enough yet
    box.clock.advance(400)
    await box.manager.reap_once()
    assert box.engine.box == "stopped"
    await box.manager.run("", "again")                       # restarted, not rebuilt: its state is intact
    assert box.engine.calls.count("create") == 1 and box.engine.box == "running"
    box.clock.advance(box.cfg.destroy_after_s + 1)
    await box.manager.reap_once()
    assert box.engine.box == "missing"


async def test_cleanup_adopts_a_box_it_did_not_start_and_then_stops_it(tmp_path: Path) -> None:
    b = Box(tmp_path)
    b.engine = FakeEngine(state="running")
    await b.manager.reap_once()
    assert b.engine.box == "running"
    b.clock.advance(b.cfg.idle_stop_s + 1)
    await b.manager.reap_once()
    assert b.engine.box == "stopped"


async def test_cleanup_with_nothing_to_clean_does_nothing(box: Box) -> None:
    await box.manager.reap_once()
    assert box.engine.calls == []


async def test_stop_all_and_shutdown_remove_the_box(box: Box) -> None:
    await box.manager.run("", "x")
    await box.manager.close_all()
    assert box.engine.box == "missing"


async def test_warming_starts_the_box_before_the_first_command(box: Box) -> None:
    box.manager.warm()
    box.manager.warm()                                       # a second hint while starting changes nothing
    await asyncio.sleep(0.05)
    assert box.engine.box == "running" and box.engine.calls == ["create", "start"]
    await box.manager.run("", "x")
    assert box.engine.calls == ["create", "start", "run"]


async def test_warming_never_downloads_and_never_fails_loudly(box: Box) -> None:
    box.engine.image_ready = False
    box.manager.warm()
    await asyncio.sleep(0.05)
    assert box.engine.calls == []
    box.engine.image_ready, box.engine.fail_start = True, True
    box.manager.warm()
    await asyncio.sleep(0.05)                                # a failed start is logged, not raised


async def test_status_tells_the_settings_screen_what_is_ready(box: Box) -> None:
    status = await box.manager.status()
    assert status == {"engine": "fake", "image": box.cfg.image, "image_ready": True, "state": "missing",
                           "folder_ok": True, "folder_problem": None, "preparing": False, "prepare_error": None}


async def test_the_tool_streams_output_labels_it_private_and_outside_and_forwards_warming(box: Box) -> None:
    tool = DevboxRunTool(box.manager)
    seen: list[str] = []
    ctx = ToolContext("t", "s", 30.0, lambda: False, on_text=seen.append)
    result = await tool.run({"command": "echo hello", "dir": ""}, ctx)
    assert seen == ["hel", "hello\n"] and result.output == "exit code 0\nhello\n"
    assert result.label is Label.PERSONAL and result.untrusted
    box.engine.hang = True
    assert "timed out" in (await tool.run({"command": "sleep 9"}, ctx)).output
    tool.warm()
    await asyncio.sleep(0.05)
    assert box.engine.box == "running"


async def test_a_folder_that_contains_something_private_cannot_be_shared(box: Box, tmp_path: Path) -> None:
    secret = tmp_path / "share" / "keys"
    secret.mkdir()
    box.scope = PathScope([str(tmp_path / "share")], deny=[str(secret)])
    box.cfg = replace(box.cfg, shared_folder=str(tmp_path / "share"))       # the parent would expose the keys
    with pytest.raises(ToolError, match="keeps private"):
        await box.manager.run("", "x")
    box.cfg = replace(box.cfg, shared_folder=str(box.folder))               # a sibling folder is fine
    assert (await box.manager.run("", "x")).exit_code == 0


async def test_a_command_that_is_cancelled_does_not_keep_running_in_the_box(box: Box) -> None:
    box.engine.delay = 5
    running = asyncio.create_task(box.manager.run("", "sleep 99"))
    await asyncio.sleep(0.05)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert box.engine.box == "missing"


async def test_stop_all_does_not_wait_for_a_running_command(box: Box) -> None:
    box.engine.delay = 5
    running = asyncio.create_task(box.manager.run("", "sleep 99"))
    await asyncio.sleep(0.05)
    async with asyncio.timeout(1):
        await box.manager.close_all()
    assert box.engine.box == "missing"
    running.cancel()
    await asyncio.gather(running, return_exceptions=True)
