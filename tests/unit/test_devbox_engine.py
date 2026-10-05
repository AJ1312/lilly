"""CliEngine against a stand-in `docker` script: real subprocesses, real pipes, no containers.

What this proves is how Lilly calls the engine and handles its output, exit codes, silence and runaway output. That a
real Docker or Podman accepts these arguments is checked by hand (docs/VERIFICATION.md)."""
from __future__ import annotations

import stat
from pathlib import Path

import pytest

from lilly.domain.devbox import MAX_OUTPUT_CHARS, Engine
from lilly.domain.errors import ToolError
from lilly.tools.devbox.engines import CliEngine, find_engine

pytestmark = pytest.mark.asyncio

SCRIPT = r"""#!/bin/sh
echo "$@" >> "$LOG"
case "$1 $2" in
  "container inspect") [ -f "$STATE" ] && cat "$STATE" || exit 1 ;;
  "image inspect") [ "$IMAGE" = "yes" ] && echo sha256:abc || exit 1 ;;
  "pull --quiet") [ "$PULL" = "fail" ] && { echo "denied: no way" >&2; exit 1; } || exit 0 ;;
esac
case "$1" in
  create) echo "id" ; echo true > "$STATE" ;;
  start) echo true > "$STATE" ;;
  stop) echo false > "$STATE" ;;
  rm) rm -f "$STATE" ;;
  exec)
    case "$*" in
      *flood*) yes 0123456789 | head -c 400000; exit 0 ;;
      *wide*) printf '%s' "$(head -c 4095 /dev/zero | tr '\0' a)é€" ;;
      *hang*) echo started; sleep 30 ;;
      *fail*) echo "boom" >&2; exit 3 ;;
      *) echo one; echo two ;;
    esac ;;
esac
"""


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CliEngine:
    path = tmp_path / "docker"
    path.write_text(SCRIPT)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("LOG", str(tmp_path / "log"))
    monkeypatch.setenv("STATE", str(tmp_path / "state"))
    monkeypatch.setenv("IMAGE", "yes")
    return CliEngine("docker", str(path))


def log(tmp_path: Path) -> list[str]:
    f = tmp_path / "log"
    return f.read_text().splitlines() if f.exists() else []


async def test_the_engine_is_found_by_name_and_docker_is_preferred() -> None:
    have = {"docker": "/x/docker", "podman": "/x/podman"}
    assert find_engine(Engine.AUTO, have.get) == ("docker", "/x/docker")
    assert find_engine(Engine.PODMAN, have.get) == ("podman", "/x/podman")
    assert find_engine(Engine.AUTO, {"podman": "/p"}.get) == ("podman", "/p")
    assert find_engine(Engine.DOCKER, {"podman": "/p"}.get) is None and find_engine(Engine.AUTO, {}.get) is None


async def test_the_box_goes_missing_stopped_running_and_back(engine: CliEngine) -> None:
    assert await engine.state() == "missing"
    await engine.create(["create", "--name", "lilly-devbox"])
    assert await engine.state() == "running"
    await engine.stop()
    assert await engine.state() == "stopped"
    await engine.start()
    assert await engine.state() == "running"
    await engine.remove()
    assert await engine.state() == "missing"


async def test_image_checks_and_pulls(engine: CliEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    assert await engine.image_present("img") is True
    monkeypatch.setenv("IMAGE", "no")
    assert await engine.image_present("img") is False
    monkeypatch.setenv("PULL", "fail")
    with pytest.raises(ToolError, match="denied"):
        await engine.pull("img")


async def test_a_refused_create_explains_itself(engine: CliEngine, tmp_path: Path) -> None:
    (tmp_path / "docker").write_text("#!/bin/sh\necho 'no such image' >&2\nexit 125\n")
    with pytest.raises(ToolError, match="no such image"):
        await engine.create(["create"])


async def test_output_is_streamed_whole_so_far_and_the_exit_code_comes_back(engine: CliEngine) -> None:
    seen: list[str] = []
    result = await engine.run(["exec", "ok"], 10, seen.append)
    assert (result.exit_code, result.output, result.timed_out) == (0, "one\ntwo\n", False) and seen[-1] == "one\ntwo\n"
    failed = await engine.run(["exec", "fail"], 10, None)
    assert failed.exit_code == 3 and "boom" in failed.output          # errors and output arrive together


async def test_runaway_output_is_cut_to_its_tail_without_filling_memory(engine: CliEngine) -> None:
    result = await engine.run(["exec", "flood"], 20, None)
    assert result.truncated and len(result.output) <= MAX_OUTPUT_CHARS and result.exit_code == 0


async def test_a_character_split_across_two_reads_is_not_damaged(engine: CliEngine) -> None:
    result = await engine.run(["exec", "wide"], 20, None)
    assert result.output == "a" * 4095 + "é€" and result.exit_code == 0


async def test_a_command_that_outlives_its_time_is_cut_off_and_reports_what_it_said(engine: CliEngine) -> None:
    result = await engine.run(["exec", "hang"], 1.5, None)
    assert result.timed_out and result.exit_code is None and "started" in result.output
