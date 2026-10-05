"""The devbox rules: settings bounds, safe paths, and a creation command that always carries every limit."""
from __future__ import annotations

import pytest

from lilly.domain import devbox as d


def parse(**over: object) -> tuple[d.DevboxSettings | None, list[str]]:
    return d.parse_devbox({**d.devbox_to_dict(d.DevboxSettings()), **over})


def test_defaults_round_trip_and_nothing_is_shared_until_chosen() -> None:
    s, errs = d.parse_devbox({})
    assert errs == [] and s == d.DevboxSettings() and s.shared_folder == ""
    assert d.parse_devbox(d.devbox_to_dict(s)) == (s, [])


@pytest.mark.parametrize("key,value", [
    ("cpus", 0.1), ("cpus", 9), ("memory_mb", 64), ("memory_mb", 99999), ("pids", 1), ("idle_stop_s", 5),
    ("destroy_after_s", 10), ("command_timeout_s", 0), ("command_timeout_s", 601), ("memory_mb", True),
    ("memory_mb", 512.5), ("runtime", "lxc"), ("image", "-rf"), ("image", "x y"), ("image", ""), ("image", 5),
    ("shared_folder", "relative/dir"), ("shared_folder", "/a,b"), ("shared_folder", "/a:b"), ("shared_folder", 4),
    ("shared_folder", "/a\nb"), ("shared_folder", '/a"b'),
])
def test_bad_values_are_refused_with_a_message(key: str, value: object) -> None:
    s, errs = parse(**{key: value})
    assert s is None and errs and key in errs[0]


def test_unknown_settings_and_non_objects_are_refused() -> None:
    assert d.parse_devbox({"network": "on"})[0] is None      # there is no switch for the network
    assert d.parse_devbox([])[0] is None


def test_digest_pinned_and_tagged_images_are_accepted() -> None:
    assert parse(image="python:3.12-slim")[0] is not None
    assert parse(image="ghcr.io/acme/box:1.2@sha256:" + "a" * 64)[0] is not None


@pytest.mark.parametrize("rel,ok", [("", True), (".", True), ("src", True), ("a/b c/d", True), ("..", False),
                                    ("../x", False), ("/etc", False), ("a/../b", False), ("a//b", False),
                                    ("a;b", False), ("$(x)", False)])
def test_relative_folders_stay_inside_the_shared_folder(rel: str, ok: bool) -> None:
    assert (d.relative_problem(rel) is None) is ok


def test_the_create_command_carries_every_limit_and_no_host_access() -> None:
    args = d.create_args(d.DevboxSettings(cpus=1.5, memory_mb=512, pids=64), "/home/me/box", 501, 20)
    joined = " ".join(args)
    for needed in ("--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
                   "--pids-limit 64", "--memory 512m", "--memory-swap 512m", "--cpus 1.5", "--user 501:20",
                   "--init", "--entrypoint sleep"):
        assert needed in joined
    mounts = [a for i, a in enumerate(args) if args[i - 1] == "--mount"]
    assert mounts == ["type=bind,source=/home/me/box,target=/work"]      # the one shared folder, nothing else
    assert not {"--privileged", "--pid", "--ipc", "-v", "--volume", "--cap-add", "--device", "--userns"} & set(args)
    assert "docker.sock" not in joined and "podman.sock" not in joined and args[-2:] == [d.DEFAULT_IMAGE, "infinity"]


def test_the_exec_command_runs_one_shell_line_in_a_folder_of_the_box() -> None:
    assert d.exec_args("", "ls")[:3] == ["exec", "--workdir", "/work"]
    assert d.exec_args("src", "ls | wc -l")[-4:] == [d.CONTAINER_NAME, "sh", "-c", "ls | wc -l"]
    assert d.exec_args("src", "x")[2] == "/work/src"
