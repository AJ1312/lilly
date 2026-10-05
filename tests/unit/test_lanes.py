"""The lane scheduler with fake steps: ordering, overlap, barriers, the worst-case rule, failure and cancellation."""
from __future__ import annotations

import asyncio
import gc
import random
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from lilly.domain.labels import Label, Mode, Risk, TaskCtx, Verdict
from lilly.domain.plan import tool_call
from lilly.domain.policy import PathScope, decide
from lilly.domain.tools_registry import ToolSpec
from lilly.engine.lanes import LaneScheduler, dependencies, parallel_eligible

SCOPE = PathScope([])
SPECS: dict[str, ToolSpec] = {
    "read": ToolSpec(Risk.R0, path_args=()),
    "private": ToolSpec(Risk.R0, reads_label=Label.PERSONAL, path_args=()),
    "web": ToolSpec(Risk.R0, egress=True, untrusted=True, path_args=()),
    "send": ToolSpec(Risk.R0, egress=True, path_args=()),
    "file": ToolSpec(Risk.R0, path_args=("path",)),
    "write": ToolSpec(Risk.R1, path_args=()),
    "press": ToolSpec(Risk.R2, egress=True, confirm=True, path_args=()),
    "llm.work": ToolSpec(Risk.R0, path_args=()),
}


class Boom(Exception):
    pass


def step(sid: str, tool: str = "read", **args: object) -> dict[str, Any]:
    return {"id": sid, "tool": tool, "args": args}


@dataclass
class Harness:
    """Fake steps that sleep, log when they start and end, and fold their effect into one shared context."""

    ctx: TaskCtx = field(default_factory=lambda: TaskCtx(Label.PUBLIC, False, Mode.ASK))
    delays: dict[str, float] = field(default_factory=dict)
    fails: set[str] = field(default_factory=set)
    log: list[tuple[str, str]] = field(default_factory=list)
    verdicts: dict[str, Verdict] = field(default_factory=dict)
    abandoned: list[str] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)
    running: int = 0
    peak: int = 0

    async def run_step(self, st: Mapping[str, Any]) -> str:
        sid, spec = st["id"], SPECS[st["tool"]]
        self.log.append(("start", sid))
        self.running += 1
        self.peak = max(self.peak, self.running)
        self.verdicts[sid] = decide(tool_call(st["tool"], spec, {}), self.ctx, SCOPE)[0]
        try:
            await asyncio.sleep(self.delays.get(sid, 0.0))
            if sid in self.fails:
                raise Boom(sid)
        except asyncio.CancelledError:
            self.cancelled.append(sid)
            raise
        finally:
            self.running -= 1
        self.ctx = self.ctx.absorb(spec.reads_label, spec.untrusted)
        self.log.append(("end", sid))
        return f"out-{sid}"

    async def abandon(self, st: Mapping[str, Any]) -> None:
        self.abandoned.append(st["id"])

    async def go(self, steps: list[dict[str, Any]], lanes: int = 3, specs: Mapping[str, ToolSpec] = SPECS) -> None:
        sched = LaneScheduler(specs, SCOPE, lanes, lambda: self.ctx)
        await sched.run(steps, self.run_step, self.abandon, self.outputs)

    def at(self, kind: str, sid: str) -> int:
        return self.log.index((kind, sid))


def test_dependencies_come_from_references_in_plan_order() -> None:
    steps = [step("a"), step("b"), step("c", text="$b.output and $a.output"), step("d", n=["$c.output"], m="$zz.output")]
    assert dependencies(steps) == {"a": (), "b": (), "c": ("a", "b"), "d": ("c",)}


@pytest.mark.parametrize("tool, ok", [("read", True), ("write", False), ("press", False), ("llm.work", False),
                                      ("nope", False)])
def test_only_plain_reads_may_run_beside_others(tool: str, ok: bool) -> None:
    assert parallel_eligible(step("a", tool), SPECS.get(tool), TaskCtx(mode=Mode.OPEN), SCOPE) is ok


def test_a_read_whose_path_comes_from_an_earlier_step_waits_its_turn() -> None:
    assert not parallel_eligible(step("b", "file", path="$a.output"), SPECS["file"], TaskCtx(mode=Mode.OPEN), SCOPE)
    assert parallel_eligible(step("b", "file", other="$a.output"), SPECS["file"], TaskCtx(mode=Mode.OPEN), SCOPE)


async def test_a_step_never_starts_before_the_steps_it_uses_have_finished() -> None:
    h = Harness(delays={"a": 0.03, "b": 0.01})
    await h.go([step("a"), step("b"), step("c", x="$a.output"), step("d", x="$b.output $c.output")])
    assert h.at("end", "a") < h.at("start", "c") and h.at("end", "b") < h.at("start", "d")
    assert h.at("end", "c") < h.at("start", "d")
    assert h.at("start", "b") < h.at("end", "a")          # b did not wait for a
    assert h.outputs == {"a": "out-a", "b": "out-b", "c": "out-c", "d": "out-d"}


