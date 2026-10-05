"""The pipeline: chain order, fall-through, time limits, caps, shadow mode, and that nothing it returns can be trusted
less than the options the caller offered."""
from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace

import pytest

from lilly.domain.decisions import (
    Answer,
    ChainStep,
    Context,
    Decider,
    DecisionRecord,
    DecisionSettings,
    Kind,
    KindSettings,
    Option,
    Request,
)
from lilly.engine.decisions import MAX_TASKS_TRACKED, DecisionPipeline
from tests.helpers import Clock

OPTIONS = (Option("a", "alpha"), Option("b", "beta"), Option("c", "gamma"))
CTX = Context(text="my secret goal sk-abcdefghijklmnopqrstuv")

Behaviour = Callable[[Request], Awaitable[Answer | None]]


@dataclass
class Fake:
    name: str
    act: Behaviour
    requests: list[Request] = field(default_factory=list)

    async def decide(self, request: Request) -> Answer | None:
        self.requests.append(request)
        return await self.act(request)


def says(choice: str | None, confidence: float = 0.9, **kw: object) -> Behaviour:
    async def act(request: Request) -> Answer | None:
        return Answer("x", choice, confidence, **kw)  # type: ignore[arg-type]
    return act


async def silent(request: Request) -> Answer | None:
    return None


async def explodes(request: Request) -> Answer | None:
    raise RuntimeError("boom with a secret")


async def hangs(request: Request) -> Answer | None:
    await asyncio.sleep(60)
    return None


@dataclass
class ListSink:
    records: list[DecisionRecord] = field(default_factory=list)
    fail: bool = False

    async def record(self, record: DecisionRecord) -> int | None:
        if self.fail:
            raise OSError("disk")
        self.records.append(record)
        return len(self.records)


def settings(*steps: ChainStep, kind: Kind = Kind.PICK, shadow: bool = False, **over: object) -> DecisionSettings:
    base = DecisionSettings()
    kinds = {**base.kinds, kind.value: KindSettings(True, shadow, steps)}
    return replace(base, kinds=kinds, **over)  # type: ignore[arg-type]


def step(name: str, minimum: float = 0.5, timeout: float = 1.0) -> ChainStep:
    return ChainStep(name, minimum, timeout)


def pipe(cfg: DecisionSettings, *deciders: Fake, sink: ListSink | None = None) -> tuple[DecisionPipeline, ListSink]:
    sink = sink or ListSink()
    registry: dict[str, Decider] = {d.name: d for d in deciders}
    return DecisionPipeline(lambda: cfg, lambda: registry, sink, Clock()), sink


async def test_the_first_confident_valid_answer_wins_and_later_deciders_are_not_asked() -> None:
    first, second = Fake("rules", says("b")), Fake("match", says("c"))
    p, sink = pipe(settings(step("rules"), step("match")), first, second)
    out = await p.decide(Kind.PICK, "t1", OPTIONS, CTX)
    assert (out.choice, out.decider, out.confidence) == ("b", "rules", 0.9)
    assert second.requests == []
    assert [(r.decider, r.choice, r.shadow) for r in sink.records] == [("rules", "b", False)]
    assert out.log_id == 1


async def test_a_decider_that_is_not_sure_enough_falls_through_to_the_next() -> None:
    p, sink = pipe(settings(step("rules", 0.8), step("match")), Fake("rules", says("a", 0.79)), Fake("match", says("c", 0.6)))
    out = await p.decide(Kind.PICK, "t", OPTIONS, CTX)
    assert (out.choice, out.decider) == ("c", "match")
    assert "rules was not sure enough" in sink.records[0].reason


async def test_an_answer_exactly_at_the_minimum_is_accepted() -> None:
    p, _ = pipe(settings(step("rules", 0.8)), Fake("rules", says("a", 0.8)))
    assert (await p.decide(Kind.PICK, "t", OPTIONS, CTX)).choice == "a"


