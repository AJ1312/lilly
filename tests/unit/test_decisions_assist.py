"""Laya assist, the vocabulary: the two extra questions, their bounded state text, and the settings that switch
them on. Both start off and, when switched on, start as watch-only."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from lilly.domain.decisions import (
    ASSIST_KINDS,
    DEFAULT_CHAIN,
    DRIFTS,
    FITS,
    FOLLOWS,
    KIND_DECIDERS,
    OFF,
    PLAN_OPTIONS,
    REPLY_OPTIONS,
    Brief,
    DecisionSettings,
    Kind,
    KindSettings,
    decisions_to_dict,
    laya_kinds,
    parse_decisions,
    plan_state,
    reply_state,
    with_assist,
    with_laya,
)
from lilly.domain.settings import default_settings, parse_settings, settings_to_dict

LONG = "x" * 50_000
SECRET = "sk-abcdefghijklmnopqrstuvwxyz0123"


def test_the_two_questions_are_yes_no_questions_with_their_own_option_ids() -> None:
    assert (Kind.PLAN.value, Kind.REPLY.value) == ("plan", "reply")
    assert ASSIST_KINDS == (Kind.PLAN, Kind.REPLY, Kind.ROUTE)
    assert (FITS, OFF, FOLLOWS, DRIFTS) == ("fits", "off", "follows", "drifts")
    assert [o.id for o in PLAN_OPTIONS] == [FITS, OFF] and [o.id for o in REPLY_OPTIONS] == [FOLLOWS, DRIFTS]
    assert all(o.label for o in (*PLAN_OPTIONS, *REPLY_OPTIONS))


# ---- state text ---------------------------------------------------------------------------------------
def test_a_plan_state_names_the_request_the_instructions_and_the_step() -> None:
    state = plan_state(Brief("tidy my downloads", "Never touch the Taxes folder."), "fs.apply_moves",
                       {"root": "/home/a/Downloads", "moves": [{"from": "a", "to": "b"}]})
    assert "tidy my downloads" in state and "Never touch the Taxes folder." in state
    assert "fs.apply_moves" in state and "/home/a/Downloads" in state


def test_a_plan_state_is_bounded_whatever_the_inputs_and_keeps_the_tool_name() -> None:
    state = plan_state(Brief(LONG, LONG), "fs.write", {"path": "/a", "content": LONG})
    assert len(state) <= 600 + 600 + 1200 + 80       # the three parts plus their labels
    assert "fs.write" in state
    assert state.count("x") <= 600 + 600 + 1200


def test_the_arguments_of_a_step_are_redacted_and_do_not_depend_on_key_order() -> None:
    state = plan_state(Brief("g"), "web.fetch", {"url": "https://a.example", "token": SECRET})
    assert SECRET not in state and "https://a.example" in state
    assert plan_state(Brief("g"), "t", {"a": 1, "b": 2}) == plan_state(Brief("g"), "t", {"b": 2, "a": 1})


def test_a_plan_state_with_no_instructions_says_so_and_a_huge_tool_name_cannot_break_the_bound() -> None:
    assert "none" in plan_state(Brief("g"), "fs.write", {}).lower()
    assert len(plan_state(Brief("g"), "t" * 5000, {})) <= 600 + 600 + 1200 + 80


def test_a_short_reply_appears_once_and_a_long_one_as_its_start_and_its_end() -> None:
    short = reply_state(Brief("Write to Ana", "Answer in French."), "Bonjour Ana, voici le rapport.")
    assert short.count("Bonjour Ana, voici le rapport.") == 1
    assert "Write to Ana" in short and "Answer in French." in short
    body = "START-" + "m" * 5000 + "-END"
    long = reply_state(Brief("g", "i"), body)
    assert "START-" in long and "-END" in long
    assert len(long) <= 600 + 600 + 900 + 600 + 100
    assert long.count("m") <= 900 + 600


def test_a_reply_state_is_bounded_whatever_the_inputs() -> None:
    assert len(reply_state(Brief(LONG, LONG), LONG)) <= 600 + 600 + 900 + 600 + 100
    assert len(reply_state(Brief("", ""), "")) < 200


# ---- settings -------------------------------------------------------------------------------------------
def test_both_questions_are_off_by_default_and_would_be_watch_only_if_switched_on() -> None:
    d = DecisionSettings()
    for kind in ASSIST_KINDS:
        assert d.for_kind(kind).chain == () and DEFAULT_CHAIN[kind] == () and d.for_kind(kind).shadow is True
    assert laya_kinds(d) == ()


def test_only_laya_or_a_small_model_may_answer_the_new_questions() -> None:
    for kind in ASSIST_KINDS:
        assert KIND_DECIDERS[kind] == frozenset({"laya", "small_model"})
        _, errs = parse_decisions({kind.value: {"chain": ["match"]}})
        assert any("cannot answer" in e for e in errs)
        parsed, errs = parse_decisions({kind.value: {"chain": ["laya", "small_model"]}})
        assert errs == [] and parsed is not None


def test_a_chain_written_by_hand_without_a_shadow_flag_is_still_watch_only() -> None:
    parsed, errs = parse_decisions({"plan": {"chain": ["laya"]}})
    assert errs == [] and parsed is not None
    assert parsed.for_kind(Kind.PLAN).shadow is True
    again, _ = parse_decisions({"plan": {"chain": ["laya"], "shadow": False}})
    assert again is not None and again.for_kind(Kind.PLAN).shadow is False


def test_settings_files_from_before_laya_assist_load_with_the_defaults() -> None:
    old = settings_to_dict(default_settings())
    del old["decisions"]["plan"], old["decisions"]["reply"]
    settings, problems = parse_settings(old)
    assert problems == [] and settings.decisions == DecisionSettings()
    bare, problems = parse_settings({k: v for k, v in old.items() if k != "decisions"})
    assert problems == [] and bare.decisions.for_kind(Kind.PLAN).chain == ()


def test_the_new_questions_are_saved_and_come_back_unchanged() -> None:
    d = with_assist(with_assist(DecisionSettings(), Kind.PLAN, True, act=True), Kind.REPLY, True, act=False)
    sent = decisions_to_dict(d)
    assert sent["plan"]["chain"] == ["laya"] and sent["plan"]["shadow"] is False
    assert sent["reply"]["chain"] == ["laya"] and sent["reply"]["shadow"] is True
    parsed, errs = parse_decisions(json.loads(json.dumps(sent)))
    assert errs == [] and parsed == d
    settings, problems = parse_settings(json.loads(json.dumps(settings_to_dict(replace(default_settings(), decisions=d)))))
    assert problems == [] and settings.decisions == d


def test_switching_a_question_on_is_watch_only_unless_asked_to_act() -> None:
    watch = with_assist(DecisionSettings(), Kind.PLAN, True, act=False)
    assert [s.decider for s in watch.for_kind(Kind.PLAN).chain] == ["laya"]
    assert watch.for_kind(Kind.PLAN).shadow and watch.for_kind(Kind.PLAN).enabled
    acting = with_assist(watch, Kind.PLAN, True, act=True)
    assert acting.for_kind(Kind.PLAN).shadow is False and len(acting.for_kind(Kind.PLAN).chain) == 1
    assert with_assist(acting, Kind.PLAN, True, act=False).for_kind(Kind.PLAN).shadow is True
    assert watch.for_kind(Kind.REPLY) == DecisionSettings().for_kind(Kind.REPLY)      # the other one is untouched


def test_switching_a_question_off_empties_its_chain_and_leaves_everything_else() -> None:
    on = with_laya(with_assist(DecisionSettings(), Kind.REPLY, True, act=True), True)
    off = with_assist(on, Kind.REPLY, False, act=True)
    assert off.for_kind(Kind.REPLY).chain == ()
    assert {k: v for k, v in off.kinds.items() if k != "reply"} == {k: v for k, v in on.kinds.items() if k != "reply"}


@pytest.mark.parametrize("kind", [Kind.TOOLS, Kind.LOOP, Kind.INSTRUCTIONS, Kind.PICK])
def test_only_the_two_assist_questions_can_be_switched_this_way(kind: Kind) -> None:
    with pytest.raises(ValueError, match="assist"):
        with_assist(DecisionSettings(), kind, True, act=False)


def test_turning_laya_on_does_not_turn_assist_on_but_turning_it_off_turns_assist_off() -> None:
    assert with_laya(DecisionSettings(), True).for_kind(Kind.PLAN).chain == ()
    assisted = with_assist(with_assist(with_laya(DecisionSettings(), True), Kind.PLAN, True, act=True),
                           Kind.REPLY, True, act=False)
    gone = with_laya(assisted, False)
    assert all(gone.for_kind(k).chain == () for k in ASSIST_KINDS)
    assert laya_kinds(gone) == ()


def test_kind_settings_default_enabled_for_the_new_questions() -> None:
    assert DecisionSettings().for_kind(Kind.PLAN) == KindSettings(True, True, ())