async def test_independent_reads_overlap_and_one_lane_is_strictly_sequential() -> None:
    steps = [step(f"s{i}") for i in range(3)]
    delay = {f"s{i}": 0.1 for i in range(3)}
    wide = Harness(delays=delay)
    began = time.monotonic()
    await wide.go(steps, lanes=3)
    assert time.monotonic() - began < 0.22 and wide.peak == 3

    narrow = Harness(delays=delay)
    began = time.monotonic()
    await narrow.go(steps, lanes=1)
    assert time.monotonic() - began >= 0.3 and narrow.peak == 1
    assert narrow.log == [(k, f"s{i}") for i in range(3) for k in ("start", "end")]


async def test_no_more_steps_run_at_once_than_there_are_lanes() -> None:
    h = Harness(delays={f"s{i}": 0.01 for i in range(7)})
    await h.go([step(f"s{i}") for i in range(7)], lanes=2)
    assert h.peak == 2 and len(h.outputs) == 7


@pytest.mark.parametrize("barrier, mode", [("write", Mode.ASK), ("write", Mode.OPEN), ("press", Mode.OPEN)])
async def test_a_change_or_a_computer_action_runs_alone_with_everything_else_before_or_after(barrier: str,
                                                                                            mode: Mode) -> None:
    h = Harness(ctx=TaskCtx(mode=mode), delays={"r1": 0.03, "r2": 0.03, "w": 0.03, "r3": 0.01, "r4": 0.01})
    await h.go([step("r1"), step("r2"), step("w", barrier), step("r3"), step("r4")], lanes=4)
    assert max(h.at("end", "r1"), h.at("end", "r2")) < h.at("start", "w")
    assert h.at("end", "w") == h.at("start", "w") + 1
    assert h.at("end", "w") < min(h.at("start", "r3"), h.at("start", "r4"))
    assert h.at("start", "r3") < h.at("end", "r4")        # the reads after the barrier overlap again


async def test_the_final_model_step_and_unknown_tools_are_barriers() -> None:
    h = Harness(delays={"r1": 0.02, "r2": 0.02})
    await h.go([step("r1"), step("r2"), step("fin", "llm.work", x="$r1.output")])
    assert h.at("end", "r2") < h.at("start", "fin") and h.peak == 2

    h = Harness()
    with pytest.raises(KeyError):                        # no spec: it is held back to run alone, and fails there
        await h.go([step("r1"), step("x", "ghost")], specs={"read": SPECS["read"]})
    assert h.at("end", "r1") == 1


async def test_a_read_that_policy_would_stop_after_an_earlier_read_does_not_run_beside_it() -> None:
    """The worst-case rule: web access is fine now, but once the private read has run it would need approval."""
    tainted_open = TaskCtx(Label.PUBLIC, True, Mode.OPEN)
    assert decide(tool_call("send", SPECS["send"], {}), tainted_open, SCOPE)[0] is Verdict.ALLOW
    h = Harness(ctx=tainted_open, delays={"p": 0.03, "w": 0.03})
    await h.go([step("p", "private"), step("w", "send")])
    assert h.at("end", "p") < h.at("start", "w")
    assert h.verdicts["w"] is Verdict.NEEDS_APPROVAL      # and it is asked, as in a sequential run

    free = Harness(ctx=tainted_open, delays={"p": 0.03, "w": 0.03})
    await free.go([step("p", "read"), step("w", "send")])
    assert free.at("start", "w") < free.at("end", "p")    # nothing private ahead of it: they overlap


async def test_steps_that_need_approval_are_never_asked_about_together() -> None:
    h = Harness(ctx=TaskCtx(mode=Mode.ASK), delays={f"s{i}": 0.02 for i in range(4)})
    await h.go([step(f"s{i}", "private") for i in range(4)], lanes=4)
    assert h.peak == 1 and all(v is Verdict.NEEDS_APPROVAL for v in h.verdicts.values())


async def test_first_failure_stops_the_steps_beside_it_and_keeps_what_finished() -> None:
    h = Harness(delays={"fast": 0.0, "bad": 0.03, "slow": 5.0, "never": 0.0}, fails={"bad"})
    with pytest.raises(Boom, match="bad"):
        await h.go([step("fast"), step("bad"), step("slow"), step("fin", "llm.work", x="$slow.output")], lanes=3)
    assert h.outputs == {"fast": "out-fast"}
    assert h.cancelled == ["slow"] and h.abandoned == ["slow"]
    assert "fin" not in {sid for _, sid in h.log}
    assert asyncio.all_tasks() == {asyncio.current_task()}


async def test_a_step_that_finishes_while_its_neighbours_are_being_stopped_keeps_its_output() -> None:
    h = Harness(delays={"bad": 0.01, "stubborn": 5.0}, fails={"bad"})
    inner = h.run_step

    async def run_step(st: Mapping[str, Any]) -> str:
        if st["id"] != "stubborn":
            return await inner(st)
        try:
            await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            return "wrapped up"      # it was already finishing when the stop arrived
        return "not reached"

    sched = LaneScheduler(SPECS, SCOPE, 3, lambda: h.ctx)
    with pytest.raises(Boom):
        await sched.run([step("bad"), step("stubborn")], run_step, h.abandon, h.outputs)
    assert h.outputs == {"stubborn": "wrapped up"} and h.abandoned == []


