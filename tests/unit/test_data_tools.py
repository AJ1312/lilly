"""data.profile, notes.search/read and memory.search/write: scope, limits, labels and hostile inputs."""
from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import openpyxl
import pytest

from lilly.domain.errors import PolicyDenied, ToolError, ValidationFailed
from lilly.domain.labels import Label
from lilly.domain.policy import PathScope
from lilly.domain.ports import ToolContext
from lilly.domain.tools_registry import DEFAULT_TOOLS
from lilly.store.db import Database
from lilly.store.memory import MAX_TEXT, add_memory
from lilly.store.spaces import create_page, create_space
from lilly.tools.data import (
    DEFAULT_ROWS,
    MAX_COLUMNS,
    MAX_ROWS,
    DataProfileTool,
    _kind,
    profile_rows,
)
from lilly.tools.memory import MemorySearchTool, MemoryWriteTool
from lilly.tools.notes import MAX_NOTE_CHARS, NotesReadTool, NotesSearchTool
from tests.helpers import Clock

CTX = ToolContext("t", "s1", 5.0, lambda: False)


# --- data.profile ------------------------------------------------------------------------------------------------


@pytest.fixture
def shared(tmp_path: Path) -> Path:
    root = tmp_path / "shared"
    root.mkdir()
    return root


@pytest.fixture
def tool(shared: Path) -> DataProfileTool:
    return DataProfileTool(PathScope([str(shared)]))


async def profile(tool: DataProfileTool, path: Path, **extra: object) -> dict[str, Any]:
    res = await tool.run({"path": str(path), **extra}, CTX)
    assert res.label is Label.PERSONAL and res.untrusted is False
    out = json.loads(res.output)
    assert out["file"] == path.name
    return out  # type: ignore[no-any-return]


def cols(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["name"]: c for c in report["columns"]}


def test_registry_entries_match_the_tools() -> None:
    for name in ("data.profile", "notes.search", "notes.read", "memory.search"):
        spec = DEFAULT_TOOLS[name]
        assert spec.reads_label is Label.PERSONAL and int(spec.risk) == 0 and not spec.untrusted and not spec.egress
    assert int(DEFAULT_TOOLS["memory.write"].risk) == 1
    assert DataProfileTool.name == "data.profile" and DEFAULT_TOOLS["data.profile"].path_args == ("path",)


def test_kind_classification() -> None:
    assert [_kind(v) for v in ("12", "-3", "+4", " 7 ")] == ["int"] * 4
    assert [_kind(v) for v in ("1.5", "1e3", "-.5")] == ["float"] * 3
    assert [_kind(v) for v in ("true", "FALSE", " Yes ", "no")] == ["bool"] * 4
    assert [_kind(v) for v in ("abc", "=SUM(A1:A2)", "12abc", "1,5", "")] == ["text"] * 5
    assert _kind("１２３") == "int"  # full-width digits are accepted by int() and mean the same number


def test_profile_rows_empty_and_header_only() -> None:
    assert profile_rows(iter([]), 10) == {"rows": 0, "columns": []}
    rep = profile_rows(iter([["a", "b"]]), 10)
    assert rep["rows"] == 0 and [c["type"] for c in rep["columns"]] == ["empty", "empty"]


def test_profile_rows_types_blanks_duplicates_and_odd_values() -> None:
    rows = iter([
        ["id", "", "score"],
        ["1", "x", "1.5"],
        ["2", "y", ""],
        ["3", "z", "oops"],
        ["3", "z", "oops"],       # exact duplicate row
        ["4"],                    # short row: the missing cells count as blank
        ["5", "w", "2.5", "ignored extra cell"],
    ])
    rep = profile_rows(rows, 100)
    assert rep["rows"] == 6 and rep["duplicate_rows"] == 1 and rep["row_limit"] == 100
    c = cols(rep)
    assert c["id"]["type"] == "int" and c["id"]["blank"] == 0 and c["id"]["odd_values"] == []
    assert c["column2"]["type"] == "text" and c["column2"]["blank"] == 1  # blank header gets a stable name
    assert c["score"]["type"] == "float" and c["score"]["blank"] == 2 and c["score"]["odd_values"] == ["oops", "oops"]
    assert len(rep["columns"]) == 3  # the extra cell does not create a column


