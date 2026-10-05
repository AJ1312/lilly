"""LaneScheduler: run the independent read-only steps of a plan side by side, and everything else alone.

Pure scheduling, no I/O. Why this is safe, in short: the policy only ever gets stricter as a task learns more
(a higher label or taint can turn ALLOW into NEEDS_APPROVAL, never the other way round). So a step may start
early only when policy says ALLOW for it in the worst case, where the task has already read everything that every
earlier, unfinished step could still teach it. ALLOW in that worst case means ALLOW in the plan's own order.
Every other step is a barrier: it starts only once all earlier steps are done, runs alone, and every later step
waits for it. That keeps approvals one at a time and each approval tied to the exact action it is asked about.

This relies on one fact about tools: a result never carries more label or taint than its ToolSpec declares
(llm.work is the exception, which is why it is never run early). The decision layer may add taint to a result
that reads like instructions, so while it is on every unfinished step is assumed to taint (`may_taint`)."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lilly.domain.labels import Risk, TaskCtx, Verdict
from lilly.domain.plan import FINAL_TOOL, references, tool_call
from lilly.domain.policy import PathScope, decide
from lilly.domain.tools_registry import ToolSpec

Step = Mapping[str, Any]


def dependencies(steps: Sequence[Step]) -> dict[str, tuple[str, ...]]:
    """For each step id, the earlier steps whose output its arguments use, in plan order."""
    earlier: list[str] = []
    out: dict[str, tuple[str, ...]] = {}
    for st in steps:
        used = references(st.get("args", {}))
        out[st["id"]] = tuple(sid for sid in earlier if sid in used)
        earlier.append(st["id"])
    return out


def parallel_eligible(step: Step, spec: ToolSpec | None, worst: TaskCtx, scope: PathScope) -> bool:
    """Whether the step may run beside others: a plain, stateless read that policy allows even in the worst case."""
    if spec is None or spec.risk is not Risk.R0 or spec.confirm or spec.serial or step["tool"] == FINAL_TOOL:
        return False
    args = step.get("args", {})
    if any(references(args.get(a)) for a in spec.path_args):
        return False   # which path it reads is not known until an earlier step finishes
    return decide(tool_call(step["tool"], spec, args), worst, scope)[0] is Verdict.ALLOW


@dataclass(slots=True)
class _Progress:
    steps: Sequence[Step]
    deps: dict[str, tuple[str, ...]]
    pending: list[int]
    running: dict[asyncio.Task[str], int] = field(default_factory=dict)
    done: set[str] = field(default_factory=set)
    solo: bool = False   # a barrier step is running, so nothing else may start


class LaneScheduler:
    def __init__(self, specs: Mapping[str, ToolSpec], scope: PathScope, width: int,
                 ctx: Callable[[], TaskCtx], may_taint: Callable[[], bool] = lambda: False) -> None:
        self._specs, self._scope, self._width, self._ctx, self._may_taint = specs, scope, width, ctx, may_taint

    async def run(self, steps: Sequence[Step], run_step: Callable[[Step], Coroutine[Any, Any, str]],
                  abandon: Callable[[Step], Awaitable[None]], outputs: dict[str, str]) -> None:
        """Run every step. Outputs land in `outputs` as steps finish. On the first failure the steps still running
        are cancelled (each is handed to `abandon`), finished outputs are kept, and that failure is raised."""
        p = _Progress(steps, dependencies(steps), list(range(len(steps))))
        try:
            while p.pending or p.running:
                while (pick := self._pick(p)) is not None:
                    i, p.solo = pick
                    p.pending.remove(i)
                    p.running[asyncio.create_task(run_step(steps[i]))] = i
                finished, _ = await asyncio.wait(p.running, return_when=asyncio.FIRST_COMPLETED)
                failure = self._collect(p, finished, outputs)
                if failure is not None:
                    await self._abort(p, abandon, outputs)
                    raise failure
                p.solo = p.solo and bool(p.running)
        except BaseException:
            await _cancel(p.running)
            raise

    def _pick(self, p: _Progress) -> tuple[int, bool] | None:
        """The first step that may start now, and whether it must run alone. None means wait."""
        if p.solo or len(p.running) >= self._width:
            return None
        worst, earlier_unfinished, running = self._ctx(), False, set(p.running.values())
        taints = self._may_taint()
        for i in sorted(running.union(p.pending)):
            step = p.steps[i]
            spec = self._specs.get(step["tool"])
            if i not in running:
                if not parallel_eligible(step, spec, worst, self._scope):
                    return None if earlier_unfinished or p.running else (i, True)
                if all(d in p.done for d in p.deps[step["id"]]):
                    return i, False
            if spec is not None:
                worst = worst.absorb(spec.reads_label, spec.untrusted or taints)
            earlier_unfinished = True
        return None

    @staticmethod
    def _collect(p: _Progress, finished: set[asyncio.Task[str]], outputs: dict[str, str]) -> BaseException | None:
        """Take in the steps that just finished. Returns the failure of the earliest failed one, if any."""
        failure: BaseException | None = None
        for task in sorted(finished, key=lambda t: p.running[t]):
            step = p.steps[p.running.pop(task)]
            exc = task.exception()
            if exc is None:
                outputs[step["id"]] = task.result()
                p.done.add(step["id"])
            elif failure is None:
                failure = exc
        return failure

    @staticmethod
    async def _abort(p: _Progress, abandon: Callable[[Step], Awaitable[None]], outputs: dict[str, str]) -> None:
        """Stop the steps still running after a failure; keep what any of them managed to finish."""
        leftovers = sorted(p.running.items(), key=lambda kv: kv[1])
        p.running.clear()
        await _cancel(dict(leftovers))
        for task, i in leftovers:
            if task.cancelled():
                await abandon(p.steps[i])
            elif task.exception() is None:
                outputs[p.steps[i]["id"]] = task.result()


async def _cancel(running: Mapping[asyncio.Task[str], int]) -> None:
    for task in running:
        task.cancel()
    await asyncio.gather(*running, return_exceptions=True)