async def test_when_several_steps_fail_together_the_earliest_failure_is_raised_and_nothing_leaks() -> None:
    loop = asyncio.get_running_loop()
    complaints: list[dict[str, Any]] = []
    loop.set_exception_handler(lambda _loop, ctx: complaints.append(ctx))
    try:
        h = Harness(fails={"a", "b", "c"})
        with pytest.raises(Boom, match="a"):
            await h.go([step("a"), step("b"), step("c")])
        gc.collect()
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(None)
    assert complaints == [] and asyncio.all_tasks() == {asyncio.current_task()}


async def test_stopping_the_whole_run_stops_every_step_and_leaves_no_task_behind() -> None:
    h = Harness(delays={"a": 5.0, "b": 5.0, "c": 5.0})
    run = asyncio.create_task(h.go([step("a"), step("b"), step("c")]))
    await asyncio.sleep(0.02)
    assert h.running == 3
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert sorted(h.cancelled) == ["a", "b", "c"] and h.abandoned == []
    assert asyncio.all_tasks() == {asyncio.current_task()}


# ---- property: any plan, any width, same verdicts and same final context as running one at a time ----------------

def random_plan(rng: random.Random) -> tuple[dict[str, ToolSpec], list[dict[str, Any]], dict[str, int], TaskCtx]:
    specs: dict[str, ToolSpec] = {}
    for i in range(rng.randint(2, 6)):
        confirm = rng.random() < 0.15
        specs[f"t{i}"] = ToolSpec(
            risk=rng.choice([Risk.R0, Risk.R0, Risk.R0, Risk.R1, Risk.R2]), egress=rng.random() < 0.4,
            reads_label=rng.choice([Label.PUBLIC, Label.PUBLIC, Label.PERSONAL, Label.SECRET]),
            untrusted=rng.random() < 0.4, confirm=confirm, path_args=())
    specs["llm.work"] = SPECS["llm.work"]
    steps: list[dict[str, Any]] = []
    for i in range(rng.randint(1, 10)):
        uses = [f"${steps[j]['id']}.output" for j in range(i) if rng.random() < 0.25]
        steps.append(step(f"s{i}", rng.choice(sorted(specs)), text=" ".join(uses)))
    ticks = {st["id"]: rng.randint(0, 4) for st in steps}
    ctx = TaskCtx(rng.choice([Label.PUBLIC, Label.PERSONAL]), rng.random() < 0.4, rng.choice(list(Mode)))
    return specs, steps, ticks, ctx


class TickHarness:
    """Steps that take a set number of event-loop turns, so a run is the same every time for a given plan."""

    def __init__(self, specs: Mapping[str, ToolSpec], ticks: Mapping[str, int], ctx: TaskCtx) -> None:
        self.specs, self.ticks, self.ctx = specs, ticks, ctx
        self.log: list[tuple[str, str]] = []
        self.verdicts: dict[str, Verdict] = {}
        self.peak = self.running = 0

    async def run_step(self, st: Mapping[str, Any]) -> str:
        sid, spec = st["id"], self.specs[st["tool"]]
        self.log.append(("start", sid))
        self.running += 1
        self.peak = max(self.peak, self.running)
        self.verdicts[sid] = decide(tool_call(st["tool"], spec, {}), self.ctx, SCOPE)[0]
        for _ in range(self.ticks[sid]):
            await asyncio.sleep(0)
        self.running -= 1
        self.ctx = self.ctx.absorb(spec.reads_label, spec.untrusted)
        self.log.append(("end", sid))
        return sid

    async def run(self, steps: list[dict[str, Any]], width: int) -> None:
        async def nobody(_: Mapping[str, Any]) -> None:
            raise AssertionError("nothing fails in this run")

        async with asyncio.timeout(5):
            await LaneScheduler(self.specs, SCOPE, width, lambda: self.ctx).run(steps, self.run_step, nobody, {})


async def test_any_plan_runs_safely_and_decides_exactly_as_a_one_at_a_time_run_would() -> None:
    rng = random.Random(20260404)
    for case in range(400):
        specs, steps, ticks, ctx = random_plan(rng)
        width = rng.randint(1, 8)
        deps = dependencies(steps)
        seq, par = TickHarness(specs, ticks, ctx), TickHarness(specs, ticks, ctx)
        await seq.run(steps, 1)
        await par.run(steps, width)
        where = f"case {case}, width {width}, plan {[(s['id'], s['tool']) for s in steps]}"

        assert seq.log == [(k, s["id"]) for s in steps for k in ("start", "end")], where
        assert len(par.log) == 2 * len(steps) and par.peak <= width, where
        for st in steps:
            for dep in deps[st["id"]]:
                assert par.log.index(("end", dep)) < par.log.index(("start", st["id"])), where
            if par.verdicts[st["id"]] is not Verdict.ALLOW:
                start = par.log.index(("start", st["id"]))
                assert par.log[start + 1] == ("end", st["id"]), f"{st['id']} overlapped another step; {where}"
        assert par.verdicts == seq.verdicts, where
        assert par.ctx == seq.ctx, where
