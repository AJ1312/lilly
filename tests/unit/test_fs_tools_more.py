"""Deeper safety tests for the file tools: containment, no silent overwrite, recoverable deletes, caps, atomicity."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest

from lilly.domain.errors import PolicyDenied, ToolError, ValidationFailed
from lilly.domain.policy import PathScope
from lilly.domain.ports import ToolContext
from lilly.tools import fs
from lilly.tools.fs import (
    FsApplyMovesTool,
    FsListTool,
    FsReadTool,
    FsSearchTool,
    FsTrashTool,
    FsWriteTool,
)

CTX = ToolContext("t", "s1", 5.0, lambda: False)

needs_symlinks = pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt",
                                    reason="POSIX symlinks are required to test link handling")
needs_fifo = pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="os.mkfifo is required (POSIX only)")


@pytest.fixture
def shared(tmp_path: Path) -> Path:
    root = tmp_path / "shared"
    root.mkdir()
    return root


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    out = tmp_path / "outside"
    out.mkdir()
    (out / "victim.txt").write_text("keep")
    return out


@pytest.fixture
def scope(shared: Path) -> PathScope:
    return PathScope([str(shared)])


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    return home


def _json(result: Any) -> Any:
    return json.loads(result.output)


# --------------------------------------------------------------------------- read


async def test_read_rejects_missing_and_non_text_inputs(shared: Path, scope: PathScope) -> None:
    tool = FsReadTool(scope)
    with pytest.raises(ValidationFailed):
        await tool.run({}, CTX)
    with pytest.raises(ValidationFailed):
        await tool.run({"path": 5}, CTX)
    with pytest.raises(ValidationFailed):
        await tool.run({"path": str(shared / "a.txt"), "max_bytes": "lots"}, CTX)
    with pytest.raises(ValidationFailed):
        await tool.run({"path": str(shared / "a.txt"), "max_bytes": True}, CTX)


async def test_read_missing_file_and_directory_are_tool_errors(shared: Path, scope: PathScope) -> None:
    tool = FsReadTool(scope)
    with pytest.raises(ToolError, match="cannot open file"):
        await tool.run({"path": str(shared / "nope.txt")}, CTX)
    with pytest.raises(ToolError, match="cannot open folder"):
        await tool.run({"path": str(shared / "nodir" / "nope.txt")}, CTX)
    (shared / "sub").mkdir()
    with pytest.raises(ToolError, match="not a regular file"):
        await tool.run({"path": str(shared / "sub")}, CTX)


async def test_read_truncates_at_max_bytes_and_says_so(shared: Path, scope: PathScope) -> None:
    (shared / "big.txt").write_text("abcdefghij" * 10)
    result = await FsReadTool(scope).run({"path": str(shared / "big.txt"), "max_bytes": 15}, CTX)
    assert result.output.startswith("abcdefghijabcde\n[truncated: showing the first 15 of 100 bytes]")


async def test_read_whole_small_file_has_no_truncation_note(shared: Path, scope: PathScope) -> None:
    (shared / "s.txt").write_text("héllo")
    result = await FsReadTool(scope).run({"path": str(shared / "s.txt")}, CTX)
    assert result.output == "héllo"


async def test_read_max_bytes_is_clamped_to_at_least_one(shared: Path, scope: PathScope) -> None:
    (shared / "s.txt").write_text("xyz")
    result = await FsReadTool(scope).run({"path": str(shared / "s.txt"), "max_bytes": -50}, CTX)
    assert result.output.startswith("x\n[truncated")


async def test_read_refuses_binary_files(shared: Path, scope: PathScope) -> None:
    (shared / "b.bin").write_bytes(b"abc\x00def")
    with pytest.raises(ToolError, match="binary"):
        await FsReadTool(scope).run({"path": str(shared / "b.bin")}, CTX)


async def test_read_replaces_invalid_utf8_instead_of_failing(shared: Path, scope: PathScope) -> None:
    (shared / "l.txt").write_bytes(b"caf\xe9")
    result = await FsReadTool(scope).run({"path": str(shared / "l.txt")}, CTX)
    assert result.output == "caf�"


@needs_fifo
async def test_read_does_not_hang_on_a_fifo(shared: Path, scope: PathScope) -> None:
    os.mkfifo(shared / "pipe")
    with pytest.raises(ToolError, match="not a regular file"):
        await FsReadTool(scope).run({"path": str(shared / "pipe")}, CTX)


async def test_read_is_labelled_personal(shared: Path, scope: PathScope) -> None:
    from lilly.domain.labels import Label

    (shared / "a.txt").write_text("x")
    result = await FsReadTool(scope).run({"path": str(shared / "a.txt")}, CTX)
    assert result.label is Label.PERSONAL


# ----------------------------------------------------------------- containment (all tools)


async def test_sibling_folder_sharing_a_name_prefix_is_not_inside(tmp_path: Path, shared: Path, scope: PathScope) -> None:
    sibling = tmp_path / "shared2"
    sibling.mkdir()
    (sibling / "x.txt").write_text("secret")
    with pytest.raises(PolicyDenied):
        await FsReadTool(scope).run({"path": str(sibling / "x.txt")}, CTX)
    with pytest.raises(PolicyDenied):
        await FsListTool(scope).run({"path": str(sibling)}, CTX)


async def test_every_tool_denies_dotdot_and_absolute_escapes(shared: Path, outside: Path, scope: PathScope) -> None:
    escape = str(shared / ".." / "outside" / "victim.txt")
    absolute = str(outside / "victim.txt")
    for raw in (escape, absolute, "/etc/passwd", "", "\x00"):
        with pytest.raises((PolicyDenied, ValidationFailed)):
            await FsReadTool(scope).run({"path": raw}, CTX)
        with pytest.raises((PolicyDenied, ValidationFailed)):
            await FsWriteTool(scope).run({"path": raw, "content": "x", "overwrite": True}, CTX)
        with pytest.raises((PolicyDenied, ValidationFailed)):
            await FsTrashTool(scope).run({"path": raw}, CTX)
    for tool in (FsListTool(scope),):
        with pytest.raises(PolicyDenied):
            await tool.run({"path": str(outside)}, CTX)
    with pytest.raises(PolicyDenied):
        await FsSearchTool(scope).run({"path": str(outside), "query": "keep"}, CTX)
    with pytest.raises(PolicyDenied):
        await FsApplyMovesTool(scope).run({"root": str(outside), "moves": [{"from": "victim.txt", "to": "y.txt"}]}, CTX)
    assert (outside / "victim.txt").read_text() == "keep"
    assert sorted(p.name for p in outside.iterdir()) == ["victim.txt"]


@pytest.mark.skipif(os.path.exists("/TMP") or os.path.exists("/Tmp"), reason="filesystem is case-insensitive")
async def test_a_different_letter_case_is_a_different_folder(tmp_path: Path, shared: Path, scope: PathScope) -> None:
    upper = tmp_path / "SHARED"
    assert not upper.exists()
    with pytest.raises(PolicyDenied):
        await FsWriteTool(scope).run({"path": str(upper / "n.txt"), "content": "x"}, CTX)
    assert not upper.exists()


@needs_symlinks
async def test_symlinked_folder_out_of_scope_is_denied_everywhere(shared: Path, outside: Path, scope: PathScope) -> None:
    (shared / "door").symlink_to(outside, target_is_directory=True)
    door = str(shared / "door")
    with pytest.raises(PolicyDenied):
        await FsListTool(scope).run({"path": door}, CTX)
    with pytest.raises(PolicyDenied):
        await FsReadTool(scope).run({"path": door + "/victim.txt"}, CTX)
    with pytest.raises(PolicyDenied):
        await FsWriteTool(scope).run({"path": door + "/new.txt", "content": "x"}, CTX)
    with pytest.raises(PolicyDenied):
        await FsTrashTool(scope).run({"path": door + "/victim.txt"}, CTX)
    with pytest.raises(PolicyDenied):
        await FsSearchTool(scope).run({"path": door, "query": "keep"}, CTX)
    assert sorted(p.name for p in outside.iterdir()) == ["victim.txt"]
    assert (outside / "victim.txt").read_text() == "keep"


@needs_symlinks
async def test_read_through_a_dangling_or_outward_file_link_is_denied(shared: Path, outside: Path, scope: PathScope) -> None:
    (shared / "peek.txt").symlink_to(outside / "victim.txt")
    with pytest.raises(PolicyDenied):
        await FsReadTool(scope).run({"path": str(shared / "peek.txt")}, CTX)
    (shared / "dangling").symlink_to(outside / "missing.txt")
    with pytest.raises(PolicyDenied):
        await FsWriteTool(scope).run({"path": str(shared / "dangling"), "content": "x"}, CTX)
    assert not (outside / "missing.txt").exists()


@needs_symlinks
async def test_a_link_inside_the_folder_to_another_inside_file_is_readable(shared: Path, scope: PathScope) -> None:
    (shared / "real.txt").write_text("inside")
    (shared / "alias.txt").symlink_to(shared / "real.txt")
    result = await FsReadTool(scope).run({"path": str(shared / "alias.txt")}, CTX)
    assert result.output == "inside"


async def test_a_denied_subfolder_is_not_reachable_directly(shared: Path) -> None:
    private = shared / "private"
    private.mkdir()
    (private / "secret.txt").write_text("hush")
    scope = PathScope([str(shared)], deny=(str(private),))
    with pytest.raises(PolicyDenied):
        await FsReadTool(scope).run({"path": str(private / "secret.txt")}, CTX)
    with pytest.raises(PolicyDenied):
        await FsWriteTool(scope).run({"path": str(private / "new.txt"), "content": "x"}, CTX)
    with pytest.raises(PolicyDenied):
        await FsTrashTool(scope).run({"path": str(private / "secret.txt")}, CTX)
    with pytest.raises(PolicyDenied):
        await FsListTool(scope).run({"path": str(private)}, CTX)


# --------------------------------------------------------------------------- list


async def test_list_reports_types_sizes_and_sorts_case_insensitively(shared: Path, scope: PathScope) -> None:
    (shared / "b.txt").write_text("12345")
    (shared / "A.txt").write_text("")
    (shared / "dir").mkdir()
    data = _json(await FsListTool(scope).run({"path": str(shared)}, CTX))
    assert [e["name"] for e in data["entries"]] == ["A.txt", "b.txt", "dir"]
    by_name = {e["name"]: e for e in data["entries"]}
    assert by_name["b.txt"]["type"] == "file" and by_name["b.txt"]["size"] == 5
    assert by_name["dir"]["type"] == "dir" and by_name["dir"]["size"] is None
    assert data["truncated"] is False
    assert by_name["b.txt"]["modified"].endswith("+00:00")


@needs_symlinks
async def test_list_shows_links_as_links_without_following_them(shared: Path, outside: Path, scope: PathScope) -> None:
    (shared / "l").symlink_to(outside / "victim.txt")
    (shared / "dangling").symlink_to(outside / "gone")
    entries = {e["name"]: e for e in _json(await FsListTool(scope).run({"path": str(shared)}, CTX))["entries"]}
    assert entries["l"]["type"] == "link" and entries["l"]["size"] is None
    assert entries["dangling"]["type"] == "link"


async def test_list_caps_entries_and_flags_truncation(shared: Path, scope: PathScope) -> None:
    for i in range(5):
        (shared / f"f{i}.txt").write_text("x")
    data = _json(await FsListTool(scope).run({"path": str(shared), "max_entries": 3}, CTX))
    assert [e["name"] for e in data["entries"]] == ["f0.txt", "f1.txt", "f2.txt"]
    assert data["truncated"] is True


async def test_list_clamps_max_entries_to_one_minimum(shared: Path, scope: PathScope) -> None:
    (shared / "a").write_text("x")
    (shared / "b").write_text("x")
    data = _json(await FsListTool(scope).run({"path": str(shared), "max_entries": 0}, CTX))
    assert len(data["entries"]) == 1 and data["truncated"] is True


async def test_list_is_not_truncated_when_everything_fits_exactly(shared: Path, scope: PathScope) -> None:
    for i in range(3):
        (shared / f"f{i}.txt").write_text("x")
    data = _json(await FsListTool(scope).run({"path": str(shared), "max_entries": 3}, CTX))
    assert len(data["entries"]) == 3
    assert data["truncated"] is False


async def test_list_errors_for_a_file_or_missing_folder(shared: Path, scope: PathScope) -> None:
    (shared / "f.txt").write_text("x")
    with pytest.raises(ToolError, match="cannot list folder"):
        await FsListTool(scope).run({"path": str(shared / "f.txt")}, CTX)
    with pytest.raises(ToolError, match="cannot list folder"):
        await FsListTool(scope).run({"path": str(shared / "missing")}, CTX)


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="permission bits are ignored for root")
async def test_list_unreadable_folder_is_a_tool_error(shared: Path, scope: PathScope) -> None:
    locked = shared / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        with pytest.raises(ToolError, match="cannot list folder"):
            await FsListTool(scope).run({"path": str(locked)}, CTX)
    finally:
        locked.chmod(stat.S_IRWXU)


# ------------------------------------------------------------------------- search


async def test_search_finds_by_name_and_by_text_case_insensitively(shared: Path, scope: PathScope) -> None:
    (shared / "Budget.txt").write_text("nothing here")
    (shared / "notes.txt").write_text("Remember the   BUDGET\nreview")
    (shared / "other.txt").write_text("unrelated")
    (shared / "sub").mkdir()
    (shared / "sub" / "deep.txt").write_text("a budget line")
    data = _json(await FsSearchTool(scope).run({"path": str(shared), "query": "Budget"}, CTX))
    hits = {Path(h["path"]).name: h for h in data["hits"]}
    assert set(hits) == {"Budget.txt", "notes.txt", "deep.txt"}
    assert hits["Budget.txt"]["match"] == "name"
    assert hits["notes.txt"]["match"] == "text"
    assert hits["notes.txt"]["snippet"] == "Remember the BUDGET review"  # whitespace collapsed
    assert data["files_scanned"] == 4 and data["truncated"] is False


async def test_search_requires_a_query(shared: Path, scope: PathScope) -> None:
    with pytest.raises(ValidationFailed):
        await FsSearchTool(scope).run({"path": str(shared)}, CTX)
    with pytest.raises(ValidationFailed):
        await FsSearchTool(scope).run({"path": str(shared), "query": "x" * 201}, CTX)
    with pytest.raises(ValidationFailed):
        await FsSearchTool(scope).run({"path": str(shared), "query": "q", "max_results": []}, CTX)


async def test_search_skips_binary_oversized_and_ignored_folders(shared: Path, scope: PathScope) -> None:
    (shared / "bin.dat").write_bytes(b"needle\x00binary")
    (shared / "huge.txt").write_text("x" * (fs.MAX_SEARCH_FILE_BYTES + 1) + "needle")
    for skipped in (".git", "node_modules", "__pycache__", ".venv"):
        (shared / skipped).mkdir()
        (shared / skipped / "f.txt").write_text("needle")
    (shared / "ok.txt").write_text("a needle")
    data = _json(await FsSearchTool(scope).run({"path": str(shared), "query": "needle"}, CTX))
    assert [Path(h["path"]).name for h in data["hits"]] == ["ok.txt"]


async def test_search_stops_at_max_results_and_flags_truncation(shared: Path, scope: PathScope) -> None:
    for i in range(6):
        (shared / f"hit{i}.txt").write_text("x")
    data = _json(await FsSearchTool(scope).run({"path": str(shared), "query": "hit", "max_results": 2}, CTX))
    assert len(data["hits"]) == 2 and data["truncated"] is True


async def test_search_stops_at_the_file_scan_cap(shared: Path, scope: PathScope, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fs, "MAX_SEARCH_FILES", 3)
    for i in range(6):
        (shared / f"f{i}.txt").write_text("x")
    data = _json(await FsSearchTool(scope).run({"path": str(shared), "query": "zzz"}, CTX))
    assert data["files_scanned"] == 3 and data["truncated"] is True and data["hits"] == []


async def test_search_honours_cancellation(shared: Path, scope: PathScope) -> None:
    (shared / "a.txt").write_text("x")
    cancelled = ToolContext("t", "s", 5.0, lambda: True)
    with pytest.raises(ToolError, match="cancelled"):
        await FsSearchTool(scope).run({"path": str(shared), "query": "x"}, cancelled)


@needs_symlinks
async def test_search_never_follows_links_out_of_the_folder(shared: Path, outside: Path, scope: PathScope) -> None:
    (outside / "leak.txt").write_text("needle")
    (shared / "dirlink").symlink_to(outside, target_is_directory=True)
    (shared / "filelink.txt").symlink_to(outside / "leak.txt")
    (shared / "plain.txt").write_text("nothing")
    data = _json(await FsSearchTool(scope).run({"path": str(shared), "query": "needle"}, CTX))
    assert data["hits"] == []
    assert data["files_scanned"] == 1


async def test_search_on_an_empty_or_missing_folder_finds_nothing(shared: Path, scope: PathScope) -> None:
    data = _json(await FsSearchTool(scope).run({"path": str(shared), "query": "a"}, CTX))
    assert data["hits"] == [] and data["files_scanned"] == 0
    data = _json(await FsSearchTool(scope).run({"path": str(shared / "missing"), "query": "a"}, CTX))
    assert data["hits"] == []


async def test_search_does_not_descend_into_denied_subfolders(shared: Path) -> None:
    private = shared / "private"
    private.mkdir()
    (private / "secret.txt").write_text("needle in the secret")
    (shared / "public.txt").write_text("needle in public")
    scope = PathScope([str(shared)], deny=(str(private),))
    data = _json(await FsSearchTool(scope).run({"path": str(shared), "query": "needle"}, CTX))
    assert [Path(h["path"]).name for h in data["hits"]] == ["public.txt"]


# -------------------------------------------------------------------------- write


async def test_write_creates_a_file_and_reports_utf8_byte_count(shared: Path, scope: PathScope) -> None:
    result = await FsWriteTool(scope).run({"path": str(shared / "u.txt"), "content": "héllo"}, CTX)
    assert (shared / "u.txt").read_bytes() == "héllo".encode()
    assert "Wrote 6 bytes" in result.output
    assert not list(shared.glob(".lilly-*"))


async def test_write_without_content_creates_an_empty_file(shared: Path, scope: PathScope) -> None:
    await FsWriteTool(scope).run({"path": str(shared / "e.txt")}, CTX)
    assert (shared / "e.txt").read_bytes() == b""


async def test_write_rejects_non_text_content_and_bad_flags(shared: Path, scope: PathScope) -> None:
    tool = FsWriteTool(scope)
    with pytest.raises(ValidationFailed, match="must be text"):
        await tool.run({"path": str(shared / "a.txt"), "content": {"a": 1}}, CTX)
    with pytest.raises(ValidationFailed, match="true or false"):
        await tool.run({"path": str(shared / "a.txt"), "content": "x", "overwrite": "maybe"}, CTX)
    with pytest.raises(ValidationFailed, match="true or false"):
        await tool.run({"path": str(shared / "a.txt"), "content": "x", "overwrite": 1}, CTX)
    assert not (shared / "a.txt").exists()


async def test_write_overwrite_accepts_string_booleans(shared: Path, scope: PathScope) -> None:
    tool = FsWriteTool(scope)
    path = str(shared / "a.txt")
    await tool.run({"path": path, "content": "one"}, CTX)
    with pytest.raises(ToolError, match="already exists"):
        await tool.run({"path": path, "content": "two", "overwrite": "false"}, CTX)
    assert (shared / "a.txt").read_text() == "one"
    await tool.run({"path": path, "content": "two", "overwrite": " TRUE "}, CTX)
    assert (shared / "a.txt").read_text() == "two"


async def test_write_enforces_the_size_cap_before_touching_disk(shared: Path, scope: PathScope) -> None:
    with pytest.raises(ValidationFailed, match="too large"):
        await FsWriteTool(scope).run({"path": str(shared / "big.txt"), "content": "x" * (fs.MAX_WRITE_BYTES + 1)}, CTX)
    assert list(shared.iterdir()) == []


async def test_write_cap_counts_bytes_not_characters(shared: Path, scope: PathScope, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fs, "MAX_WRITE_BYTES", 10)
    await FsWriteTool(scope).run({"path": str(shared / "ok.txt"), "content": "x" * 10}, CTX)
    with pytest.raises(ValidationFailed, match="too large"):
        await FsWriteTool(scope).run({"path": str(shared / "wide.txt"), "content": "é" * 6}, CTX)  # 12 bytes
    assert not (shared / "wide.txt").exists()


async def test_write_into_a_missing_folder_fails_without_creating_it(shared: Path, scope: PathScope) -> None:
    with pytest.raises(ToolError, match="does not exist"):
        await FsWriteTool(scope).run({"path": str(shared / "nope" / "a.txt"), "content": "x"}, CTX)
    assert not (shared / "nope").exists()


async def test_write_cannot_replace_a_folder(shared: Path, scope: PathScope) -> None:
    (shared / "dir").mkdir()
    (shared / "dir" / "keep.txt").write_text("keep")
    with pytest.raises(ToolError):
        await FsWriteTool(scope).run({"path": str(shared / "dir"), "content": "x"}, CTX)
    with pytest.raises(ToolError):
        await FsWriteTool(scope).run({"path": str(shared / "dir"), "content": "x", "overwrite": True}, CTX)
    assert (shared / "dir" / "keep.txt").read_text() == "keep"
    assert not list(shared.glob(".lilly-*"))


async def test_write_cannot_replace_the_shared_folder_itself(shared: Path, scope: PathScope) -> None:
    (shared / "keep.txt").write_text("keep")
    with pytest.raises(ToolError):
        await FsWriteTool(scope).run({"path": str(shared), "content": "x", "overwrite": True}, CTX)
    assert (shared / "keep.txt").read_text() == "keep"
    assert not list(shared.parent.glob(".lilly-*"))


async def test_failed_overwrite_leaves_original_intact_and_no_temp_file(
        shared: Path, scope: PathScope, monkeypatch: pytest.MonkeyPatch) -> None:
    (shared / "a.txt").write_text("original")

    def boom(fd: int) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(fs.os, "fsync", boom)
    with pytest.raises(ToolError, match="cannot write file"):
        await FsWriteTool(scope).run({"path": str(shared / "a.txt"), "content": "new", "overwrite": True}, CTX)
    assert (shared / "a.txt").read_text() == "original"
    assert sorted(p.name for p in shared.iterdir()) == ["a.txt"]


async def test_failed_create_leaves_nothing_behind(shared: Path, scope: PathScope, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(fd: int) -> None:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(fs.os, "fsync", boom)
    with pytest.raises(ToolError):
        await FsWriteTool(scope).run({"path": str(shared / "a.txt"), "content": "new"}, CTX)
    assert list(shared.iterdir()) == []


async def test_write_refuses_when_a_file_appears_late_without_overwrite(
        shared: Path, scope: PathScope, monkeypatch: pytest.MonkeyPatch) -> None:
    """The existence check is atomic (hard link), so a file created between tool start and link is never lost."""
    real_link = os.link

    def racing_link(src: str, dst: str, **kw: Any) -> None:
        (shared / "a.txt").write_text("someone else")
        real_link(src, dst, **kw)

    monkeypatch.setattr(fs.os, "link", racing_link)
    with pytest.raises(ToolError, match="already exists"):
        await FsWriteTool(scope).run({"path": str(shared / "a.txt"), "content": "mine"}, CTX)
    assert (shared / "a.txt").read_text() == "someone else"
    assert sorted(p.name for p in shared.iterdir()) == ["a.txt"]


async def test_write_through_a_dotdot_that_stays_inside_is_allowed(shared: Path, scope: PathScope) -> None:
    (shared / "sub").mkdir()
    await FsWriteTool(scope).run({"path": str(shared / "sub" / ".." / "n.txt"), "content": "ok"}, CTX)
    assert (shared / "n.txt").read_text() == "ok"


@needs_symlinks
async def test_write_does_not_modify_the_target_of_an_inside_link_via_the_tmp_name(shared: Path, scope: PathScope) -> None:
    (shared / "real.txt").write_text("real")
    (shared / "alias.txt").symlink_to(shared / "real.txt")
    await FsWriteTool(scope).run({"path": str(shared / "alias.txt"), "content": "new", "overwrite": True}, CTX)
    assert (shared / "real.txt").read_text() == "new"
    assert not list(shared.glob(".lilly-*"))


# ------------------------------------------------------------------- apply_moves


def _moves(*pairs: tuple[str, str]) -> dict[str, Any]:
    return {"moves": [{"from": a, "to": b} for a, b in pairs]}


async def test_apply_moves_moves_files_creates_folders_and_returns_undo(shared: Path, scope: PathScope) -> None:
    (shared / "a.txt").write_text("A")
    (shared / "b.txt").write_text("B")
    result = await FsApplyMovesTool(scope).run(
        {"root": str(shared), **_moves(("a.txt", "docs/a.txt"), ("b.txt", "docs/2024/b.txt"))}, CTX)
    data = _json(result)
    assert data["moved"] == 2
    assert (shared / "docs" / "a.txt").read_text() == "A"
    assert (shared / "docs" / "2024" / "b.txt").read_text() == "B"
    assert not (shared / "a.txt").exists() and not (shared / "b.txt").exists()
    # the undo list, applied, restores the original layout
    undo = {"root": str(shared), "moves": data["undo"]}
    await FsApplyMovesTool(scope).run(undo, CTX)
    assert (shared / "a.txt").read_text() == "A" and (shared / "b.txt").read_text() == "B"


async def test_apply_moves_accepts_json_text_fenced_json_and_wrapped_object(shared: Path, scope: PathScope) -> None:
    for n, payload in enumerate((
        json.dumps([{"from": "a.txt", "to": "x1.txt"}]),
        'Here you go:\n```json\n{"moves": [{"src": "x1.txt", "dst": "x2.txt"}]}\n```',
        {"moves": [{"from": "x2.txt", "to": "x3.txt"}]},
    )):
        if n == 0:
            (shared / "a.txt").write_text("A")
        await FsApplyMovesTool(scope).run({"root": str(shared), "moves": payload}, CTX)
    assert (shared / "x3.txt").read_text() == "A"
    assert sorted(p.name for p in shared.iterdir()) == ["x3.txt"]


async def test_apply_moves_validates_the_move_list(shared: Path, scope: PathScope) -> None:
    tool = FsApplyMovesTool(scope)
    root = str(shared)
    for bad in (None, [], {}, "not json at all", "[]", 5, {"moves": "x"}):
        with pytest.raises(ValidationFailed):
            await tool.run({"root": root, "moves": bad}, CTX)
    with pytest.raises(ValidationFailed, match="not an object"):
        await tool.run({"root": root, "moves": ["a.txt"]}, CTX)
    with pytest.raises(ValidationFailed):
        await tool.run({"moves": [{"from": "a", "to": "b"}]}, CTX)


async def test_apply_moves_enforces_the_batch_cap(shared: Path, scope: PathScope) -> None:
    (shared / "a.txt").write_text("A")
    too_many = [{"from": "a.txt", "to": f"d/{i}.txt"} for i in range(fs.MAX_MOVES + 1)]
    with pytest.raises(ValidationFailed, match="at most"):
        await FsApplyMovesTool(scope).run({"root": str(shared), "moves": too_many}, CTX)
    assert (shared / "a.txt").exists() and not (shared / "d").exists()


async def test_apply_moves_at_exactly_the_cap_is_accepted(shared: Path, scope: PathScope, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fs, "MAX_MOVES", 3)
    for i in range(3):
        (shared / f"f{i}.txt").write_text(str(i))
    moves = [{"from": f"f{i}.txt", "to": f"g/f{i}.txt"} for i in range(3)]
    assert _json(await FsApplyMovesTool(scope).run({"root": str(shared), "moves": moves}, CTX))["moved"] == 3


async def test_apply_moves_refuses_paths_that_leave_the_folder(shared: Path, outside: Path, scope: PathScope) -> None:
    (shared / "a.txt").write_text("A")
    tool = FsApplyMovesTool(scope)
    root = str(shared)
    escapes = [
        ("a.txt", "../outside/a.txt"),
        ("a.txt", "sub/../../outside/a.txt"),
        ("../outside/victim.txt", "stolen.txt"),
        ("a.txt", "."),
        (".", "x.txt"),
    ]
    for src, dst in escapes:
        with pytest.raises(PolicyDenied):
            await tool.run({"root": root, **_moves((src, dst))}, CTX)
    assert (shared / "a.txt").read_text() == "A"
    assert (outside / "victim.txt").read_text() == "keep"
    assert sorted(p.name for p in outside.iterdir()) == ["victim.txt"]
    assert sorted(p.name for p in shared.iterdir()) == ["a.txt"]


async def test_apply_moves_refuses_absolute_and_malformed_names(shared: Path, outside: Path, scope: PathScope) -> None:
    (shared / "a.txt").write_text("A")
    tool = FsApplyMovesTool(scope)
    root = str(shared)
    for src, dst in [("a.txt", str(outside / "a.txt")), (str(outside / "victim.txt"), "x.txt"),
                     ("a.txt", ""), ("a.txt", "   "), ("a.txt", "b\x00c"), ("", "b.txt")]:
        with pytest.raises(ValidationFailed):
            await tool.run({"root": root, **_moves((src, dst))}, CTX)
    for dst in ("sub/..", ".."):
        with pytest.raises((ValidationFailed, PolicyDenied)):
            await tool.run({"root": root, **_moves(("a.txt", dst))}, CTX)
    with pytest.raises(ValidationFailed):
        await tool.run({"root": root, "moves": [{"from": "a.txt"}]}, CTX)
    assert (shared / "a.txt").read_text() == "A" and (outside / "victim.txt").exists()


@needs_symlinks
async def test_apply_moves_refuses_a_symlinked_folder_pointing_out(shared: Path, outside: Path, scope: PathScope) -> None:
    (shared / "a.txt").write_text("A")
    (shared / "door").symlink_to(outside, target_is_directory=True)
    tool = FsApplyMovesTool(scope)
    with pytest.raises(PolicyDenied):
        await tool.run({"root": str(shared), **_moves(("a.txt", "door/a.txt"))}, CTX)
    with pytest.raises(PolicyDenied):
        await tool.run({"root": str(shared), **_moves(("door/victim.txt", "stolen.txt"))}, CTX)
    assert (shared / "a.txt").exists()
    assert (outside / "victim.txt").read_text() == "keep"
    assert sorted(p.name for p in outside.iterdir()) == ["victim.txt"]
    assert not (shared / "stolen.txt").exists()


@needs_symlinks
async def test_apply_moves_moves_the_link_itself_not_its_target(shared: Path, outside: Path, scope: PathScope) -> None:
    (shared / "link.txt").symlink_to(outside / "victim.txt")
    await FsApplyMovesTool(scope).run({"root": str(shared), **_moves(("link.txt", "moved/link.txt"))}, CTX)
    assert (outside / "victim.txt").read_text() == "keep"
    assert (shared / "moved" / "link.txt").is_symlink()
    assert not os.path.lexists(shared / "link.txt")


@needs_symlinks
async def test_apply_moves_handles_a_dangling_link_source(shared: Path, scope: PathScope) -> None:
    (shared / "dead").symlink_to(shared / "nowhere")
    await FsApplyMovesTool(scope).run({"root": str(shared), **_moves(("dead", "x/dead"))}, CTX)
    assert (shared / "x" / "dead").is_symlink()


async def test_apply_moves_never_overwrites_an_existing_destination(shared: Path, scope: PathScope) -> None:
    (shared / "a.txt").write_text("A")
    (shared / "b.txt").write_text("B")
    with pytest.raises(ToolError, match="refusing to overwrite"):
        await FsApplyMovesTool(scope).run({"root": str(shared), **_moves(("a.txt", "b.txt"))}, CTX)
    assert (shared / "a.txt").read_text() == "A" and (shared / "b.txt").read_text() == "B"


async def test_apply_moves_refuses_a_swap_or_chain_through_a_source(shared: Path, scope: PathScope) -> None:
    (shared / "a.txt").write_text("A")
    (shared / "b.txt").write_text("B")
    with pytest.raises(ToolError, match="refusing to overwrite"):
        await FsApplyMovesTool(scope).run({"root": str(shared), **_moves(("a.txt", "b.txt"), ("b.txt", "a.txt"))}, CTX)
    assert (shared / "a.txt").read_text() == "A" and (shared / "b.txt").read_text() == "B"


async def test_apply_moves_refuses_duplicate_destinations(shared: Path, scope: PathScope) -> None:
    (shared / "a.txt").write_text("A")
    (shared / "b.txt").write_text("B")
    with pytest.raises(ValidationFailed, match="same destination"):
        await FsApplyMovesTool(scope).run({"root": str(shared), **_moves(("a.txt", "c.txt"), ("b.txt", "c.txt"))}, CTX)
    assert sorted(p.name for p in shared.iterdir()) == ["a.txt", "b.txt"]


async def test_apply_moves_missing_source_changes_nothing(shared: Path, scope: PathScope) -> None:
    (shared / "a.txt").write_text("A")
    with pytest.raises(ToolError, match="does not exist"):
        await FsApplyMovesTool(scope).run(
            {"root": str(shared), **_moves(("a.txt", "x/a.txt"), ("ghost.txt", "x/g.txt"))}, CTX)
    assert (shared / "a.txt").read_text() == "A"
    assert not (shared / "x").exists()


async def test_apply_moves_onto_itself_is_refused_and_leaves_the_file(shared: Path, scope: PathScope) -> None:
    (shared / "a.txt").write_text("A")
    with pytest.raises((ToolError, ValidationFailed)):
        await FsApplyMovesTool(scope).run({"root": str(shared), **_moves(("a.txt", "a.txt"))}, CTX)
    with pytest.raises((ToolError, ValidationFailed)):
        await FsApplyMovesTool(scope).run({"root": str(shared), **_moves(("a.txt", "./a.txt"))}, CTX)
    assert (shared / "a.txt").read_text() == "A"


async def test_apply_moves_rolls_back_everything_when_a_later_move_fails(shared: Path, scope: PathScope) -> None:
    (shared / "a.txt").write_text("A")
    (shared / "b.txt").write_text("B")
    (shared / "blocker").write_text("I am a file, not a folder")
    with pytest.raises(ToolError, match="put back"):
        await FsApplyMovesTool(scope).run(
            {"root": str(shared), **_moves(("a.txt", "ok/a.txt"), ("b.txt", "blocker/b.txt"))}, CTX)
    assert (shared / "a.txt").read_text() == "A"
    assert (shared / "b.txt").read_text() == "B"
    assert not (shared / "ok" / "a.txt").exists()
    assert (shared / "blocker").read_text() == "I am a file, not a folder"


async def test_apply_moves_rolls_back_when_the_same_source_is_listed_twice(shared: Path, scope: PathScope) -> None:
    (shared / "a.txt").write_text("A")
    with pytest.raises(ToolError, match="put back"):
        await FsApplyMovesTool(scope).run({"root": str(shared), **_moves(("a.txt", "x.txt"), ("a.txt", "y.txt"))}, CTX)
    assert (shared / "a.txt").read_text() == "A"
    assert not (shared / "x.txt").exists() and not (shared / "y.txt").exists()


async def test_apply_moves_moves_whole_folders(shared: Path, scope: PathScope) -> None:
    (shared / "old").mkdir()
    (shared / "old" / "f.txt").write_text("F")
    await FsApplyMovesTool(scope).run({"root": str(shared), **_moves(("old", "archive/old"))}, CTX)
    assert (shared / "archive" / "old" / "f.txt").read_text() == "F"


async def test_apply_moves_works_with_a_subfolder_as_root(shared: Path, scope: PathScope) -> None:
    (shared / "sub").mkdir()
    (shared / "sub" / "a.txt").write_text("A")
    (shared / "top.txt").write_text("T")
    with pytest.raises(PolicyDenied):
        await FsApplyMovesTool(scope).run({"root": str(shared / "sub"), **_moves(("../top.txt", "t.txt"))}, CTX)
    await FsApplyMovesTool(scope).run({"root": str(shared / "sub"), **_moves(("a.txt", "z/a.txt"))}, CTX)
    assert (shared / "sub" / "z" / "a.txt").read_text() == "A"
    assert (shared / "top.txt").read_text() == "T"


async def test_apply_moves_cannot_touch_denied_subfolders(shared: Path) -> None:
    private = shared / "private"
    private.mkdir()
    (private / "secret.txt").write_text("hush")
    scope = PathScope([str(shared)], deny=(str(private),))
    with pytest.raises(PolicyDenied):
        await FsApplyMovesTool(scope).run({"root": str(shared), **_moves(("private/secret.txt", "out.txt"))}, CTX)
    assert (private / "secret.txt").read_text() == "hush"
    assert not (shared / "out.txt").exists()


# --------------------------------------------------------------------------- trash


async def test_trash_moves_to_freedesktop_trash_with_restore_info(
        shared: Path, scope: PathScope, fake_home: Path) -> None:
    (shared / "my file.txt").write_text("precious")
    result = await FsTrashTool(scope).run({"path": str(shared / "my file.txt")}, CTX)
    assert "my file.txt" in result.output
    assert not (shared / "my file.txt").exists()
    base = fake_home / ".local" / "share" / "Trash"
    assert (base / "files" / "my file.txt").read_text() == "precious"  # recoverable, not deleted
    info = (base / "info" / "my file.txt.trashinfo").read_text()
    assert info.startswith("[Trash Info]\n")
    path_line = next(line for line in info.splitlines() if line.startswith("Path="))
    assert unquote(path_line[5:]) == str((shared / "my file.txt").resolve())
    assert any(line.startswith("DeletionDate=") for line in info.splitlines())


async def test_trash_honours_xdg_data_home(
        shared: Path, scope: PathScope, fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    (shared / "a.txt").write_text("A")
    await FsTrashTool(scope).run({"path": str(shared / "a.txt")}, CTX)
    assert (xdg / "Trash" / "files" / "a.txt").read_text() == "A"
    assert (xdg / "Trash" / "info" / "a.txt.trashinfo").is_file()
    assert not (fake_home / ".local").exists()


async def test_trash_uses_the_mac_trash_when_present(shared: Path, scope: PathScope, fake_home: Path) -> None:
    (fake_home / ".Trash").mkdir()
    (shared / "a.txt").write_text("A")
    await FsTrashTool(scope).run({"path": str(shared / "a.txt")}, CTX)
    assert (fake_home / ".Trash" / "a.txt").read_text() == "A"
    assert not (fake_home / ".local").exists()


async def test_trash_never_overwrites_an_item_already_in_the_trash(shared: Path, scope: PathScope, fake_home: Path) -> None:
    tool = FsTrashTool(scope)
    for content in ("one", "two", "three"):
        (shared / "a.txt").write_text(content)
        await tool.run({"path": str(shared / "a.txt")}, CTX)
    files = fake_home / ".local" / "share" / "Trash" / "files"
    assert sorted(p.name for p in files.iterdir()) == ["a-1.txt", "a-2.txt", "a.txt"]
    assert {p.read_text() for p in files.iterdir()} == {"one", "two", "three"}
    infos = sorted(p.name for p in (files.parent / "info").iterdir())
    assert infos == ["a-1.txt.trashinfo", "a-2.txt.trashinfo", "a.txt.trashinfo"]


async def test_trash_moves_a_whole_folder_with_its_contents(shared: Path, scope: PathScope, fake_home: Path) -> None:
    (shared / "dir" / "inner").mkdir(parents=True)
    (shared / "dir" / "inner" / "f.txt").write_text("deep")
    await FsTrashTool(scope).run({"path": str(shared / "dir")}, CTX)
    assert not (shared / "dir").exists()
    trashed = fake_home / ".local" / "share" / "Trash" / "files" / "dir" / "inner" / "f.txt"
    assert trashed.read_text() == "deep"


async def test_trash_refuses_a_shared_folder_itself(shared: Path, scope: PathScope, fake_home: Path) -> None:
    (shared / "keep.txt").write_text("keep")
    with pytest.raises(PolicyDenied, match="cannot be trashed"):
        await FsTrashTool(scope).run({"path": str(shared)}, CTX)
    with pytest.raises(PolicyDenied, match="cannot be trashed"):
        await FsTrashTool(scope).run({"path": str(shared / "sub" / "..")}, CTX)
    assert (shared / "keep.txt").read_text() == "keep"
    assert not (fake_home / ".local").exists()


async def test_trash_missing_path_is_a_tool_error_and_touches_nothing(shared: Path, scope: PathScope, fake_home: Path) -> None:
    with pytest.raises(ToolError, match="does not exist"):
        await FsTrashTool(scope).run({"path": str(shared / "ghost.txt")}, CTX)
    assert not (fake_home / ".local").exists()


async def test_trash_requires_a_path(scope: PathScope) -> None:
    with pytest.raises(ValidationFailed):
        await FsTrashTool(scope).run({}, CTX)


async def test_trash_outside_the_shared_folder_is_denied_and_the_file_survives(
        outside: Path, scope: PathScope, fake_home: Path) -> None:
    with pytest.raises(PolicyDenied):
        await FsTrashTool(scope).run({"path": str(outside / "victim.txt")}, CTX)
    assert (outside / "victim.txt").read_text() == "keep"
    assert not (fake_home / ".local").exists()


async def test_trash_reports_a_failed_move_as_a_tool_error(
        shared: Path, scope: PathScope, fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (shared / "a.txt").write_text("A")

    def boom(src: str, dst: str) -> None:
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(fs.shutil, "move", boom)
    with pytest.raises(ToolError, match="could not move to the Trash"):
        await FsTrashTool(scope).run({"path": str(shared / "a.txt")}, CTX)
    assert (shared / "a.txt").read_text() == "A"
