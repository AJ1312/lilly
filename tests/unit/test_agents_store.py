"""Agents keep their pet's look, skills and model, and a damaged look never breaks a listing."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from lilly.domain.errors import ValidationFailed
from lilly.domain.pets import Look
from lilly.store.agents import MAX_SKILLS, AgentRow, create_agent, get_agent, list_agents, narrows, update_agent
from lilly.store.connection import open_db


@pytest.fixture
def con(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = open_db(tmp_path / "agents.db")
    try:
        yield c
    finally:
        c.close()


def test_a_new_agent_has_the_default_look_and_no_skills_or_model(con: sqlite3.Connection) -> None:
    a = create_agent(con, "a1", "Fox", "", 1, 1.0)
    assert (a.skills, a.model, a.look) == ("", "", Look(None, "none", "round", True))


def test_look_skills_and_model_round_trip(con: sqlite3.Connection) -> None:
    look = Look(200, "hat", "sleepy", False)
    create_agent(con, "a1", "Fox", "", 1, 1.0, skills="# Skills\nDo X.", model="mistral-small", look=look)
    got = get_agent(con, "a1")
    assert got is not None and (got.skills, got.model, got.look) == ("# Skills\nDo X.", "mistral-small", look)
    assert list_agents(con)[0] == got


def test_update_changes_only_what_it_is_given(con: sqlite3.Connection) -> None:
    create_agent(con, "a1", "Fox", "be brief", 1, 1.0, skills="S", model="m", look=Look(5, "bow", "round", True))
    row = update_agent(con, "a1", look=Look(6, "bow", "round", True))
    assert (row.skills, row.model, row.instructions, row.look.hue) == ("S", "m", "be brief", 6)
    row = update_agent(con, "a1", skills="", model="")
    assert (row.skills, row.model, row.look.hue) == ("", "", 6)


def test_skills_are_limited(con: sqlite3.Connection) -> None:
    create_agent(con, "a1", "Fox", "", 1, 1.0, skills="x" * MAX_SKILLS)
    with pytest.raises(ValidationFailed):
        create_agent(con, "a2", "Fox", "", 1, 1.0, skills="x" * (MAX_SKILLS + 1))
    with pytest.raises(ValidationFailed):
        update_agent(con, "a1", skills="x" * (MAX_SKILLS + 1))
    assert MAX_SKILLS == 6000 and get_agent(con, "a2") is None


def test_a_model_name_must_be_short(con: sqlite3.Connection) -> None:
    with pytest.raises(ValidationFailed):
        create_agent(con, "a1", "Fox", "", 1, 1.0, model="m" * 81)


@pytest.mark.parametrize("stored", ["not json", "[]", '{"hue": 999}', '{"nope": 1}', ""])
def test_a_corrupt_stored_look_falls_back_to_the_default(con: sqlite3.Connection, stored: str) -> None:
    create_agent(con, "a1", "Fox", "", 1, 1.0, look=Look(5, "bow", "round", True))
    create_agent(con, "a2", "Owl", "", 1, 2.0)
    con.execute("UPDATE agents SET look=? WHERE id='a1'", (stored,))
    assert [a.look for a in list_agents(con)] == [Look(None, "none", "round", True)] * 2


# ---- which changes take something away -------------------------------------------------------------
def _agent(**kw: object) -> AgentRow:
    base: dict[str, object] = dict(
        id="a1", name="Fox", instructions="", mode=1, research_allowed=True, memory_allowed=True, files_allowed=True,
        space_id=None, created_at=1.0, computer_allowed=True, pet="lily", chat_allowed=True, skills="", model="m",
        look=Look(None, "none", "round", True))
    return AgentRow(**{**base, **kw})  # type: ignore[arg-type]


@pytest.mark.parametrize("change", [
    {"research_allowed": False}, {"memory_allowed": False}, {"files_allowed": False}, {"computer_allowed": False},
    {"chat_allowed": False}, {"mode": 0}, {"mode": 0, "name": "Renamed", "research_allowed": True}])
def test_a_permission_turned_off_or_a_stricter_mode_narrows(change: dict[str, object]) -> None:
    assert narrows(_agent(), _agent(**change))


@pytest.mark.parametrize("change", [
    {}, {"mode": 2}, {"name": "Other"}, {"instructions": "new"}, {"skills": "S"}, {"pet": "otto"}, {"model": "other"},
    {"model": ""}, {"look": Look(7, "hat", "sleepy", False)}])
def test_widening_and_other_edits_do_not_narrow(change: dict[str, object]) -> None:
    assert not narrows(_agent(), _agent(**change))


def test_turning_a_permission_on_never_narrows_even_when_another_is_unchanged_off() -> None:
    before = _agent(research_allowed=False, files_allowed=False, mode=0)
    assert not narrows(before, _agent(research_allowed=True, files_allowed=False, mode=1))


def test_one_permission_off_while_another_turns_on_still_narrows() -> None:
    assert narrows(_agent(files_allowed=False), _agent(files_allowed=True, research_allowed=False))
