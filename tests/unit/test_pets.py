"""A pet's look is validated at the edge and its skills reach the planner in one fixed shape."""
from __future__ import annotations

import pytest

from lilly.domain.errors import ValidationFailed
from lilly.domain.pets import ACCESSORIES, EYES, PETS, Look, agent_prompt, look_to_dict, parse_look


def test_a_missing_or_empty_look_is_the_default() -> None:
    assert parse_look({}) == Look(None, "none", "round", True)
    assert parse_look({"hue": 10}) == Look(10, "none", "round", True)


def test_a_full_look_round_trips() -> None:
    look = Look(359, "crown", "sparkle", False)
    assert parse_look(look_to_dict(look)) == look
    assert look_to_dict(look) == {"hue": 359, "accessory": "crown", "eyes": "sparkle", "blush": False}


def test_the_default_look_serialises_a_null_hue() -> None:
    assert look_to_dict(Look(None, "none", "round", True)) == {"hue": None, "accessory": "none", "eyes": "round",
                                                              "blush": True}


@pytest.mark.parametrize("hue", [0, 359])
def test_hue_bounds_are_inclusive(hue: int) -> None:
    assert parse_look({"hue": hue}).hue == hue


@pytest.mark.parametrize("raw", [
    {"hue": -1}, {"hue": 360}, {"hue": True}, {"hue": 1.5}, {"hue": "10"},
    {"accessory": "tiara"}, {"accessory": 3}, {"eyes": "laser"}, {"eyes": None},
    {"blush": 1}, {"blush": "yes"}, {"blush": None},
    {"sparkles": True}, {"hue": 5, "extra": 1},
    None, [], "x", 3,
])
def test_a_bad_look_is_rejected(raw: object) -> None:
    with pytest.raises(ValidationFailed):
        parse_look(raw)


def test_every_listed_choice_is_accepted() -> None:
    for accessory in ACCESSORIES:
        assert parse_look({"accessory": accessory}).accessory == accessory
    for eyes in EYES:
        assert parse_look({"eyes": eyes}).eyes == eyes
    assert "lily" in PETS and len(PETS) == 8


def test_agent_prompt_adds_skills_after_the_instructions() -> None:
    assert agent_prompt("Be brief.", "# Skills\nDo X.") == "Be brief.\n\nSkills of this agent:\n# Skills\nDo X."


@pytest.mark.parametrize("skills", ["", "   \n"])
def test_agent_prompt_without_skills_is_the_instructions_alone(skills: str) -> None:
    assert agent_prompt("Be brief.", skills) == "Be brief."


def test_agent_prompt_with_only_skills() -> None:
    assert agent_prompt("", "Do X.") == "\n\nSkills of this agent:\nDo X."
