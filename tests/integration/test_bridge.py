"""The Telegram bridge against a fake Telegram: pairing, the allowlist, untrusted tasks, rate limits, approvals."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from pathlib import Path

import pytest

from lilly.bridges.service import TOKEN_REF, BridgeService
from lilly.bridges.telegram import TelegramApi
from lilly.domain.bridges import BridgeSettings
from lilly.domain.ports import Secret
from lilly.domain.settings import settings_to_dict
from lilly.store import agents, bridges, tasks
from tests.fake_telegram import BASE, TOKEN, FakeTelegram, error
from tests.helpers import plan, step
from tests.integration.conftest import Api

pytestmark = pytest.mark.asyncio
OWNER, STRANGER = 4242, 777


class Rig:
    def __init__(self, api: Api, tg: FakeTelegram, service: BridgeService) -> None:
        self.api, self.tg, self.service = api, tg, service

    async def until(self, check: Callable[[], bool], timeout: float = 5.0) -> None:
        async with asyncio.timeout(timeout):
            while not check():
                await asyncio.sleep(0.02)

    async def configure(self, **over: object) -> str:
        """An agent that may be reached from chat, and the bridge switched on for it."""
        rt = self.api.runtime
        agent = await rt.db.write(lambda con: agents.create_agent(con, "chatty", "Chat", "be brief", 1, rt.clock(),
                                                                  chat_allowed=True, files_allowed=True))
        settings = BridgeSettings(enabled=True, agent_id=agent.id, **over)  # type: ignore[arg-type]
        await rt.apply_settings(replace(rt.settings, bridges=settings))
        return agent.id

    async def allow_files(self) -> None:
        settings = settings_to_dict(self.api.runtime.settings)
        settings["file_roots"] = [str(self.api.shared)]
        await self.api.sign_in()
        await self.api.send("PUT", "/api/settings", settings)

    async def pair(self, user: int = OWNER) -> None:
        code = (await self.service.new_pairing())["code"]
        self.tg.say(user, f"/pair {code}")
        await self.until(lambda: bridges.identity(self.api.runtime.db.reader, "telegram", user) is not None)


@pytest.fixture
async def rig(api: Api) -> AsyncIterator[Rig]:
    tg = FakeTelegram()
    http = tg.client()
    api.runtime.keys.put(TOKEN_REF, Secret(TOKEN))
    service = BridgeService(api.runtime, lambda token: TelegramApi(http, token, BASE), poll_s=1, backoff_s=0.05)
    await service.start()
    yield Rig(api, tg, service)
    await service.aclose()
    await http.aclose()


async def test_nothing_polls_until_the_bridge_is_switched_on(rig: Rig) -> None:
    await asyncio.sleep(0.1)
    assert rig.tg.calls == [] and rig.service.status()["running"] is False
    await rig.configure()
    await rig.until(lambda: "getUpdates" in rig.tg.calls)
    assert rig.service.status()["running"] is True


async def test_a_stranger_gets_no_answer_and_no_task(rig: Rig) -> None:
    await rig.configure()
    rig.tg.say(STRANGER, "hello?")
    rig.tg.say(STRANGER, "what is the weather")
    await rig.until(lambda: bridges.last_update(rig.api.runtime.db.reader, "telegram") >= rig.tg.next_id)
    assert rig.tg.sent == [] and tasks.list_tasks(rig.api.runtime.db.reader) == []


async def test_pairing_needs_the_right_code_and_works_once(rig: Rig) -> None:
    await rig.configure()
    issued = await rig.service.new_pairing()
    assert issued["bot"] is None or isinstance(issued["bot"], str)
    rig.tg.say(OWNER, "/pair WRONGONE")
    await rig.until(lambda: len(rig.tg.sent) == 1)
    assert "did not work" in rig.tg.texts(OWNER)[0]
    assert bridges.identity(rig.api.runtime.db.reader, "telegram", OWNER) is None
    rig.tg.say(OWNER, f"/pair {issued['code']}")
    await rig.until(lambda: bridges.identity(rig.api.runtime.db.reader, "telegram", OWNER) is not None)
    rig.tg.say(STRANGER, f"/pair {issued['code']}")                 # the same code again, from someone else
    await rig.until(lambda: len(rig.tg.sent) == 3)
    assert bridges.identity(rig.api.runtime.db.reader, "telegram", STRANGER) is None
    assert [i["user_id"] for i in rig.service.status()["identities"]] == [OWNER]  # type: ignore[attr-defined]


async def test_group_chats_are_ignored_even_for_a_paired_person(rig: Rig) -> None:
    await rig.configure()
    await rig.pair()
    before = len(rig.tg.sent)
    rig.tg.say(OWNER, "do something", chat_type="group", chat=-100)
    await rig.until(lambda: bridges.last_update(rig.api.runtime.db.reader, "telegram") >= rig.tg.next_id)
    assert len(rig.tg.sent) == before and tasks.list_tasks(rig.api.runtime.db.reader) == []


async def test_a_paired_message_becomes_an_untrusted_task_and_the_answer_comes_back(rig: Rig) -> None:
    agent = await rig.configure()
    await rig.pair()
    rig.api.provider.replies = [plan(answer="Four.")]
    rig.tg.say(OWNER, "What is 2+2?")
    await rig.until(lambda: "Four." in rig.tg.texts(OWNER))
    row = tasks.list_tasks(rig.api.runtime.db.reader)[0]
    assert row.tainted is True and row.agent_id == agent and row.goal == "What is 2+2?"
    assert "On it." in rig.tg.texts(OWNER)


async def test_an_answer_that_used_private_data_stays_in_the_app_by_default(rig: Rig) -> None:
    await rig.configure()
    await rig.pair()
    rig.api.provider.replies = [plan(answer="secret stuff")]
    rig.tg.say(OWNER, "tell me")
    await rig.until(lambda: any("On it" in t for t in rig.tg.texts(OWNER)))
    await rig.until(lambda: "secret stuff" in rig.tg.texts(OWNER))      # public data: sent as normal
    # Now a task that has read private data: label it PERSONAL in the store, then finish through the bridge.
    row = tasks.list_tasks(rig.api.runtime.db.reader)[0]
    await rig.api.runtime.db.write(lambda con: con.execute("UPDATE tasks SET label=1 WHERE id=?", (row.id,)))
    rig.service._tracked[row.id] = OWNER
    assert rig.service._api is not None
    await rig.service._finish(rig.service._api, row.id)
    assert "stays in Lilly" in rig.tg.texts(OWNER)[-1]


async def test_a_message_over_the_limit_and_a_flood_are_refused(rig: Rig) -> None:
    await rig.configure(per_minute=3, max_chars=100)
    await rig.pair()
    rig.tg.say(OWNER, "x" * 101)
    await rig.until(lambda: any("too long" in t for t in rig.tg.texts(OWNER)))
    rig.api.provider.replies = [plan(answer="a"), plan(answer="b")]
    for text in ("one", "two", "three"):       # the over-long message used the first of three slots
        rig.tg.say(OWNER, text)
    await rig.until(lambda: any("lot of messages" in t for t in rig.tg.texts(OWNER)))
    assert len(tasks.list_tasks(rig.api.runtime.db.reader)) == 2


async def test_with_no_chat_agent_the_person_is_told_how_to_set_one_up(rig: Rig) -> None:
    rt = rig.api.runtime
    await rt.apply_settings(replace(rt.settings, bridges=BridgeSettings(enabled=True)))
    await rig.pair()
    rig.tg.say(OWNER, "hi there")
    await rig.until(lambda: any("No agent is set up" in t for t in rig.tg.texts(OWNER)))
    assert tasks.list_tasks(rt.db.reader) == []


async def test_an_agent_that_is_not_marked_reachable_is_not_used(rig: Rig) -> None:
    rt = rig.api.runtime
    plain = await rt.db.write(lambda con: agents.create_agent(con, "plain", "Plain", "x", 1, rt.clock()))
    await rt.apply_settings(replace(rt.settings, bridges=BridgeSettings(enabled=True, agent_id=plain.id)))
    await rig.pair()
    rig.tg.say(OWNER, "hello")
    await rig.until(lambda: any("No agent is set up" in t for t in rig.tg.texts(OWNER)))
    assert tasks.list_tasks(rt.db.reader) == []


async def test_a_replayed_update_does_not_run_twice(rig: Rig) -> None:
    await rig.configure()
    await rig.pair()
    rig.api.provider.replies = [plan(answer="once"), plan(answer="twice")]
    update = rig.tg.say(OWNER, "do it")
    await rig.until(lambda: "once" in rig.tg.texts(OWNER))
    rig.tg.updates.append({**rig.tg.updates[-1]})                     # Telegram sends the same update again
    assert rig.tg.updates[-1]["update_id"] == update
    await asyncio.sleep(0.3)
    assert len(tasks.list_tasks(rig.api.runtime.db.reader)) == 1


async def test_stop_cancels_what_is_running_from_this_chat(rig: Rig) -> None:
    await rig.configure()
    await rig.pair()
    target = rig.api.shared / "x.txt"
    settings = settings_to_dict(rig.api.runtime.settings)
    settings["file_roots"] = [str(rig.api.shared)]
    await rig.api.sign_in()
    await rig.api.send("PUT", "/api/settings", settings)
    rig.api.provider.replies = [plan(step("s1", "fs.write", path=str(target), content="x"),
                                     step("s2", "llm.work", task="t", input="i"))]
    rig.tg.say(OWNER, "write a file")
    await rig.until(lambda: any("Approve" in str(m.get("reply_markup")) for m in rig.tg.sent))
    rig.tg.say(OWNER, "/stop")
    await rig.until(lambda: any("Stopped 1" in t for t in rig.tg.texts(OWNER)))
    assert not target.exists()


async def test_an_approval_in_chat_shows_the_exact_action_and_only_that_can_be_approved(rig: Rig) -> None:
    await rig.configure()
    await rig.pair()
    await rig.api.sign_in()
    settings = settings_to_dict(rig.api.runtime.settings)
    settings["file_roots"] = [str(rig.api.shared)]
    await rig.api.send("PUT", "/api/settings", settings)
    target = rig.api.shared / "note.txt"
    rig.api.provider.replies = [plan(step("s1", "fs.write", path=str(target), content="hello"),
                                     step("s2", "llm.work", task="say done", input="$s1.output")), "All done."]
    rig.tg.say(OWNER, "write a note")
    await rig.until(lambda: any(m.get("reply_markup") for m in rig.tg.sent))
    card = next(m for m in rig.tg.sent if m.get("reply_markup"))
    assert "fs.write" in str(card["text"]) and str(target) in str(card["text"]) and "hello" in str(card["text"])
    buttons = card["reply_markup"]["inline_keyboard"][0]
    assert [b["text"] for b in buttons] == ["Approve", "Decline"] and all(len(b["callback_data"]) <= 64 for b in buttons)
    assert not target.exists()
    rig.tg.press(STRANGER, buttons[0]["callback_data"])                # someone else pressing it does nothing
    await asyncio.sleep(0.2)
    assert not target.exists()
    rig.tg.press(OWNER, buttons[0]["callback_data"])
    await rig.until(lambda: "All done." in rig.tg.texts(OWNER))
    assert target.read_text() == "hello"
    assert rig.tg.edits and "Approved" in str(rig.tg.edits[0]["text"])
    rig.tg.press(OWNER, buttons[0]["callback_data"])                   # single use
    await rig.until(lambda: any("no longer waiting" in str(a.get("text")) for a in rig.tg.answers))


async def test_computer_control_can_only_be_approved_in_the_app(rig: Rig) -> None:
    rt = rig.api.runtime
    agent = await rt.db.write(lambda con: agents.create_agent(
        con, "ctl", "Ctl", "x", 1, rt.clock(), chat_allowed=True, computer_allowed=True))
    await rt.apply_settings(replace(rt.settings, modules=rt.settings.modules | {"computer"},
                                    bridges=BridgeSettings(enabled=True, agent_id=agent.id)))
    await rig.pair()
    rig.api.provider.replies = [plan(step("s1", "computer.notify", title="hi", message="there"),
                                     step("s2", "llm.work", task="t", input="i"))]
    rig.tg.say(OWNER, "notify me")
    await rig.until(lambda: any("approved in the Lilly app" in t for t in rig.tg.texts(OWNER)))
    assert not any(m.get("reply_markup") for m in rig.tg.sent)


async def test_a_wrong_token_stops_the_bridge_with_a_plain_reason_and_never_shows_the_token(rig: Rig) -> None:
    await rig.service.aclose()
    rig.tg.fail = [error(401)]
    await rig.configure()
    await rig.until(lambda: rig.service.status()["error"] is not None)
    status = str(rig.service.status())
    assert "rejected the bot token" in status and TOKEN not in status
    await rig.until(lambda: rig.service.status()["running"] is False)


async def test_telegram_asking_to_slow_down_is_obeyed_and_polling_resumes(rig: Rig) -> None:
    rig.tg.fail = [error(429, retry_after=0), error(500)]
    await rig.configure()
    await rig.until(lambda: rig.tg.calls.count("getUpdates") >= 3)
    assert rig.service.status()["running"] is True


async def test_setting_the_token_checks_it_and_clearing_it_stops_the_bridge(api: Api) -> None:
    tg = FakeTelegram()
    http = tg.client()
    service = BridgeService(api.runtime, lambda token: TelegramApi(http, token, BASE), poll_s=1, backoff_s=0.05)
    await service.start()
    from lilly.domain.errors import ConflictError
    with pytest.raises(ConflictError, match="did not work"):
        await service.set_token("999:WRONG")
    assert api.runtime.keys.get(TOKEN_REF) is None
    assert await service.set_token(TOKEN) == "lilly_test_bot"
    assert api.runtime.keys.get(TOKEN_REF) is not None
    await service.clear_token()
    assert api.runtime.keys.get(TOKEN_REF) is None and service.status()["bot"] is None
    await service.aclose()
    await http.aclose()


async def test_pairing_needs_a_token_first(api: Api) -> None:
    from lilly.domain.errors import ConflictError
    service = BridgeService(api.runtime)
    with pytest.raises(ConflictError, match="token"):
        await service.new_pairing()


async def test_unpairing_removes_the_account_and_it_is_ignored_again(rig: Rig) -> None:
    await rig.configure()
    await rig.pair()
    assert await rig.service.unpair(OWNER) is True and await rig.service.unpair(OWNER) is False
    rig.tg.say(OWNER, "still there?")
    await rig.until(lambda: bridges.last_update(rig.api.runtime.db.reader, "telegram") >= rig.tg.next_id)
    assert Path and tasks.list_tasks(rig.api.runtime.db.reader) == []


async def _ask_to_write(rig: Rig, name: str, content: str) -> dict[str, object]:
    """Start a chat task that stops at an approval to write `name`, and return the message that asked."""
    await rig.configure()
    await rig.pair()
    await rig.allow_files()
    rig.api.provider.replies = [plan(step("s1", "fs.write", path=name, content=content),
                                     step("s2", "llm.work", task="t", input="$s1.output")), "All done."]
    rig.tg.say(OWNER, "write it")
    await rig.until(lambda: any("fs.write" in t for t in rig.tg.texts(OWNER)))
    return next(m for m in rig.tg.sent if "fs.write" in str(m["text"]))


async def test_an_approval_that_is_not_shown_in_full_can_only_be_decided_in_the_app(rig: Rig) -> None:
    card = await _ask_to_write(rig, str(rig.api.shared / "note.txt"), "x" * 1000)
    assert "approved in the Lilly app" in str(card["text"]) and "reply_markup" not in card


async def test_an_approval_cut_at_the_card_length_can_only_be_decided_in_the_app(rig: Rig) -> None:
    deep = rig.api.shared / ("a" * 200) / ("b" * 200) / "note.txt"
    card = await _ask_to_write(rig, str(deep), "y" * 590)
    assert "approved in the Lilly app" in str(card["text"]) and "reply_markup" not in card


async def test_an_unpaired_chat_hears_nothing_more_even_after_it_pairs_again(rig: Rig) -> None:
    await _ask_to_write(rig, str(rig.api.shared / "note.txt"), "hello")
    await rig.service.unpair(OWNER)
    await rig.pair()
    before = len(rig.tg.sent)
    approval = rig.api.runtime.approvals.pending()[0]
    await rig.api.runtime.approvals.decide(approval.id, approve=False, payload_hash=approval.payload_hash)
    await rig.until(lambda: tasks.list_tasks(rig.api.runtime.db.reader)[0].state.value == "CANCELLED")
    await asyncio.sleep(0.3)
    assert len(rig.tg.sent) == before


async def test_an_answer_is_not_sent_when_the_account_was_removed_behind_the_bridges_back(rig: Rig) -> None:
    await _ask_to_write(rig, str(rig.api.shared / "note.txt"), "hello")
    await rig.api.runtime.db.write(lambda con: bridges.remove_identity(con, "telegram", OWNER))
    before = len(rig.tg.sent)
    approval = rig.api.runtime.approvals.pending()[0]
    await rig.api.runtime.approvals.decide(approval.id, approve=False, payload_hash=approval.payload_hash)
    await rig.until(lambda: tasks.list_tasks(rig.api.runtime.db.reader)[0].state.value == "CANCELLED")
    await asyncio.sleep(0.3)
    assert len(rig.tg.sent) == before


async def test_replacing_the_token_with_another_bots_starts_its_updates_from_scratch(rig: Rig) -> None:
    db = rig.api.runtime.db
    await rig.service.set_token(TOKEN)
    await db.write(lambda con: bridges.set_last_update(con, "telegram", 500))
    await rig.service.set_token(TOKEN)                 # the same bot again: nothing is forgotten
    assert bridges.last_update(db.reader, "telegram") == 500
    rig.tg.username = "other_bot"
    await rig.service.set_token(TOKEN)
    assert bridges.last_update(db.reader, "telegram") == 0
    await db.write(lambda con: bridges.set_last_update(con, "telegram", 700))
    await rig.service.clear_token()
    assert bridges.last_update(db.reader, "telegram") == 0
