"""Agents: named instructions plus the permissions and mode a task runs under."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, replace
from typing import Any

from lilly.domain.errors import NotFound, ValidationFailed
from lilly.domain.pets import DEFAULT_LOOK, PETS, Look, look_to_dict, parse_look

_COLS = ("id, name, instructions, mode, research_allowed, memory_allowed, files_allowed, space_id, created_at, "
         "computer_allowed, pet, chat_allowed, skills, model, look")
MAX_SKILLS = 6000
MAX_MODEL = 80


@dataclass(frozen=True, slots=True)
class AgentRow:
    id: str
    name: str
    instructions: str
    mode: int
    research_allowed: bool
    memory_allowed: bool
    files_allowed: bool
    space_id: str | None
    created_at: float
    computer_allowed: bool
    pet: str
    chat_allowed: bool       # may be reached from a chat app (Telegram); off until the owner says so
    skills: str              # markdown the owner wrote for this pet: trusted like instructions
    model: str               # the one configured model this pet always uses; "" lets routing choose
    look: Look


PERMISSIONS = ("research_allowed", "memory_allowed", "files_allowed", "computer_allowed", "chat_allowed")


def narrows(old: AgentRow, new: AgentRow) -> bool:
    """Whether a change takes something away: a permission turned off, or a stricter mode (a lower number).
    Widening, and edits to the name, instructions, skills, pet, look or model, take nothing away."""
    return new.mode < old.mode or any(getattr(old, p) and not getattr(new, p) for p in PERMISSIONS)


def _stored_look(raw: str) -> Look:
    """A look that cannot be read back is shown as the default one: a damaged value must not break a listing."""
    try:
        return parse_look(json.loads(raw))
    except ValueError:      # bad JSON, or ValidationFailed (also a ValueError)
        return DEFAULT_LOOK


def _row(r: tuple[Any, ...]) -> AgentRow:
    return AgentRow(str(r[0]), str(r[1]), str(r[2]), int(r[3]), bool(r[4]), bool(r[5]), bool(r[6]),
                    r[7], float(r[8]), bool(r[9]), str(r[10]), bool(r[11]), str(r[12]), str(r[13]),
                    _stored_look(str(r[14])))


def _check(name: str, instructions: str, mode: int, pet: str, skills: str, model: str) -> str:
    name = name.strip()
    if not 1 <= len(name) <= 80 or len(instructions) > 8000 or mode not in (0, 1, 2):
        raise ValidationFailed("agent name, instructions or mode out of bounds")
    if len(skills) > MAX_SKILLS:
        raise ValidationFailed(f"skills must be at most {MAX_SKILLS} characters")
    if len(model) > MAX_MODEL:
        raise ValidationFailed(f"model must be at most {MAX_MODEL} characters")
    if pet not in PETS:
        raise ValidationFailed(f"pet must be one of {', '.join(PETS)}")
    return name


def create_agent(con: sqlite3.Connection, id: str, name: str, instructions: str, mode: int, now: float, *,
                 research_allowed: bool = True, memory_allowed: bool = True, files_allowed: bool = False,
                 space_id: str | None = None, computer_allowed: bool = False, pet: str = "lily",
                 chat_allowed: bool = False, skills: str = "", model: str = "",
                 look: Look = DEFAULT_LOOK) -> AgentRow:
    name = _check(name, instructions, mode, pet, skills, model)
    con.execute(f"INSERT INTO agents({_COLS}) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (id, name, instructions, mode, int(research_allowed), int(memory_allowed), int(files_allowed),
                 space_id, now, int(computer_allowed), pet, int(chat_allowed), skills, model,
                 json.dumps(look_to_dict(look))))
    row = get_agent(con, id)
    assert row is not None
    return row


def get_agent(con: sqlite3.Connection, agent_id: str) -> AgentRow | None:
    r = con.execute(f"SELECT {_COLS} FROM agents WHERE id=?", (agent_id,)).fetchone()
    return _row(r) if r else None


def list_agents(con: sqlite3.Connection) -> list[AgentRow]:
    return [_row(r) for r in con.execute(f"SELECT {_COLS} FROM agents ORDER BY created_at")]


def update_agent(con: sqlite3.Connection, agent_id: str, *, name: str | None = None,
                 instructions: str | None = None, mode: int | None = None, research_allowed: bool | None = None,
                 memory_allowed: bool | None = None, files_allowed: bool | None = None,
                 computer_allowed: bool | None = None, pet: str | None = None,
                 chat_allowed: bool | None = None, skills: str | None = None, model: str | None = None,
                 look: Look | None = None) -> AgentRow:
    cur = get_agent(con, agent_id)
    if cur is None:
        raise NotFound(agent_id)
    merged = replace(
        cur, name=cur.name if name is None else name,
        instructions=cur.instructions if instructions is None else instructions,
        mode=cur.mode if mode is None else mode,
        research_allowed=cur.research_allowed if research_allowed is None else research_allowed,
        memory_allowed=cur.memory_allowed if memory_allowed is None else memory_allowed,
        files_allowed=cur.files_allowed if files_allowed is None else files_allowed,
        computer_allowed=cur.computer_allowed if computer_allowed is None else computer_allowed,
        pet=cur.pet if pet is None else pet,
        chat_allowed=cur.chat_allowed if chat_allowed is None else chat_allowed,
        skills=cur.skills if skills is None else skills, model=cur.model if model is None else model,
        look=cur.look if look is None else look)
    clean = _check(merged.name, merged.instructions, merged.mode, merged.pet, merged.skills, merged.model)
    con.execute("UPDATE agents SET name=?, instructions=?, mode=?, research_allowed=?, memory_allowed=?, "
                "files_allowed=?, computer_allowed=?, pet=?, chat_allowed=?, skills=?, model=?, look=? WHERE id=?",
                (clean, merged.instructions, merged.mode, int(merged.research_allowed),
                 int(merged.memory_allowed), int(merged.files_allowed), int(merged.computer_allowed), merged.pet,
                 int(merged.chat_allowed), merged.skills, merged.model, json.dumps(look_to_dict(merged.look)),
                 agent_id))
    row = get_agent(con, agent_id)
    assert row is not None
    return row


def delete_agent(con: sqlite3.Connection, agent_id: str) -> None:
    if con.execute("DELETE FROM agents WHERE id=?", (agent_id,)).rowcount == 0:
        raise NotFound(agent_id)