def test_profile_rows_row_limit_counts_data_rows_only() -> None:
    rows = iter([["n"]] + [[str(i)] for i in range(50)])
    rep = profile_rows(rows, 7)
    assert rep["rows"] == 7 and rep["row_limit"] == 7
    assert rep["columns"][0]["blank"] == 0


def test_profile_rows_caps_columns() -> None:
    rep = profile_rows(iter([[f"c{i}" for i in range(MAX_COLUMNS + 50)], ["1"] * (MAX_COLUMNS + 50)]), 10)
    assert len(rep["columns"]) == MAX_COLUMNS


def test_profile_rows_truncates_huge_cells_and_bounds_samples() -> None:
    huge = "A" * 2_000_000
    rows = iter([["v"]] + [["1"]] * 20 + [[huge]] * 20)
    rep = profile_rows(rows, 100)
    odd = rep["columns"][0]["odd_values"]
    assert rep["columns"][0]["type"] == "int"
    assert len(odd) == 5 and all(len(v) == 60 for v in odd)  # at most 5 samples, 60 characters each
    assert len(json.dumps(rep)) < 2000


def test_profile_rows_never_interprets_formulas_or_markup() -> None:
    evil = ["=cmd|' /C calc'!A0", "@SUM(1+1)", "+1+1", "-2+3", "<script>alert(1)</script>", "'; DROP TABLE x;--"]
    rep = profile_rows(iter([["v"]] + [["1"]] * 10 + [[e] for e in evil]), 100)
    odd = rep["columns"][0]["odd_values"]
    assert odd == evil[:5]  # reported verbatim (first five samples) as data, never evaluated


def test_profile_rows_dominant_type_wins_ties_by_first_seen() -> None:
    rep = profile_rows(iter([["v"], ["1"], ["a"], ["2"], ["b"]]), 10)
    assert rep["columns"][0]["type"] == "int"
    assert rep["columns"][0]["odd_values"] == ["a", "b"]


async def test_profile_a_csv_file(tool: DataProfileTool, shared: Path) -> None:
    f = shared / "people.csv"
    f.write_text("name,age,active\nAda,36,yes\nBob,,no\nCy,x,true\nAda,36,yes\n", encoding="utf-8")
    rep = await profile(tool, f)
    assert rep["rows"] == 4 and rep["duplicate_rows"] == 1 and rep["row_limit"] == DEFAULT_ROWS
    c = cols(rep)
    assert (c["name"]["type"], c["age"]["type"], c["active"]["type"]) == ("text", "int", "bool")
    assert c["age"]["blank"] == 1 and c["age"]["odd_values"] == ["x"]


async def test_profile_detects_other_delimiters(tool: DataProfileTool, shared: Path) -> None:
    (shared / "semi.csv").write_text("a;b;c\n1;2;3\n4;5;6\n")
    (shared / "tabs.tsv").write_text("a\tb\n1\t2\n3\t4\n")
    (shared / "pipes.txt").write_text("a|b|c\n1|2|3\n4|5|6\n")
    for name, ncols in (("semi.csv", 3), ("tabs.tsv", 2), ("pipes.txt", 3)):
        rep = await profile(tool, shared / name)
        assert rep["rows"] == 2 and len(rep["columns"]) == ncols


async def test_profile_handles_bom_quotes_unicode_and_embedded_newlines(tool: DataProfileTool, shared: Path) -> None:
    f = shared / "u.csv"
    f.write_bytes("﻿nom,note\n\"Zoë\",\"line1\nline2, with comma\"\n\"日本\",\"🎵\"\n".encode())
    rep = await profile(tool, f)
    assert rep["rows"] == 2
    assert [c["name"] for c in rep["columns"]] == ["nom", "note"]  # the BOM is not part of the first header