async def test_abstaining_errors_and_timeouts_fall_through_and_never_raise() -> None:
    cfg = settings(step("quiet"), step("broken"), step("slow", timeout=0.05), step("good"))
    p, sink = pipe(cfg, Fake("quiet", silent), Fake("broken", explodes), Fake("slow", hangs), Fake("good", says("a")))
    out = await p.decide(Kind.PICK, "t", OPTIONS, CTX)
    assert out.choice == "a" and out.decider == "good"
    reason = sink.records[0].reason
    assert "quiet had no answer" in reason and "broken failed" in reason and "slow ran out of time" in reason
    assert "secret" not in reason


async def test_a_slow_decider_is_cut_off_at_its_time_limit() -> None:
    p, _ = pipe(settings(step("slow", timeout=0.05)), Fake("slow", hangs))
    started = asyncio.get_running_loop().time()
    out = await p.decide(Kind.PICK, "t", OPTIONS, CTX)
    assert out.choice is None and asyncio.get_running_loop().time() - started < 1.0


@pytest.mark.parametrize("answer", ["zzz", "", "A", None])
async def test_an_answer_outside_the_offered_options_counts_as_no_answer(answer: str | None) -> None:
    p, sink = pipe(settings(step("rules"), step("match")), Fake("rules", says(answer, 1.0)), Fake("match", silent))
    out = await p.decide(Kind.PICK, "t", OPTIONS, CTX)
    assert out.choice is None and out.decider is None
    assert "rules answered outside the offered options" in sink.records[0].reason


async def test_a_ranking_that_names_an_unknown_option_is_refused() -> None:
    p, _ = pipe(settings(step("rules")), Fake("rules", says("a", 1.0, ranking=("a", "ghost"))))
    assert (await p.decide(Kind.PICK, "t", OPTIONS, CTX)).choice is None


async def test_a_valid_ranking_comes_back_with_the_choice_first() -> None:
    p, _ = pipe(settings(step("rules")), Fake("rules", says("b", 1.0, ranking=("c", "b"))))
    out = await p.decide(Kind.PICK, "t", OPTIONS, CTX)
    assert out.ranking == ("b", "c")


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), -1.0, 2.0])
async def test_an_impossible_confidence_is_refused(confidence: float) -> None:
    p, _ = pipe(settings(step("rules", 0.0)), Fake("rules", says("a", confidence)))
    assert (await p.decide(Kind.PICK, "t", OPTIONS, CTX)).choice is None


async def test_a_decider_that_returns_the_wrong_type_is_refused() -> None:
    async def junk(request: Request) -> Answer | None:
        return "a"  # type: ignore[return-value]
    p, _ = pipe(settings(step("rules")), Fake("rules", junk))
    assert (await p.decide(Kind.PICK, "t", OPTIONS, CTX)).choice is None


async def test_a_decider_in_the_chain_but_not_installed_is_skipped() -> None:
    p, sink = pipe(settings(step("laya"), step("match")), Fake("match", says("a")))
    out = await p.decide(Kind.PICK, "t", OPTIONS, CTX)
    assert out.decider == "match" and "laya is not installed" in sink.records[0].reason


async def test_when_nothing_answers_the_outcome_is_no_decision_and_is_logged() -> None:
    p, sink = pipe(settings(step("rules")), Fake("rules", silent))
    out = await p.decide(Kind.PICK, "t", OPTIONS, CTX)
    assert (out.choice, out.decider, out.ranking, out.confidence) == (None, None, (), None)
    assert sink.records[0].choice is None and sink.records[0].decider is None


async def test_an_empty_chain_makes_no_decision() -> None:
    p, sink = pipe(settings())
    out = await p.decide(Kind.PICK, "t", OPTIONS, CTX)
    assert out.choice is None and sink.records[0].reason == "no decider was configured"


async def test_shadow_mode_logs_the_answer_but_returns_no_decision() -> None:
    p, sink = pipe(settings(step("rules"), shadow=True), Fake("rules", says("b")))
    out = await p.decide(Kind.PICK, "t", OPTIONS, CTX)
    assert out.choice is None and out.decider is None and out.ranking == ()
    assert "would have chosen b" in out.reason
    assert (sink.records[0].choice, sink.records[0].decider, sink.records[0].shadow) == ("b", "rules", True)


