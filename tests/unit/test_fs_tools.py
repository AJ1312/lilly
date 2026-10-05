"""File tools stay inside shared folders and never overwrite or follow links silently."""
from __future__ import annotations

from pathlib import Path

import pytest

from lilly.domain.errors import PolicyDenied, ToolError
from lilly.domain.policy import PathScope
from lilly.domain.ports import ToolContext
from lilly.tools.fs import FsListTool, FsReadTool, FsWriteTool

CTX = ToolContext("t", "s1", 5.0, lambda: False)


@pytest.fixture
def shared(tmp_path: Path) -> Path:
    root = tmp_path / "shared"
    root.mkdir()
    return root


async def test_read_and_list_inside_the_shared_folder(shared: Path) -> None:
    (shared / "a.txt").write_text("hello")
    scope = PathScope([str(shared)])
    assert "hello" in (await FsReadTool(scope).run({"path": str(shared / "a.txt")}, CTX)).output
    assert "a.txt" in (await FsListTool(scope).run({"path": str(shared)}, CTX)).output


async def test_paths_outside_the_shared_folder_are_denied(shared: Path, tmp_path: Path) -> None:
    (tmp_path / "private.txt").write_text("nope")
    scope = PathScope([str(shared)])
    with pytest.raises(PolicyDenied):
        await FsReadTool(scope).run({"path": str(tmp_path / "private.txt")}, CTX)
    with pytest.raises(PolicyDenied):
        await FsReadTool(scope).run({"path": str(shared / ".." / "private.txt")}, CTX)


async def test_write_refuses_to_replace_unless_asked(shared: Path) -> None:
    tool = FsWriteTool(PathScope([str(shared)]))
    target = str(shared / "n.txt")
    await tool.run({"path": target, "content": "one"}, CTX)
    with pytest.raises(ToolError, match="already exists"):
        await tool.run({"path": target, "content": "two"}, CTX)
    assert (shared / "n.txt").read_text() == "one"
    await tool.run({"path": target, "content": "two", "overwrite": True}, CTX)
    assert (shared / "n.txt").read_text() == "two"
    assert not list(shared.glob(".lilly-*.tmp"))


async def test_a_symlink_pointing_out_of_the_shared_folder_is_refused(shared: Path, tmp_path: Path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    (shared / "n.txt").symlink_to(victim)
    with pytest.raises(PolicyDenied):
        await FsWriteTool(PathScope([str(shared)])).run(
            {"path": str(shared / "n.txt"), "content": "x", "overwrite": True}, CTX)
    assert victim.read_text() == "keep"