async def test_profile_survives_invalid_utf8_and_nul_bytes(tool: DataProfileTool, shared: Path) -> None:
    f = shared / "bad.csv"
    f.write_bytes(b"a,b\n\xff\xfe,1\nok\x00x,2\n")
    rep = await profile(tool, f)
    assert rep["rows"] == 2


async def test_profile_empty_and_blank_files(tool: DataProfileTool, shared: Path) -> None:
    (shared / "empty.csv").write_text("")
    (shared / "blank.csv").write_text("\n\n\n")
    assert (await profile(tool, shared / "empty.csv"))["rows"] == 0
    await profile(tool, shared / "blank.csv")  # a file of only blank lines must not crash the profile


async def test_blank_lines_are_not_data_rows(tool: DataProfileTool, shared: Path) -> None:
    f = shared / "trailing.csv"
    f.write_text("a,b\n1,2\n3,4\n\n\n")
    rep = await profile(tool, f)
    assert rep["rows"] == 2 and rep["duplicate_rows"] == 0


async def test_profile_header_only_csv(tool: DataProfileTool, shared: Path) -> None:
    (shared / "h.csv").write_text("a,b,c\n")
    rep = await profile(tool, shared / "h.csv")
    assert rep["rows"] == 0 and [c["type"] for c in rep["columns"]] == ["empty"] * 3


async def test_profile_max_rows_is_clamped(tool: DataProfileTool, shared: Path) -> None:
    f = shared / "n.csv"
    f.write_text("n\n" + "\n".join(str(i) for i in range(30)) + "\n")
    assert (await profile(tool, f, max_rows=5))["rows"] == 5
    assert (await profile(tool, f, max_rows=0))["rows"] == 1  # clamped up to the minimum
    assert (await profile(tool, f, max_rows=-10))["row_limit"] == 1
    assert (await profile(tool, f, max_rows=10**12))["row_limit"] == MAX_ROWS
    assert (await profile(tool, f, max_rows="7"))["rows"] == 7
    assert (await profile(tool, f, max_rows=""))["row_limit"] == DEFAULT_ROWS


@pytest.mark.parametrize("bad", ["many", True, [1], {"a": 1}, float("nan")])
async def test_profile_rejects_non_numeric_max_rows(tool: DataProfileTool, shared: Path, bad: object) -> None:
    (shared / "n.csv").write_text("n\n1\n")
    with pytest.raises(ValidationFailed):
        await tool.run({"path": str(shared / "n.csv"), "max_rows": bad}, CTX)


@pytest.mark.parametrize("args", [{}, {"path": ""}, {"path": "   "}, {"path": 5}, {"path": None}, {"path": ["a"]}])
async def test_profile_requires_a_text_path(tool: DataProfileTool, args: dict[str, object]) -> None:
    with pytest.raises(ValidationFailed):
        await tool.run(args, CTX)


async def test_profile_refuses_paths_outside_the_shared_folder(tool: DataProfileTool, shared: Path,
                                                               tmp_path: Path) -> None:
    outside = tmp_path / "private.csv"
    outside.write_text("secret\n1\n")
    for raw in (str(outside), str(shared / ".." / "private.csv"), "/etc/passwd", "/etc/passwd.csv", "~/x.csv",
                "relative.csv", "bad\x00.csv"):
        with pytest.raises(PolicyDenied):
            await tool.run({"path": raw}, CTX)


async def test_profile_refuses_symlinks_that_escape_the_shared_folder(tool: DataProfileTool, shared: Path,
                                                                      tmp_path: Path) -> None:
    outside = tmp_path / "private.csv"
    outside.write_text("secret\n1\n")
    (shared / "link.csv").symlink_to(outside)
    (shared / "dirlink").symlink_to(tmp_path)
    with pytest.raises(PolicyDenied):
        await tool.run({"path": str(shared / "link.csv")}, CTX)
    with pytest.raises(PolicyDenied):
        await tool.run({"path": str(shared / "dirlink" / "private.csv")}, CTX)


async def test_profile_denies_the_deny_listed_folder_inside_the_share(shared: Path) -> None:
    private = shared / "lilly-data"
    private.mkdir()
    (private / "x.csv").write_text("a\n1\n")
    t = DataProfileTool(PathScope([str(shared)], deny=[str(private)]))
    with pytest.raises(PolicyDenied):
        await t.run({"path": str(private / "x.csv")}, CTX)


