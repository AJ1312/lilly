"""Decision settings: cautious defaults, strict validation, and the guarantee that nothing here can allow anything."""
from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
from typing import Any

import pytest

from lilly.domain import decisions as domain
from lilly.domain.decisions import (
    DECIDERS,
    Answer,
    DecisionRecord,
    DecisionSettings,
    Kind,
    Outcome,
    Request,
    decisions_to_dict,
    parse_decisions,
    valid_confidence,
)
from lilly.domain.settings import default_settings, parse_settings, settings_to_dict

SRC = Path(__file__).resolve().parents[2] / "src" / "lilly"


def test_defaults_are_cautious_rules_only_and_round_trip() -> None:
    d = DecisionSettings()
    assert d.enabled and d.for_kind(Kind.TOOLS).shadow is False
    chains = {k: [s.decider for s in d.for_kind(k).chain] for k in Kind}
    assert chains == {Kind.TOOLS: ["search"], Kind.LOOP: ["loop"], Kind.INSTRUCTIONS: ["rules"], Kind.PICK: ["match"],
                      Kind.PLAN: [], Kind.REPLY: [], Kind.ROUTE: []}      # Laya assist is not asked at all until switched on
    assert all("small_model" not in c and "laya" not in c for c in chains.values())
    parsed, errs = parse_decisions(decisions_to_dict(d))
    assert not errs and parsed == d
    assert parse_decisions({}) == (d, [])


def test_a_custom_chain_with_thresholds_and_timeouts_is_kept() -> None:
    parsed, errs = parse_decisions({"pick": {"chain": ["match", "small_model", "laya"], "shadow": True,
                                             "min_confidence": {"match": 0.9}, "timeout_s": {"laya": 5}},
                                    "max_per_task": 5, "max_model_tokens_per_task": 0})
    assert not errs and parsed is not None
    pick = parsed.for_kind(Kind.PICK)
    assert [(s.decider, s.min_confidence, s.timeout_s) for s in pick.chain] == [
        ("match", 0.9, 0.5), ("small_model", 0.7, 8.0), ("laya", 0.7, 5.0)]
    assert pick.shadow and parsed.max_per_task == 5 and parsed.max_model_tokens_per_task == 0


@pytest.mark.parametrize("raw, fragment", [
    ({"tools": {"chain": ["gpt"]}}, "unknown decider"),
    ({"tools": {"chain": ["laya"]}}, "cannot answer"),
    ({"loop": {"chain": ["rules"]}}, "cannot answer"),
    ({"voice": {}}, "unknown setting"),
    ({"tools": {"chain": ["search", "search"]}}, "different deciders"),
    ({"pick": {"chain": ["match", "small_model", "laya", "match", "x"]}}, "at most"),
    ({"tools": {"min_confidence": {"search": 1.5}}}, "0 to 1"),
    ({"tools": {"min_confidence": {"search": -0.1}}}, "0 to 1"),
    ({"tools": {"min_confidence": {"search": float("nan")}}}, "0 to 1"),
    ({"tools": {"min_confidence": {"search": True}}}, "0 to 1"),
    ({"tools": {"min_confidence": {"match": 0.5}}}, "not in the chain"),
    ({"tools": {"timeout_s": {"search": 0.01}}}, "0.05 to 30"),
    ({"tools": {"timeout_s": {"search": 31}}}, "0.05 to 30"),
    ({"tools": {"timeout_s": {"search": "fast"}}}, "0.05 to 30"),
    ({"tools": {"enabled": "yes"}}, "true or false"),
    ({"tools": {"shadow": 1}}, "true or false"),
    ({"tools": {"bogus": 1}}, "unknown setting"),
    ({"tools": []}, "must be an object"),
    ({"tools": {"chain": "search"}}, "list of decider names"),
    ({"tools": {"min_confidence": []}}, "object"),
    ({"enabled": "no"}, "true or false"),
    ({"max_per_task": 0}, "1 to 10000"),
    ({"max_per_task": 10_001}, "1 to 10000"),
    ({"max_model_tokens_per_task": -1}, "0 to 100000"),
    ({"max_model_tokens_per_task": 100_001}, "0 to 100000"),
    ({"max_per_task": True}, "whole number"),
])
def test_invalid_decision_settings_are_rejected_with_a_reason(raw: dict[str, Any], fragment: str) -> None:
    parsed, errs = parse_decisions(raw)
    assert parsed is None and any(fragment in e for e in errs), errs


