"""Spaces and pages: validation, optimistic concurrency, isolation between spaces, cascades and search."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from lilly.domain.errors import ConflictError, NotFound, ValidationFailed
from lilly.store.connection import open_db
from lilly.store.spaces import (
    MAX_CONTENT,
    MAX_SPACE_NAME,
    MAX_TITLE,
    _check_parent,
    create_page,
    create_space,
    delete_page,
    delete_space,
    get_page,
    get_page_any,
    get_space,
    list_pages,
    list_spaces,
    search_pages,
    update_page,
    update_space,
)


@pytest.fixture
def con(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = open_db(tmp_path / "spaces.db")
    try:
        yield c
    finally:
        c.close()


def _two_spaces(con: sqlite3.Connection) -> None:
    create_space(con, "sa", "Alpha", "", 1.0)
    create_space(con, "sb", "Beta", "", 2.0)


# --- spaces -----------------------------------------------------------------------------------------------------


def test_create_space_strips_and_stores(con: sqlite3.Connection) -> None:
    row = create_space(con, "s1", "  Réunion 📓  ", "  about things  ", 5.0)
    assert (row.name, row.description, row.created_at) == ("Réunion 📓", "about things", 5.0)
    assert get_space(con, "s1") == row
    assert get_space(con, "missing") is None


@pytest.mark.parametrize("name", ["", "   ", "\t\n", "x" * (MAX_SPACE_NAME + 1)])
def test_create_space_rejects_bad_names_and_stores_nothing(con: sqlite3.Connection, name: str) -> None:
    with pytest.raises(ValidationFailed):
        create_space(con, "s1", name, "", 1.0)
    assert list_spaces(con) == []


def test_create_space_accepts_the_longest_name_and_truncates_description(con: sqlite3.Connection) -> None:
    row = create_space(con, "s1", "n" * MAX_SPACE_NAME, "d" * 5000, 1.0)
    assert len(row.name) == MAX_SPACE_NAME
    assert len(row.description) == 1000


def test_whitespace_is_stripped_before_the_length_check(con: sqlite3.Connection) -> None:
    assert create_space(con, "s1", " " * 50 + "n" * MAX_SPACE_NAME + " " * 50, "", 1.0).name == "n" * MAX_SPACE_NAME


def test_duplicate_space_id_is_rejected(con: sqlite3.Connection) -> None:
    create_space(con, "s1", "One", "", 1.0)
    with pytest.raises(sqlite3.IntegrityError):
        create_space(con, "s1", "Other", "", 2.0)
    assert [s.name for s in list_spaces(con)] == ["One"]


def test_list_spaces_is_ordered_by_creation(con: sqlite3.Connection) -> None:
    create_space(con, "late", "Late", "", 9.0)
    create_space(con, "early", "Early", "", 1.0)
    assert [s.id for s in list_spaces(con)] == ["early", "late"]


def test_update_space_changes_only_what_is_given(con: sqlite3.Connection) -> None:
    create_space(con, "s1", "Name", "desc", 1.0)
    assert update_space(con, "s1", name="  New  ").description == "desc"
    row = update_space(con, "s1", description="  fresh  ")
    assert (row.name, row.description) == ("New", "fresh")
    assert update_space(con, "s1") == row  # no-op


def test_update_space_with_bad_name_changes_nothing(con: sqlite3.Connection) -> None:
    create_space(con, "s1", "Name", "desc", 1.0)
    with pytest.raises(ValidationFailed):
        update_space(con, "s1", name="  ", description="should not land")
    row = get_space(con, "s1")
    assert row is not None and (row.name, row.description) == ("Name", "desc")


def test_update_space_unknown_is_not_found(con: sqlite3.Connection) -> None:
    with pytest.raises(NotFound):
        update_space(con, "nope", name="x")


def test_update_space_truncates_long_description(con: sqlite3.Connection) -> None:
    create_space(con, "s1", "Name", "", 1.0)
    assert len(update_space(con, "s1", description="z" * 2000).description) == 1000


def test_delete_space_cascades_to_its_pages_and_search_index(con: sqlite3.Connection) -> None:
    _two_spaces(con)
    create_page(con, "pa", "sa", "Gardenia", "scented flower", 1.0)
    create_page(con, "pb", "sb", "Gardenia", "scented flower", 1.0)
    delete_space(con, "sa")
    assert get_space(con, "sa") is None
    assert get_page_any(con, "pa") is None
    assert [p.id for p in search_pages(con, "gardenia")] == ["pb"]  # the other space is untouched
    assert get_page(con, "sb", "pb") is not None


def test_delete_space_unknown_is_not_found(con: sqlite3.Connection) -> None:
    with pytest.raises(NotFound):
        delete_space(con, "nope")


# --- pages ------------------------------------------------------------------------------------------------------


def test_create_page_basics(con: sqlite3.Connection) -> None:
    create_space(con, "s", "S", "", 1.0)
    page = create_page(con, "p1", "s", "  Title  ", "<p>body</p>", 3.0)
    assert (page.title, page.content, page.revision) == ("Title", "<p>body</p>", 1)
    assert (page.created_at, page.updated_at, page.parent_id, page.space_id) == (3.0, 3.0, None, "s")


@pytest.mark.parametrize("title,content", [("", "x"), ("   ", "x"), ("t" * (MAX_TITLE + 1), "x"),
                                           ("t", "c" * (MAX_CONTENT + 1))])
def test_create_page_rejects_out_of_bounds_input(con: sqlite3.Connection, title: str, content: str) -> None:
    create_space(con, "s", "S", "", 1.0)
    with pytest.raises(ValidationFailed):
        create_page(con, "p", "s", title, content, 1.0)
    assert list_pages(con, "s") == []


def test_create_page_accepts_the_exact_limits(con: sqlite3.Connection) -> None:
    create_space(con, "s", "S", "", 1.0)
    page = create_page(con, "p", "s", "t" * MAX_TITLE, "c" * MAX_CONTENT, 1.0)
    assert len(page.title) == MAX_TITLE and len(page.content) == MAX_CONTENT


def test_create_page_accepts_empty_content_and_unicode(con: sqlite3.Connection) -> None:
    create_space(con, "s", "S", "", 1.0)
    assert create_page(con, "p1", "s", "Empty", "", 1.0).content == ""
    uni = create_page(con, "p2", "s", "日本語のメモ 🎵", "Ünïcødé \u0000 text", 1.0)
    assert get_page(con, "s", "p2") == uni


def test_create_page_in_missing_space_is_not_found(con: sqlite3.Connection) -> None:
    with pytest.raises(NotFound):
        create_page(con, "p", "ghost", "t", "c", 1.0)


def test_create_page_validates_bounds_before_space_lookup(con: sqlite3.Connection) -> None:
    with pytest.raises(ValidationFailed):
        create_page(con, "p", "ghost", "", "c", 1.0)


def test_nested_pages_and_parent_validation(con: sqlite3.Connection) -> None:
    _two_spaces(con)
    create_page(con, "root", "sa", "Root", "", 1.0)
    child = create_page(con, "kid", "sa", "Kid", "", 1.0, parent_id="root")
    assert child.parent_id == "root"
    with pytest.raises(ValidationFailed, match="parent"):
        create_page(con, "x", "sa", "X", "", 1.0, parent_id="missing")
    with pytest.raises(ValidationFailed, match="parent"):
        create_page(con, "y", "sb", "Y", "", 1.0, parent_id="root")  # parent lives in another space
    assert get_page_any(con, "x") is None and get_page_any(con, "y") is None


def test_check_parent_rejects_cycles_and_self_nesting(con: sqlite3.Connection) -> None:
    create_space(con, "s", "S", "", 1.0)
    create_page(con, "a", "s", "A", "", 1.0)
    create_page(con, "b", "s", "B", "", 1.0, parent_id="a")
    _check_parent(con, "s", None, "b")  # fine
    with pytest.raises(ValidationFailed, match="itself"):
        _check_parent(con, "s", "a", "b")  # a would sit below its own descendant
    with pytest.raises(ValidationFailed, match="itself"):
        _check_parent(con, "s", "a", "a")
    con.execute("UPDATE pages SET parent_id='b' WHERE id='a'")  # corrupt data: a -> b -> a
    with pytest.raises(ValidationFailed):  # must terminate instead of looping forever
        _check_parent(con, "s", None, "a")


def test_deleting_a_parent_keeps_children_and_detaches_them(con: sqlite3.Connection) -> None:
    create_space(con, "s", "S", "", 1.0)
    create_page(con, "root", "s", "Root", "", 1.0)
    create_page(con, "kid", "s", "Kid", "", 1.0, parent_id="root")
    delete_page(con, "s", "root")
    kid = get_page(con, "s", "kid")
    assert kid is not None and kid.parent_id is None


def test_pages_are_isolated_between_spaces(con: sqlite3.Connection) -> None:
    _two_spaces(con)
    create_page(con, "pa", "sa", "Only in alpha", "secret alpha", 1.0)
    assert get_page(con, "sb", "pa") is None
    assert get_page(con, "sa", "pa") is not None
    assert get_page_any(con, "pa") is not None
    assert [p.id for p in list_pages(con, "sa")] == ["pa"]
    assert list_pages(con, "sb") == []
    with pytest.raises(NotFound):
        update_page(con, "sb", "pa", 1, 2.0, title="hijack")
    with pytest.raises(NotFound):
        delete_page(con, "sb", "pa")
    page = get_page(con, "sa", "pa")
    assert page is not None and (page.title, page.revision) == ("Only in alpha", 1)


def test_list_pages_is_most_recently_updated_first(con: sqlite3.Connection) -> None:
    create_space(con, "s", "S", "", 1.0)
    create_page(con, "old", "s", "Old", "", 1.0)
    create_page(con, "mid", "s", "Mid", "", 2.0)
    create_page(con, "new", "s", "New", "", 3.0)
    update_page(con, "s", "old", 1, 9.0, content="touched")
    assert [p.id for p in list_pages(con, "s")] == ["old", "new", "mid"]


# --- optimistic concurrency -------------------------------------------------------------------------------------


def test_update_page_bumps_the_revision_and_keeps_unspecified_fields(con: sqlite3.Connection) -> None:
    create_space(con, "s", "S", "", 1.0)
    create_page(con, "p", "s", "Title", "body", 1.0)
    r2 = update_page(con, "s", "p", 1, 5.0, content="new body")
    assert (r2.revision, r2.title, r2.content, r2.updated_at, r2.created_at) == (2, "Title", "new body", 5.0, 1.0)
    r3 = update_page(con, "s", "p", 2, 6.0, title="  New title ")
    assert (r3.revision, r3.title, r3.content) == (3, "New title", "new body")
    assert update_page(con, "s", "p", 3, 7.0).revision == 4  # a no-op edit still counts as a revision


def test_a_stale_revision_is_a_conflict_and_changes_nothing(con: sqlite3.Connection) -> None:
    create_space(con, "s", "S", "", 1.0)
    create_page(con, "p", "s", "Title", "mine", 1.0)
    update_page(con, "s", "p", 1, 2.0, content="theirs")
    with pytest.raises(ConflictError):
        update_page(con, "s", "p", 1, 3.0, content="mine, overwriting")
    with pytest.raises(ConflictError):
        update_page(con, "s", "p", 99, 3.0, content="from the future")
    page = get_page(con, "s", "p")
    assert page is not None and (page.content, page.revision, page.updated_at) == ("theirs", 2, 2.0)


def test_update_page_unknown_is_not_found(con: sqlite3.Connection) -> None:
    create_space(con, "s", "S", "", 1.0)
    with pytest.raises(NotFound):
        update_page(con, "s", "ghost", 1, 1.0, title="x")


@pytest.mark.parametrize("kw", [{"title": ""}, {"title": "  "}, {"title": "t" * (MAX_TITLE + 1)},
                                {"content": "c" * (MAX_CONTENT + 1)},
                                {"title": "valid change", "content": "c" * (MAX_CONTENT + 1)}])
def test_invalid_update_is_rejected_atomically(con: sqlite3.Connection, kw: dict[str, str]) -> None:
    create_space(con, "s", "S", "", 1.0)
    create_page(con, "p", "s", "Title", "body", 1.0)
    with pytest.raises(ValidationFailed):
        update_page(con, "s", "p", 1, 2.0, **kw)
    page = get_page(con, "s", "p")
    assert page is not None and (page.title, page.content, page.revision, page.updated_at) == ("Title", "body", 1, 1.0)
    assert not con.in_transaction  # the failed edit did not leave a transaction open


def test_update_page_at_the_exact_limits(con: sqlite3.Connection) -> None:
    create_space(con, "s", "S", "", 1.0)
    create_page(con, "p", "s", "T", "", 1.0)
    page = update_page(con, "s", "p", 1, 2.0, title="t" * MAX_TITLE, content="c" * MAX_CONTENT)
    assert len(page.content) == MAX_CONTENT


def test_update_page_joins_an_outer_transaction_and_rolls_back_with_it(con: sqlite3.Connection) -> None:
    create_space(con, "s", "S", "", 1.0)
    create_page(con, "p", "s", "T", "v1", 1.0)
    con.execute("BEGIN IMMEDIATE")
    update_page(con, "s", "p", 1, 2.0, content="v2")
    assert con.in_transaction  # tx() joined rather than committing the caller's transaction
    con.execute("ROLLBACK")
    page = get_page(con, "s", "p")
    assert page is not None and (page.content, page.revision) == ("v1", 1)


def test_delete_page_removes_it_and_a_second_delete_is_not_found(con: sqlite3.Connection) -> None:
    create_space(con, "s", "S", "", 1.0)
    create_page(con, "p", "s", "T", "", 1.0)
    delete_page(con, "s", "p")
    assert get_page_any(con, "p") is None
    with pytest.raises(NotFound):
        delete_page(con, "s", "p")


# --- search -----------------------------------------------------------------------------------------------------


def test_search_finds_title_and_content_and_tracks_edits_and_deletes(con: sqlite3.Connection) -> None:
    create_space(con, "s", "S", "", 1.0)
    create_page(con, "p1", "s", "Kubernetes notes", "pods and nodes", 1.0)
    create_page(con, "p2", "s", "Groceries", "buy zucchini today", 1.0)
    assert [p.id for p in search_pages(con, "kubernetes")] == ["p1"]
    assert [p.id for p in search_pages(con, "zucchini")] == ["p2"]
    update_page(con, "s", "p2", 1, 2.0, content="buy quinoa today")
    assert search_pages(con, "zucchini") == []
    assert [p.id for p in search_pages(con, "quinoa")] == ["p2"]
    delete_page(con, "s", "p1")
    assert search_pages(con, "kubernetes") == []


def test_search_can_be_scoped_to_one_space(con: sqlite3.Connection) -> None:
    _two_spaces(con)
    create_page(con, "pa", "sa", "Budget", "alpha numbers", 1.0)
    create_page(con, "pb", "sb", "Budget", "beta numbers", 2.0)
    assert {p.id for p in search_pages(con, "budget")} == {"pa", "pb"}
    assert [p.id for p in search_pages(con, "budget", space_id="sa")] == ["pa"]
    assert [p.id for p in search_pages(con, "budget", space_id="sb")] == ["pb"]
    assert search_pages(con, "budget", space_id="nonexistent") == []


def test_search_limit_is_honoured(con: sqlite3.Connection) -> None:
    create_space(con, "s", "S", "", 1.0)
    for i in range(15):
        create_page(con, f"p{i}", "s", f"Meeting {i}", "agenda", float(i))
    assert len(search_pages(con, "meeting")) == 15
    assert len(search_pages(con, "meeting", limit=4)) == 4
    assert search_pages(con, "meeting", limit=0) == []


@pytest.mark.parametrize("query", ["", "   ", "the a of", '"', "*", "-", "AND OR NOT", "NEAR(", "title:", "((("])
def test_search_with_unsearchable_or_hostile_queries_never_errors(con: sqlite3.Connection, query: str) -> None:
    create_space(con, "s", "S", "", 1.0)
    create_page(con, "p", "s", "Plain title", "plain content", 1.0)
    search_pages(con, query)  # must not raise sqlite3.OperationalError (FTS syntax)


def test_fts_operators_in_user_text_are_just_words(con: sqlite3.Connection) -> None:
    create_space(con, "s", "S", "", 1.0)
    create_page(con, "p1", "s", "Alpha", "needle", 1.0)
    create_page(con, "p2", "s", "Beta", "haystack", 2.0)
    # a column filter or prefix wildcard must not widen or redirect the match
    assert search_pages(con, "content:needle") == [p for p in search_pages(con, "content needle")]
    assert [p.id for p in search_pages(con, "hay*")] == []
    assert [p.id for p in search_pages(con, "needle")] == ["p1"]


def test_search_handles_unicode(con: sqlite3.Connection) -> None:
    create_space(con, "s", "S", "", 1.0)
    create_page(con, "p", "s", "Café résumé", "naïve façade", 1.0)
    assert [p.id for p in search_pages(con, "café")] == ["p"]
    assert [p.id for p in search_pages(con, "façade")] == ["p"]
