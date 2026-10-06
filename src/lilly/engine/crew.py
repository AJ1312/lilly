"""Crew routing and role model resolution.

Implements Part 5:
- resolve_ref for auto, pins, and tag:<tag> (with SHEET-010 fallback hint)
- choose_pet routing: @handle -> rules (lexical scoring) -> Laya PICK -> default pet
"""
from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

from lilly.core.lexical import score
from lilly.domain.decisions import Context, Kind, Option
from lilly.domain.settings import ModelSpec
from lilly.engine.decisions import DecisionPipeline
from lilly.store.agents import AgentRow, parsed_sheet_for

log = logging.getLogger(__name__)

_HANDLE_RE = re.compile(r"@([a-zA-Z0-9_\-]+)")


@dataclass(frozen=True, slots=True)
class RouteResult:
    pet: str
    how: str  # "explicit", "rules", "laya", "default"
    confidence: float
    alternatives: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "pet": self.pet,
            "how": self.how,
            "confidence": self.confidence,
            "alternatives": list(self.alternatives),
        }


def resolve_ref(
    ref: str | None,
    available_models: Sequence[ModelSpec],
    role: str = "act",
) -> tuple[str | None, str | None]:
    """Resolves a model reference (auto, exact pin, or tag:<tag>).

    Returns (pinned_model_or_none, warning_hint_or_none).
    """
    if not ref or ref == "auto":
        return None, None

    clean_ref = ref.strip()
    if clean_ref.startswith("tag:"):
        tag_name = clean_ref[4:].strip().lower()
        matching = [m.name for m in available_models if tag_name in {t.lower() for t in m.tags}]
        if matching:
            return matching[0], None
        # Tag not found: behave as auto and provide SHEET-010 hint
        hint = f'no model has the tag "{tag_name}", so Lilly will choose automatically for the "{role}" role.'
        return None, hint

    # Exact pin
    return clean_ref, None


async def choose_pet(
    goal: str,
    pets: Sequence[AgentRow],
    pipeline: DecisionPipeline | None = None,
    min_confidence: float = 0.6,
) -> RouteResult:
    """Routes a task request to the best pet in the crew.

    Order:
    1. Explicit @handle
    2. Rules (lexical score of request against description and skill names)
    3. Laya PICK if active and confident
    4. Default pet (first pet / Lily)
    """
    if not pets:
        return RouteResult(pet="", how="default", confidence=0.0)

    # 1. Explicit @handle
    handle_match = _HANDLE_RE.search(goal)
    if handle_match:
        handle = handle_match.group(1).lower()
        for p in pets:
            if p.name.lower() == handle or p.pet.lower() == handle or p.id == handle:
                alts = tuple(other.name for other in pets if other.id != p.id)
                return RouteResult(pet=p.name, how="explicit", confidence=1.0, alternatives=alts)

    # 2. Rules: Lexical scoring against description and skill names
    texts: dict[str, str] = {}
    pet_by_id: dict[str, AgentRow] = {}
    for p in pets:
        pet_by_id[p.id] = p
        sheet = parsed_sheet_for(p)
        desc = sheet.description if sheet else ""
        skills_text = " ".join(sheet.skills.keys()) if sheet and sheet.skills else p.skills
        # Include persona keywords as well
        persona = sheet.persona if sheet else p.instructions
        combined = f"{p.name} {p.pet} {desc} {skills_text} {persona}"
        texts[p.id] = combined

    scored = score(goal, texts)
    if scored.coverage >= min_confidence and any(v > 0 for v in scored.scores.values()):
        # Sort pets by score descending
        sorted_pets = sorted(texts.keys(), key=lambda pid: scored.scores[pid], reverse=True)
        best_id = sorted_pets[0]
        if scored.scores[best_id] > 0:
            best_pet = pet_by_id[best_id]
            alts = tuple(pet_by_id[pid].name for pid in sorted_pets[1:] if scored.scores[pid] > 0)
            return RouteResult(
                pet=best_pet.name,
                how="rules",
                confidence=round(scored.coverage, 2),
                alternatives=alts,
            )

    # 3. Laya PICK if active
    if pipeline is not None and pipeline.active(Kind.PICK):
        try:
            pet_options: list[Option] = []
            for p in pets:
                sheet = parsed_sheet_for(p)
                desc = sheet.description if sheet and sheet.description else (p.instructions or p.pet)
                pet_options.append(Option(id=p.id, label=desc))
            decision = await pipeline.decide(Kind.PICK, "route_preview", tuple(pet_options), Context(text=goal))
            if decision.choice and decision.confidence is not None and decision.confidence >= min_confidence:
                matching = [p for p in pets if p.name == decision.choice or p.id == decision.choice]
                if matching:
                    alts = tuple(p.name for p in pets if p.id != matching[0].id)
                    return RouteResult(
                        pet=matching[0].name,
                        how="laya",
                        confidence=round(decision.confidence, 2),
                        alternatives=alts,
                    )
        except Exception as exc:
            log.debug("Laya pet routing failed, using default: %s", exc)

    # 4. None (the default pet)
    # Prefer lily if present, else first pet
    default = pets[0]
    for p in pets:
        if p.pet.lower() == "lily" or p.name.lower() == "lily":
            default = p
            break

    alts = tuple(p.name for p in pets if p.id != default.id)
    return RouteResult(pet=default.name, how="default", confidence=0.0, alternatives=alts)