async def test_shadow_mode_with_no_answer_still_logs() -> None:
    p, sink = pipe(settings(step("rules"), shadow=True), Fake("rules", silent))
    assert (await p.decide(Kind.PICK, "t", OPTIONS, CTX)).choice is None
    assert sink.records[0].shadow and sink.records[0].choice is None


async def test_the_master_switch_stops_everything_and_nothing_runs() -> None:
    d = Fake("rules", says("a"))
    p, sink = pipe(settings(step("rules"), enabled=False), d)
    out = await p.decide(Kind.PICK, "t", OPTIONS, CTX)
    assert out.choice is None and d.requests == [] and sink.records == []


async def test_a_question_that_is_switched_off_runs_nothing() -> None:
    d = Fake("rules", says("a"))
    cfg = settings(step("rules"))
    cfg = replace(cfg, kinds={**cfg.kinds, "pick": KindSettings(False, False, (step("rules"),))})
    p, sink = pipe(cfg, d)
    assert (await p.decide(Kind.PICK, "t", OPTIONS, CTX)).choice is None and d.requests == []


async def test_no_options_means_no_decision_without_asking_anyone() -> None:
    d = Fake("rules", says("a"))
    p, _ = pipe(settings(step("rules")), d)
    assert (await p.decide(Kind.PICK, "t", (), CTX)).choice is None and d.requests == []


async def test_the_configuration_is_read_on_every_call() -> None:
    cfg = [settings(step("rules"), enabled=False)]
    sink = ListSink()
    p = DecisionPipeline(lambda: cfg[0], lambda: {"rules": Fake("rules", says("a"))}, sink, Clock())
    assert (await p.decide(Kind.PICK, "t", OPTIONS, CTX)).choice is None
    cfg[0] = settings(step("rules"))
    assert (await p.decide(Kind.PICK, "t", OPTIONS, CTX)).choice == "a"


async def test_a_task_may_only_ask_so_many_questions() -> None:
    p, sink = pipe(settings(step("rules"), max_per_task=2), Fake("rules", says("a")))
    got = [(await p.decide(Kind.PICK, "t1", OPTIONS, CTX)).choice for _ in range(4)]
    assert got == ["a", "a", None, None]
    assert "decision allowance" in sink.records[2].reason
    assert (await p.decide(Kind.PICK, "t2", OPTIONS, CTX)).choice == "a"      # another task has its own allowance


async def test_tokens_spent_by_a_model_decider_reduce_what_is_left_for_the_task() -> None:
    spend = Fake("small_model", says("a", 0.9, tokens_used=700))
    p, _ = pipe(settings(step("small_model"), max_model_tokens_per_task=1000), spend)
    await p.decide(Kind.PICK, "t", OPTIONS, CTX)
    await p.decide(Kind.PICK, "t", OPTIONS, CTX)
    await p.decide(Kind.PICK, "other", OPTIONS, CTX)
    assert [r.tokens_left for r in spend.requests] == [1000, 300, 1000]


async def test_tokens_are_counted_even_when_the_answer_is_refused() -> None:
    spend = Fake("small_model", says("zzz", 0.9, tokens_used=400))
    p, _ = pipe(settings(step("small_model"), max_model_tokens_per_task=1000), spend)
    await p.decide(Kind.PICK, "t", OPTIONS, CTX)
    await p.decide(Kind.PICK, "t", OPTIONS, CTX)
    assert spend.requests[1].tokens_left == 600


async def test_the_request_carries_the_deciders_own_time_limit() -> None:
    d = Fake("rules", says("a"))
    p, _ = pipe(settings(step("rules", timeout=2.5)), d)
    await p.decide(Kind.PICK, "t", OPTIONS, CTX)
    assert d.requests[0].timeout_s == 2.5 and d.requests[0].options == OPTIONS and d.requests[0].kind is Kind.PICK


