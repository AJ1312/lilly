"""Laya assist over the API: the switches, the verdict on a task, and the interface's types."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from lilly.app.laya import LayaService
from lilly.decide import laya_install
from lilly.domain.decisions import DRIFTS, FOLLOWS, Answer, Kind, Request, with_assist
from lilly.domain.ids import new_id
from lilly.domain.labels import Label
from lilly.store import tasks
from lilly.store.events import append_event
from tests.helpers import plan
from tests.integration.conftest import Api
from tests.integration.test_laya_api import finished_install, use
from tests.unit.test_web_contract import _fields

pytestmark = pytest.mark.asyncio


class Verdict:
    """A stand-in for Laya that gives the same answer to every reply it is shown."""

    name = "laya"

    def __init__(self, choice: str) -> None:
        self.choice = choice

    async def decide(self, request: Request) -> Answer | None:
        return Answer("laya", self.choice, 0.9)


async def installed(api: Api, tmp_path: Path) -> None:
    api.runtime.laya = LayaService(tmp_path / "laya", finished_install)
    api.runtime.laya.install()
    for _ in range(200):
        if laya_install.is_installed(tmp_path / "laya"):
            return
        await asyncio.sleep(0.02)
    raise AssertionError("the stand-in install never finished")


async def a_task(api: Api) -> str:
    task_id = new_id()
    await api.runtime.db.write(lambda con: tasks.create_task(con, id=task_id, goal="g", mode=1, label=Label.PUBLIC,
                                                              tainted=False, now=1.0))
    return task_id


async def note(api: Api, task_id: str, payload: dict[str, Any]) -> None:
    await api.runtime.db.write(lambda con: append_event(con, task_id, "reply_check", payload, "system", 2.0))


async def test_a_task_shows_what_the_reply_check_found_and_nothing_when_it_did_not_run(api: Api) -> None:
    await api.sign_in()
    task_id = await a_task(api)
    assert (await api.get(f"/api/tasks/{task_id}")).json()["reply_check"] is None
    await note(api, task_id, {"choice": FOLLOWS, "confidence": 0.9, "decider": "laya"})
    assert (await api.get(f"/api/tasks/{task_id}")).json()["reply_check"] == "follows"
    await note(api, task_id, {"choice": DRIFTS, "confidence": 0.8, "decider": "laya"})
    assert (await api.get(f"/api/tasks/{task_id}")).json()["reply_check"] == "drifts"      # the newest note counts


@pytest.mark.parametrize("payload", [{"choice": "allow"}, {"choice": None}, {}, {"choice": 5}])
async def test_a_note_that_is_not_one_of_the_two_verdicts_is_shown_as_nothing(api: Api, payload: dict[str, Any]) -> None:
    await api.sign_in()
    task_id = await a_task(api)
    await note(api, task_id, payload)
    assert (await api.get(f"/api/tasks/{task_id}")).json()["reply_check"] is None


async def test_a_finished_task_gets_its_reply_check_through_the_whole_app(api: Api) -> None:
    await api.sign_in()
    api.runtime._static_deciders["laya"] = Verdict(DRIFTS)          # type: ignore[assignment]
    await api.runtime.apply_settings(replace(api.runtime.settings, decisions=with_assist(
        api.runtime.settings.decisions, Kind.REPLY, True, act=True)))
    api.provider.replies = [plan(answer="Four.")]
    task = (await api.send("POST", "/api/tasks", {"goal": "What is 2+2? Answer in French."})).json()["task"]
    done = await api.finished(task["id"])
    assert done["task"]["state"] == "DONE"
    async with asyncio.timeout(5):
        while (await api.get(f"/api/tasks/{task['id']}")).json()["reply_check"] is None:
            await asyncio.sleep(0.02)
    assert (await api.get(f"/api/tasks/{task['id']}")).json()["reply_check"] == "drifts"


async def test_the_task_type_in_the_interface_names_exactly_what_the_server_sends(api: Api) -> None:
    await api.sign_in()
    sent = (await api.get(f"/api/tasks/{await a_task(api)}")).json()
    assert _fields("TaskDetail") == set(sent)


# ---- the switches -------------------------------------------------------------------------------------
async def test_the_switches_need_a_session_and_laya_to_be_installed(api: Api, tmp_path: Path) -> None:
    body = {"kind": "plan", "enabled": True, "act": False}
    assert (await api.http.put("/api/laya/assist", json=body)).status_code == 401
    await api.sign_in()
    use(api, tmp_path, finished_install)
    refused = await api.send("PUT", "/api/laya/assist", body)
    assert refused.status_code == 409 and "not installed" in refused.json()["error"]
    assert api.runtime.settings.decisions.for_kind(Kind.PLAN).chain == ()
    assert (await api.send("PUT", "/api/laya/assist", {**body, "enabled": False})).status_code == 200   # off is always allowed


async def test_switching_a_check_on_starts_watch_only_and_acting_is_a_separate_choice(api: Api, tmp_path: Path) -> None:
    await api.sign_in()
    await installed(api, tmp_path)
    assert (await api.send("PUT", "/api/laya/assist", {"kind": "reply", "enabled": True})).status_code == 200
    reply = api.runtime.settings.decisions.for_kind(Kind.REPLY)
    assert [s.decider for s in reply.chain] == ["laya"] and reply.shadow is True
    await api.send("PUT", "/api/laya/assist", {"kind": "reply", "enabled": True, "act": True})
    assert api.runtime.settings.decisions.for_kind(Kind.REPLY).shadow is False
    shown = (await api.get("/api/settings")).json()["settings"]["decisions"]["reply"]
    assert shown["chain"] == ["laya"] and shown["shadow"] is False
    await api.send("PUT", "/api/laya/assist", {"kind": "reply", "enabled": False})
    assert api.runtime.settings.decisions.for_kind(Kind.REPLY).chain == ()


@pytest.mark.parametrize("body", [{"kind": "loop", "enabled": True}, {"kind": "nope", "enabled": True},
                                  {"enabled": True}, {"kind": "plan"}, {"kind": "plan", "enabled": "yes"},
                                  {"kind": "plan", "enabled": True, "act": "yes"}])
async def test_a_switch_request_must_name_one_of_the_two_checks_and_use_real_booleans(api: Api, body: dict[str, Any]) -> None:
    await api.sign_in()
    assert (await api.send("PUT", "/api/laya/assist", body)).status_code == 400


async def test_turning_laya_off_turns_both_checks_off(api: Api, tmp_path: Path) -> None:
    await api.sign_in()
    await installed(api, tmp_path)
    await api.send("PUT", "/api/laya/enabled", {"enabled": True})
    for kind in ("plan", "reply"):
        await api.send("PUT", "/api/laya/assist", {"kind": kind, "enabled": True, "act": True})
    await api.send("PUT", "/api/laya/enabled", {"enabled": False})
    decisions = api.runtime.settings.decisions
    assert decisions.for_kind(Kind.PLAN).chain == () and decisions.for_kind(Kind.REPLY).chain == ()