async def test_profile_rejects_other_file_types_and_missing_files(tool: DataProfileTool, shared: Path) -> None:
    for name in ("a.exe", "a.json", "a.xlsm", "a.xls", "a", "a.csv.bak", "a.pdf"):
        (shared / name).write_text("x")
        with pytest.raises(ValidationFailed):
            await tool.run({"path": str(shared / name)}, CTX)
    with pytest.raises(ToolError, match="not found"):
        await tool.run({"path": str(shared / "missing.csv")}, CTX)
    (shared / "dir.csv").mkdir()
    with pytest.raises(ToolError, match="not found"):
        await tool.run({"path": str(shared / "dir.csv")}, CTX)


async def test_profile_suffix_check_is_case_insensitive(tool: DataProfileTool, shared: Path) -> None:
    (shared / "UP.CSV").write_text("a\n1\n")
    assert (await profile(tool, shared / "UP.CSV"))["rows"] == 1


async def test_profile_reports_only_the_file_name_not_the_directory(tool: DataProfileTool, shared: Path) -> None:
    (shared / "n.csv").write_text("a\n1\n")
    res = await tool.run({"path": str(shared / "n.csv")}, CTX)
    assert str(shared) not in res.output


async def test_a_single_cell_over_the_csv_field_limit_is_a_clean_tool_error(tool: DataProfileTool,
                                                                            shared: Path) -> None:
    f = shared / "huge.csv"
    f.write_text("a,b\n1," + "x" * 300_000 + "\n")
    with pytest.raises(ToolError, match="could not read"):
        await tool.run({"path": str(f)}, CTX)


async def test_a_large_file_is_only_read_up_to_the_row_limit(tool: DataProfileTool, shared: Path) -> None:
    f = shared / "big.csv"
    f.write_text("n,t\n" + "".join(f"{i},row{i}\n" for i in range(5000)))
    rep = await profile(tool, f, max_rows=100)
    assert rep["rows"] == 100 and rep["duplicate_rows"] == 0


def _xlsx(path: Path, rows: list[list[Any]], *, extra_sheet: list[list[Any]] | None = None) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    for r in rows:
        ws.append(r)
    if extra_sheet is not None:
        ws2 = wb.create_sheet("Other")
        for r in extra_sheet:
            ws2.append(r)
    wb.save(path)
    wb.close()


async def test_profile_an_xlsx_file(tool: DataProfileTool, shared: Path) -> None:
    f = shared / "book.xlsx"
    _xlsx(f, [["item", "qty", "price"], ["pen", 3, 1.5], ["ink", None, 2.25], ["pad", "n/a", 3.0], ["pen", 3, 1.5]])
    rep = await profile(tool, f)
    assert rep["rows"] == 4 and rep["duplicate_rows"] == 1
    c = cols(rep)
    assert (c["item"]["type"], c["qty"]["type"], c["price"]["type"]) == ("text", "int", "float")
    assert c["qty"]["blank"] == 1 and c["qty"]["odd_values"] == ["n/a"]


async def test_xlsx_formulas_are_reported_as_cached_values_never_evaluated(tool: DataProfileTool,
                                                                          shared: Path) -> None:
    f = shared / "formulas.xlsx"
    _xlsx(f, [["a", "b"], [1, "=1+1"], [2, "=HYPERLINK(\"http://evil.example\",\"x\")"], [3, "=cmd|' /C calc'!A0"]])
    rep = await profile(tool, f)
    # openpyxl writes no cached value, so a formula cell has no value to profile: it counts as blank
    assert cols(rep)["b"]["blank"] == 3
    assert "evil.example" not in json.dumps(rep) and "cmd" not in json.dumps(rep)


async def test_xlsx_only_the_active_sheet_is_profiled(tool: DataProfileTool, shared: Path) -> None:
    f = shared / "two.xlsx"
    _xlsx(f, [["first"], [1], [2]], extra_sheet=[["second"], ["a"], ["b"], ["c"]])
    rep = await profile(tool, f)
    assert [c["name"] for c in rep["columns"]] == ["first"] and rep["rows"] == 2


