from __future__ import annotations

import pytest

from lilly.decide.system1 import (
    ComplexityLevel,
    DecisionType,
    System1Engine,
    System1Request,
    TaskClass,
)
from lilly.domain.decisions import Answer


class RecordingLaya:
    def __init__(self, choice: str = "standard") -> None:
        self.choice = choice
        self.requests = []

    async def decide(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return Answer("laya", self.choice, 0.9)


@pytest.mark.asyncio
async def test_system1_offers_typed_closed_choices_to_laya() -> None:
    laya = RecordingLaya()
    engine = System1Engine(laya_decider=laya, laya_enabled=True)
    await engine.decide(System1Request(DecisionType.MODEL_TIER_SELECTION, task_id="t", user_request="choose"))
    assert {option.id for option in laya.requests[-1].options} == {"quick", "standard", "strong", "vision", "specialized"}

    await engine.decide(System1Request(DecisionType.TOOL_FAMILY_SELECTION, task_id="t", available_tools=("computer.click",)))
    assert [option.id for option in laya.requests[-1].options] == ["computer.click"]

    await engine.decide(System1Request(DecisionType.VERIFICATION_NECESSITY, task_id="t"))
    assert {option.id for option in laya.requests[-1].options} == {"none", "light", "standard", "thorough"}


@pytest.mark.asyncio
async def test_system1_can_clear_laya_and_use_default() -> None:
    laya = RecordingLaya("strong")
    engine = System1Engine(laya_decider=laya, laya_enabled=True)
    engine.set_laya_decider(None)
    result = await engine.decide(System1Request(DecisionType.MODEL_TIER_SELECTION))
    assert result.tier.value == "standard"  # type: ignore[attr-defined]


def test_system1_uses_exact_enum_values_for_laya_answers() -> None:
    engine = System1Engine()

    classification = engine._convert_from_laya_answer(
        DecisionType.TASK_CLASSIFICATION, Answer("laya", "coding", 0.9)
    )
    assert classification.task_class is TaskClass.CODING

    complexity = engine._convert_from_laya_answer(
        DecisionType.COMPLEXITY_ESTIMATION, Answer("laya", "expert", 0.9)
    )
    assert complexity.level is ComplexityLevel.EXPERT

    with pytest.raises(ValueError):
        engine._convert_from_laya_answer(
            DecisionType.COMPLEXITY_ESTIMATION, Answer("laya", "very complex reasoning", 0.9)
        )

    with pytest.raises(ValueError):
        engine._convert_from_laya_answer(
            DecisionType.CAPABILITY_ROUTING, Answer("laya", "vision and tools", 0.9)
        )