async def test_the_log_holds_a_redacted_short_summary_never_the_full_text() -> None:
    p, sink = pipe(settings(step("rules")), Fake("rules", says("a")))
    await p.decide(Kind.PICK, "t", OPTIONS, Context(text="x" * 5000 + " sk-abcdefghijklmnopqrstuv"))
    assert len(sink.records[0].summary) <= 300
    p2, sink2 = pipe(settings(step("rules")), Fake("rules", says("a")))
    await p2.decide(Kind.PICK, "t", OPTIONS, CTX)
    assert "sk-abc" not in sink2.records[0].summary and "[redacted]" in sink2.records[0].summary


async def test_a_failing_log_never_stops_a_decision() -> None:
    p, _ = pipe(settings(step("rules")), Fake("rules", says("a")), sink=ListSink(fail=True))
    out = await p.decide(Kind.PICK, "t", OPTIONS, CTX)
    assert out.choice == "a" and out.log_id is None


async def test_the_per_task_bookkeeping_is_bounded() -> None:
    p, _ = pipe(settings(step("rules")), Fake("rules", says("a")))
    for i in range(MAX_TASKS_TRACKED + 20):
        await p.decide(Kind.PICK, f"t{i}", OPTIONS, CTX)
    assert len(p._spent) == MAX_TASKS_TRACKED


# ---- property test ----------------------------------------------------------------------------------------
def _random_behaviour(rng: random.Random) -> Behaviour:
    kind = rng.choice(["valid", "valid", "valid", "stranger", "none", "boom", "bad_conf", "bad_rank", "junk"] + (["slow"] if rng.random() < 0.15 else []))

    async def act(request: Request) -> Answer | None:
        ids = [o.id for o in request.options]
        if kind == "boom":
            raise ValueError("x")
        if kind == "slow":
            await asyncio.sleep(0.2)
        if kind == "none":
            return None
        if kind == "junk":
            return 7  # type: ignore[return-value]
        choice = "stranger" if kind == "stranger" else rng.choice(ids)
        conf = rng.choice([float("nan"), 5.0, -2.0]) if kind == "bad_conf" else rng.random()
        rank = ("stranger",) if kind == "bad_rank" else tuple(rng.sample(ids, len(ids)))
        return Answer("x", choice, conf, rank, rng.randint(-5, 500))
    return act


def _fixed(cfg: DecisionSettings) -> Callable[[], DecisionSettings]:
    return lambda: cfg


async def test_random_configs_and_behaviours_never_escape_the_offered_options() -> None:
    rng = random.Random(20260514)
    names = ["search", "loop", "rules", "match", "small_model", "laya"]
    for case in range(400):
        kind = rng.choice(list(Kind))
        chain = tuple(ChainStep(n, rng.random(), 0.05) for n in rng.sample(names, rng.randint(0, 4)))
        shadow = rng.random() < 0.3
        cfg = DecisionSettings(rng.random() < 0.9, rng.randint(1, 4), rng.randint(0, 300),
                               {k.value: KindSettings(rng.random() < 0.9, shadow, chain) for k in Kind})
        registry: dict[str, Decider] = {n: Fake(n, _random_behaviour(rng)) for n in names if rng.random() < 0.8}
        options = tuple(Option(f"id{i}", f"label {i}") for i in range(rng.randint(0, 5)))
        sink = ListSink(fail=rng.random() < 0.1)
        p = DecisionPipeline(_fixed(cfg), lambda registry=registry: registry, sink, Clock())
        for _ in range(rng.randint(1, 5)):
            out = await p.decide(kind, rng.choice(["t", None]), options, Context(text="goal"))
            ids = {o.id for o in options}
            assert out.choice is None or out.choice in ids, case
            assert set(out.ranking) <= ids, case
            if out.choice is None:
                assert out.ranking == () and out.decider is None
            if shadow:
                assert out.choice is None and out.ranking == (), case