async def test_xlsx_huge_cell_unicode_and_empty_workbook(tool: DataProfileTool, shared: Path) -> None:
    f = shared / "huge.xlsx"
    _xlsx(f, [["v"], [1], [2], ["Ж" * 30_000], ["🎵日本"]])
    rep = await profile(tool, f)
    odd = cols(rep)["v"]["odd_values"]
    assert len(odd[0]) == 60 and odd[1] == "🎵日本"
    empty = shared / "empty.xlsx"
    _xlsx(empty, [])
    assert (await profile(tool, empty))["rows"] == 0


async def test_corrupt_or_fake_xlsx_is_a_clean_tool_error(tool: DataProfileTool, shared: Path) -> None:
    (shared / "fake.xlsx").write_text("this is not a zip file")
    (shared / "zero.xlsx").write_bytes(b"")
    for name in ("fake.xlsx", "zero.xlsx"):
        with pytest.raises(ToolError, match="could not read"):
            await tool.run({"path": str(shared / name)}, CTX)


async def test_profile_does_not_block_the_event_loop(tool: DataProfileTool, shared: Path) -> None:
    f = shared / "n.csv"
    f.write_text("n\n1\n")
    ticks: list[int] = []

    async def ticker() -> None:
        ticks.append(1)

    await asyncio.gather(tool.run({"path": str(f)}, CTX), ticker())
    assert ticks == [1]


# --- notes and memory --------------------------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    d = Database(tmp_path / "lilly.db")
    try:
        yield d
    finally:
        d.close()


async def _add_page(db: Database, pid: str, title: str, content: str, space: str = "s") -> None:
    def w(con):  # type: ignore[no-untyped-def]
        from lilly.store.spaces import get_space

        if get_space(con, space) is None:
            create_space(con, space, space.upper(), "", 1.0)
        create_page(con, pid, space, title, content, 1.0)

    await db.write(w)


async def test_notes_search_returns_clean_snippets_and_is_personal(db: Database) -> None:
    await _add_page(db, "n1", "Trip plan", "<h1>Lisbon</h1><script>steal()</script><p>pack <b>sunscreen</b></p>")
    res = await NotesSearchTool(db).run({"query": "sunscreen"}, CTX)
    hits = json.loads(res.output)
    assert res.label is Label.PERSONAL and res.untrusted is False
    assert [h["id"] for h in hits] == ["n1"] and hits[0]["title"] == "Trip plan"
    assert "sunscreen" in hits[0]["snippet"] and "<" not in hits[0]["snippet"] and "steal" not in hits[0]["snippet"]


async def test_notes_search_without_hits_is_public_and_empty(db: Database) -> None:
    await _add_page(db, "n1", "Trip plan", "lisbon")
    for q in ("nothingmatches", "the of and"):
        res = await NotesSearchTool(db).run({"query": q}, CTX)
        assert json.loads(res.output) == [] and res.label is Label.PUBLIC


async def test_notes_search_caps_results_and_snippet_length(db: Database) -> None:
    for i in range(12):
        await _add_page(db, f"n{i}", f"Standup {i}", "agenda " + "word " * 500)
    hits = json.loads((await NotesSearchTool(db).run({"query": "agenda"}, CTX)).output)
    assert len(hits) == 8
    assert all(len(h["snippet"]) <= 200 for h in hits)


async def test_notes_search_spans_all_spaces_and_validates_the_query(db: Database) -> None:
    await _add_page(db, "a", "Alpha", "budget", space="s1")
    await _add_page(db, "b", "Beta", "budget", space="s2")
    hits = json.loads((await NotesSearchTool(db).run({"query": "budget"}, CTX)).output)
    assert {h["id"] for h in hits} == {"a", "b"}
    for bad in ({}, {"query": ""}, {"query": "  "}, {"query": 3}, {"query": "q" * 301}):
        with pytest.raises(ValidationFailed):
            await NotesSearchTool(db).run(bad, CTX)