def test_decisions_must_be_an_object() -> None:
    assert parse_decisions([]) == (None, ["decisions must be an object"])


def test_all_known_deciders_are_valid_for_some_question() -> None:
    assert DECIDERS == set().union(*domain.KIND_DECIDERS.values())


def test_decisions_are_part_of_the_settings_file() -> None:
    assert default_settings().decisions == DecisionSettings()
    raw = settings_to_dict(default_settings())
    assert raw["decisions"]["tools"]["chain"] == ["search"]
    raw["decisions"]["tools"]["timeout_s"] = {"search": 2}
    parsed, errs = parse_settings(raw)
    assert not errs and parsed is not None
    assert parsed.decisions.for_kind(Kind.TOOLS).chain[0].timeout_s == 2.0
    assert settings_to_dict(parsed)["decisions"]["tools"]["timeout_s"] == {"search": 2.0}


def test_invalid_decisions_make_the_settings_invalid_so_defaults_are_used() -> None:
    raw = settings_to_dict(default_settings())
    raw["decisions"]["pick"]["chain"] = ["nope"]
    parsed, errs = parse_settings(raw)
    assert parsed is None and any("unknown decider" in e for e in errs)


def test_settings_without_a_decisions_section_still_load() -> None:
    raw = settings_to_dict(default_settings())
    del raw["decisions"]
    parsed, errs = parse_settings(raw)
    assert not errs and parsed is not None and parsed.decisions == DecisionSettings()


@pytest.mark.parametrize("value, ok", [(0, True), (1, True), (0.5, True), (-0.01, False), (1.01, False),
                                       (float("nan"), False), (float("inf"), False), (True, False), ("0.5", False),
                                       (None, False)])
def test_confidence_must_be_a_real_number_from_zero_to_one(value: object, ok: bool) -> None:
    assert valid_confidence(value) is ok


# ---- safety by construction ---------------------------------------------------------------------------
FORBIDDEN = ("allow", "approv", "permit", "grant", "deny", "authori", "verdict", "policy")


@pytest.mark.parametrize("cls", [Answer, Outcome, Request, DecisionRecord])
def test_no_result_type_has_a_field_that_could_express_allow_or_approve(cls: type) -> None:
    names = [f.name.lower() for f in dataclasses.fields(cls)]
    assert not [n for n in names for word in FORBIDDEN if word in n], names


def test_an_outcome_can_only_carry_text_ids_and_numbers() -> None:
    kinds = {f.name: str(f.type) for f in dataclasses.fields(Outcome)}
    assert "bool" not in " ".join(kinds.values())


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found |= {f"{node.module}.{a.name}" for a in node.names}
        elif isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
    return found


@pytest.mark.parametrize("path", [*sorted((SRC / "decide").glob("*.py")), SRC / "engine" / "decisions.py",
                                  SRC / "domain" / "decisions.py", SRC / "core" / "shortlist.py",
                                  SRC / "core" / "lexical.py", SRC / "core" / "calibration.py",
                                  SRC / "store" / "decisions.py"], ids=lambda p: p.name)
def test_the_decision_layer_never_imports_policy_approvals_or_grants(path: Path) -> None:
    banned = ("lilly.domain.policy", "lilly.domain.grants", "lilly.engine.approvals", "lilly.store.approvals",
              "lilly.providers", "lilly.tools")
    assert not [i for i in _imports(path) if i.startswith(banned)]


def test_laya_is_added_after_the_other_deciders_and_can_be_taken_out_again() -> None:
    from lilly.domain.decisions import with_laya

    on = with_laya(DecisionSettings(), True)
    assert [s.decider for s in on.for_kind(Kind.INSTRUCTIONS).chain] == ["rules", "laya"]
    assert [s.decider for s in on.for_kind(Kind.LOOP).chain] == ["loop", "laya"]
    assert [s.decider for s in on.for_kind(Kind.PICK).chain] == ["match", "laya"]
    assert [s.decider for s in on.for_kind(Kind.TOOLS).chain] == ["search"]      # it cannot rank tools
    assert with_laya(on, True) == on                                               # twice is the same as once
    assert with_laya(on, False) == DecisionSettings()
    parsed, errors = parse_decisions(decisions_to_dict(on))
    assert errors == [] and parsed == on