def test_a_question_is_active_only_when_it_is_switched_on_and_has_a_decider() -> None:
    on = DecisionSettings()
    assert pipe(on)[0].active(Kind.LOOP)
    assert not pipe(DecisionSettings(enabled=False))[0].active(Kind.LOOP)
    off = DecisionSettings(kinds={**on.kinds, "loop": KindSettings(enabled=False)})
    assert not pipe(off)[0].active(Kind.LOOP) and pipe(off)[0].active(Kind.PICK)
    empty = DecisionSettings(kinds={**on.kinds, "loop": KindSettings(chain=())})
    assert not pipe(empty)[0].active(Kind.LOOP)


async def test_a_decider_that_appears_later_is_used_without_rebuilding_the_pipeline() -> None:
    present: dict[str, Decider] = {}
    cfg = settings(step("late"))
    p = DecisionPipeline(lambda: cfg, lambda: present, ListSink(), Clock())
    assert (await p.decide(Kind.PICK, "t", OPTIONS, CTX)).choice is None
    present["late"] = Fake("late", says("a"))
    assert (await p.decide(Kind.PICK, "t", OPTIONS, CTX)).choice == "a"


# ---- Laya assist: the two extra questions and getting ready for them ---------------------------------------

@pytest.mark.parametrize("kind, yes, no", [(Kind.PLAN, "fits", "off"), (Kind.REPLY, "follows", "drifts")])
async def test_the_new_questions_act_when_asked_to_and_only_log_in_watch_mode(kind: Kind, yes: str, no: str) -> None:
    options = (Option(yes), Option(no))
    acting, sink = pipe(settings(step("laya"), kind=kind), Fake("laya", says(no)))
    out = await acting.decide(kind, "t", options, CTX)
    assert (out.choice, out.decider) == (no, "laya") and sink.records[0].kind is kind and not sink.records[0].shadow
    watching, sink = pipe(settings(step("laya"), kind=kind, shadow=True), Fake("laya", says(no)))
    out = await watching.decide(kind, "t", options, CTX)
    assert out.choice is None and "shadow, would have chosen" in out.reason
    assert (sink.records[0].choice, sink.records[0].shadow) == (no, True)


@pytest.mark.parametrize("kind", [Kind.PLAN, Kind.REPLY])
async def test_a_new_question_with_no_chain_is_not_active_and_asks_nobody(kind: Kind) -> None:
    fake = Fake("laya", says("fits"))
    p, sink = pipe(DecisionSettings(), fake)
    assert not p.active(kind)
    p.prepare(kind)
    assert fake.requests == [] and sink.records == []


@dataclass
class Warmer(Fake):
    warmed: int = 0

    def warm(self) -> None:
        self.warmed += 1


async def test_preparing_warms_the_deciders_of_an_active_question_that_can_warm_and_skips_the_rest() -> None:
    laya, small = Warmer("laya", silent), Fake("small_model", silent)
    p, _ = pipe(settings(step("small_model"), step("laya"), kind=Kind.PLAN), laya, small)
    p.prepare(Kind.PLAN)
    p.prepare(Kind.PLAN)
    assert laya.warmed == 2           # asking again is the decider's own business: warm() is idempotent
    assert small.requests == []       # nothing is asked, only warmed


async def test_preparing_does_nothing_for_a_question_that_is_off_or_whose_decider_is_missing() -> None:
    laya = Warmer("laya", silent)
    p, _ = pipe(settings(step("laya"), kind=Kind.PLAN), laya)
    p.prepare(Kind.REPLY)                                             # not switched on
    assert laya.warmed == 0
    gone, _ = pipe(settings(step("laya"), kind=Kind.PLAN))            # switched on, Laya not installed
    gone.prepare(Kind.PLAN)
    off, _ = pipe(settings(step("laya"), kind=Kind.PLAN, enabled=False), laya)
    off.prepare(Kind.PLAN)
    assert laya.warmed == 0


async def test_a_decider_that_fails_to_warm_never_breaks_the_caller() -> None:
    class Broken(Fake):
        def warm(self) -> None:
            raise RuntimeError("no loop")

    p, _ = pipe(settings(step("laya"), kind=Kind.PLAN), Broken("laya", silent))
    p.prepare(Kind.PLAN)