async def test_notes_search_survives_hostile_fts_syntax(db: Database) -> None:
    await _add_page(db, "n1", "Plain", "plain text")
    for q in ('"', "NEAR(", "title:", "* OR *", "a AND", "\x00", "'; DROP TABLE pages;--"):
        res = await NotesSearchTool(db).run({"query": q}, CTX)
        json.loads(res.output)
    assert json.loads((await NotesSearchTool(db).run({"query": "plain"}, CTX)).output)[0]["id"] == "n1"


async def test_notes_read_returns_title_and_plain_text(db: Database) -> None:
    await _add_page(db, "n1", "Recipe", "<p>Mix <i>flour</i></p><style>p{}</style><p>Bake</p>")
    res = await NotesReadTool(db).run({"id": "n1"}, CTX)
    assert res.output.startswith("# Recipe\nrevision: 1\n\n") and res.label is Label.PERSONAL and not res.untrusted
    assert "Mix flour" in res.output and "Bake" in res.output and "<" not in res.output and "p{}" not in res.output


async def test_notes_read_truncates_huge_notes(db: Database) -> None:
    await _add_page(db, "big", "Big", "x" * 150_000)
    res = await NotesReadTool(db).run({"id": "big"}, CTX)
    assert len(res.output) == len("# Big\nrevision: 1\n\n") + MAX_NOTE_CHARS


async def test_notes_read_unknown_and_invalid_ids(db: Database) -> None:
    with pytest.raises(ToolError, match="no note"):
        await NotesReadTool(db).run({"id": "ghost"}, CTX)
    with pytest.raises(ToolError):
        await NotesReadTool(db).run({"id": "' OR '1'='1"}, CTX)
    for bad in ({}, {"id": ""}, {"id": 5}, {"id": "i" * 65}):
        with pytest.raises(ValidationFailed):
            await NotesReadTool(db).run(bad, CTX)


async def test_notes_read_empty_content_and_unicode_title(db: Database) -> None:
    await _add_page(db, "e", "空のノート 🎵", "")
    res = await NotesReadTool(db).run({"id": "e"}, CTX)
    assert res.output == "# 空のノート 🎵\nrevision: 1\n\n"


async def test_notes_tools_cannot_change_anything(db: Database) -> None:
    await _add_page(db, "n1", "Keep", "<p>body</p>")
    await NotesReadTool(db).run({"id": "n1"}, CTX)
    await NotesSearchTool(db).run({"query": "body"}, CTX)
    assert db.reader.execute("SELECT COUNT(*), MAX(revision) FROM pages").fetchone() == (1, 1)


# memory


async def test_memory_write_stores_an_agent_memory_and_reports_it(db: Database) -> None:
    tool = MemoryWriteTool(db, Clock(42.0))
    res = await tool.run({"text": "  Hardik prefers dark mode  "}, CTX)
    assert res.output.startswith("Remembered (#") and res.label is Label.PUBLIC and not res.untrusted
    row = db.reader.execute("SELECT text, source, label, created_at FROM memory").fetchone()
    assert row == ("Hardik prefers dark mode", "agent", int(Label.PERSONAL), 42.0)


async def test_memory_write_dedupes_exact_text_after_trimming(db: Database) -> None:
    tool = MemoryWriteTool(db, Clock())
    await tool.run({"text": "likes tea"}, CTX)
    again = await tool.run({"text": "   likes tea\n"}, CTX)
    assert again.output == "Already remembered."
    assert db.reader.execute("SELECT COUNT(*) FROM memory").fetchone()[0] == 1
    await tool.run({"text": "Likes tea"}, CTX)  # a different string is a different memory
    assert db.reader.execute("SELECT COUNT(*) FROM memory").fetchone()[0] == 2


