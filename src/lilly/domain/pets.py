"""What a pet looks like and how what its owner wrote for it reaches the planner."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lilly.domain.errors import ValidationFailed

PETS = ("lily", "pip", "mochi", "bao", "fern", "juno", "otto", "wisp")
ACCESSORIES = ("none", "bow", "glasses", "hat", "scarf", "crown", "headphones")
EYES = ("round", "sparkle", "sleepy")
MAX_HUE = 359


@dataclass(frozen=True, slots=True)
class Look:
    hue: int | None          # degrees on the colour wheel; None keeps the pet's own colours
    accessory: str
    eyes: str
    blush: bool


DEFAULT_LOOK = Look(None, "none", "round", True)


def _choice(raw: dict[str, Any], key: str, allowed: tuple[str, ...], default: str) -> str:
    value = raw.get(key, default)
    if not isinstance(value, str) or value not in allowed:
        raise ValidationFailed(f"look.{key} must be one of {', '.join(allowed)}")
    return value


def parse_look(raw: object) -> Look:
    """A look from a JSON object. Keys left out take their defaults; anything unknown or mistyped is refused."""
    if not isinstance(raw, dict):
        raise ValidationFailed("look must be an object")
    unknown = set(raw) - set(DEFAULT_LOOK.__slots__)
    if unknown:
        raise ValidationFailed(f"look has unknown fields: {', '.join(sorted(map(str, unknown)))}")
    hue = raw.get("hue", DEFAULT_LOOK.hue)
    if hue is not None and (isinstance(hue, bool) or not isinstance(hue, int) or not 0 <= hue <= MAX_HUE):
        raise ValidationFailed(f"look.hue must be a whole number from 0 to {MAX_HUE}")
    blush = raw.get("blush", DEFAULT_LOOK.blush)
    if not isinstance(blush, bool):
        raise ValidationFailed("look.blush must be true or false")
    return Look(hue, _choice(raw, "accessory", ACCESSORIES, DEFAULT_LOOK.accessory),
                _choice(raw, "eyes", EYES, DEFAULT_LOOK.eyes), blush)


def look_to_dict(look: Look) -> dict[str, Any]:
    return {"hue": look.hue, "accessory": look.accessory, "eyes": look.eyes, "blush": look.blush}


def agent_prompt(instructions: str, skills: str) -> str:
    """The owner's standing instructions, followed by the pet's skills when it has any."""
    if not skills.strip():
        return instructions
    return f"{instructions}\n\nSkills of this agent:\n{skills}"