async def test_memory_write_validation(db: Database) -> None:
    tool = MemoryWriteTool(db, Clock())
    for bad in ({}, {"text": ""}, {"text": " \n\t "}, {"text": 5}, {"text": None}, {"text": "x" * (MAX_TEXT + 1)}):
        with pytest.raises(ValidationFailed):
            await tool.run(bad, CTX)
    assert db.reader.execute("SELECT COUNT(*) FROM memory").fetchone()[0] == 0
    ok = await tool.run({"text": "y" * MAX_TEXT}, CTX)  # the boundary itself is accepted
    assert ok.output.startswith("Remembered")


async def test_memory_write_accepts_unicode_and_injection_text_as_plain_data(db: Database) -> None:
    tool = MemoryWriteTool(db, Clock())
    text = "'); DROP TABLE memory;-- 日本語 🎵 ‮"
    await tool.run({"text": text}, CTX)
    assert db.reader.execute("SELECT text FROM memory").fetchone()[0] == text.strip()


async def test_memory_search_labels_results_by_the_most_sensitive_hit(db: Database) -> None:
    await db.write(lambda con: add_memory(con, "favourite colour is teal", 1.0, label=Label.PUBLIC))
    res = await MemorySearchTool(db).run({"query": "colour"}, CTX)
    assert res.label is Label.PUBLIC and [h["text"] for h in json.loads(res.output)] == ["favourite colour is teal"]
    await db.write(lambda con: add_memory(con, "colour of my front door is red", 2.0, label=Label.PERSONAL))
    res = await MemorySearchTool(db).run({"query": "colour"}, CTX)
    assert res.label is Label.PERSONAL and len(json.loads(res.output)) == 2


async def test_memory_search_never_returns_secret_memories(db: Database) -> None:
    await db.write(lambda con: add_memory(con, "wifi password is hunter2", 1.0, label=Label.SECRET))
    await db.write(lambda con: add_memory(con, "wifi router is in the hall", 2.0, label=Label.PERSONAL))
    res = await MemorySearchTool(db).run({"query": "wifi password"}, CTX)
    assert "hunter2" not in res.output
    assert [h["text"] for h in json.loads(res.output)] == ["wifi router is in the hall"]


async def test_memory_search_without_hits_is_public_and_returns_ids(db: Database) -> None:
    res = await MemorySearchTool(db).run({"query": "anything"}, CTX)
    assert json.loads(res.output) == [] and res.label is Label.PUBLIC
    await MemoryWriteTool(db, Clock()).run({"text": "owns a bicycle"}, CTX)
    hit = json.loads((await MemorySearchTool(db).run({"query": "bicycle"}, CTX)).output)[0]
    assert set(hit) == {"id", "text"} and isinstance(hit["id"], int)


async def test_memory_search_validation_and_hostile_queries(db: Database) -> None:
    for bad in ({}, {"query": ""}, {"query": 1}, {"query": "q" * 301}):
        with pytest.raises(ValidationFailed):
            await MemorySearchTool(db).run(bad, CTX)
    await MemoryWriteTool(db, Clock()).run({"text": "plain fact"}, CTX)
    for q in ('"', "NEAR(", "text:", "* OR *", "-"):
        assert isinstance(json.loads((await MemorySearchTool(db).run({"query": q}, CTX)).output), list)


async def test_memory_search_caps_results(db: Database) -> None:
    for i in range(15):
        await db.write(lambda con, i=i: add_memory(con, f"hobby number {i}: chess", float(i)))
    assert len(json.loads((await MemorySearchTool(db).run({"query": "chess"}, CTX)).output)) == 10


async def test_concurrent_identical_memory_writes_store_one_memory(db: Database) -> None:
    gate, started = threading.Event(), threading.Event()

    def hold(con: object) -> None:
        started.set()
        gate.wait(10)

    blocker = db._writer.submit(hold)  # type: ignore[arg-type]
    assert started.wait(10)
    tool = MemoryWriteTool(db, Clock())
    jobs = [asyncio.ensure_future(tool.run({"text": "same fact"}, CTX)) for _ in range(2)]
    for _ in range(5):
        await asyncio.sleep(0)  # both calls pass their duplicate check while the writer is busy
    gate.set()
    await asyncio.gather(*jobs)
    blocker.result(10)
    assert db.reader.execute("SELECT COUNT(*) FROM memory").fetchone()[0] == 1
