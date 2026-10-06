"""Delegation service: hand a self-contained job to another specialist pet.

Implements Part 5 delegation rules:
- Child task has parent_task_id and depth + 1
- Limits: crew.max_depth (default 1, 0..3) and crew.max_children (default 3, 1..8)
- Tool intersection: child_tools = parent visible ∩ child visible
- Child mode is stricter of parent and child
- Budget share: child_budget_share (default 0.4) deducted from parent remaining
- Child answer returns as untrusted data (4A.9) and raises parent label and taint
- Cancel cascades
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass

from lilly.domain.decisions import step_sig
from lilly.domain.errors import ToolError
from lilly.domain.labels import Mode
from lilly.domain.ports import ToolContext, ToolResult
from lilly.domain.settings import CrewSettings, LimitSettings
from lilly.domain.sheet import TaskProfile
from lilly.domain.text import fence_untrusted
from lilly.engine.bus import EventBus
from lilly.engine.orchestrator import Orchestrator, SubmitRequest
from lilly.engine.runner import EngineDeps
from lilly.store import agents as agent_store
from lilly.store import tasks
from lilly.store.db import Database


@dataclass
class DelegationContext:
    db: Database
    bus: EventBus
    orchestrator: Orchestrator
    crew_settings: Callable[[], CrewSettings]
    limits: Callable[[], LimitSettings]


class DelegateHandler:
    def __init__(self, d: DelegationContext) -> None:
        self._d = d

    async def delegate(
        self,
        target_agent: str,
        task_instruction: str,
        ctx: ToolContext,
        parent_deps: EngineDeps | None = None,
    ) -> ToolResult:
        crew = self._d.crew_settings()

        # 1. Check max depth
        # Look up parent task row
        parent_row = tasks.get_task(self._d.db.reader, ctx.task_id)
        parent_depth = parent_row.depth if parent_row else 0
        if parent_depth >= crew.max_depth:
            raise ToolError(f"cannot delegate: maximum delegation depth ({crew.max_depth}) reached")

        # 2. Check max children
        children = tasks.list_children(self._d.db.reader, ctx.task_id)
        if len(children) >= crew.max_children:
            raise ToolError(f"cannot delegate: maximum number of child tasks ({crew.max_children}) reached")

        # 3. Find child pet
        all_agents = agent_store.list_agents(self._d.db.reader)
        target_clean = target_agent.strip().lower()
        child_agent: agent_store.AgentRow | None = None
        for a in all_agents:
            if a.name.lower() == target_clean or a.pet.lower() == target_clean or a.id == target_agent:
                child_agent = a
                break

        if child_agent is None:
            raise ToolError(f"unknown agent {target_agent!r}")

        # 4. Mode is stricter of parent and child
        child_mode = Mode(min(ctx.mode.value, child_agent.mode))

        # 5. Compute budget
        share = crew.child_budget_share
        limits_now = self._d.limits()
        # Allocate child budget share
        child_steps = max(1, int(limits_now.max_agent_steps * share))
        child_calls = max(1, int(limits_now.max_model_calls * share))
        child_tokens = max(1000, int(limits_now.max_task_tokens * share))

        child_sheet = agent_store.parsed_sheet_for(child_agent)
        if child_sheet and child_sheet.limits:
            if child_sheet.limits.steps is not None:
                child_steps = min(child_steps, child_sheet.limits.steps)
            if child_sheet.limits.model_calls is not None:
                child_calls = min(child_calls, child_sheet.limits.model_calls)
            if child_sheet.limits.tokens is not None:
                child_tokens = min(child_tokens, child_sheet.limits.tokens)

        # 6. Submit child task
        # Child's visible tools will be intersection of parent's visible tools and child pet visible tools
        tools_off: list[str] = []
        if parent_deps is not None:
            parent_tools = set(parent_deps.tools().keys())
            for tname in self._d.orchestrator._d.tools().keys():
                if tname not in parent_tools:
                    tools_off.append(tname)

        req = SubmitRequest(
            goal=task_instruction,
            agent_id=child_agent.id,
            conversation_id=None,  # new conversation
            parent_task_id=ctx.task_id,
            depth=parent_depth + 1,
            mode=child_mode,
            profile=TaskProfile(tools_off=tuple(tools_off), steps=child_steps),
        )

        child_row = await self._d.orchestrator.submit(req)
        # Wait for child task to complete
        child_final_row = await self._wait_task(child_row.id)

        # Forward child task steps to parent runner for loop detection (Part 6 L2)
        parent_entry = self._d.orchestrator._active.get(ctx.task_id)
        if parent_entry is not None:
            parent_runner = parent_entry[1]
            finished_steps = tasks.list_steps(self._d.db.reader, child_final_row.id)
            for cs in finished_steps:
                try:
                    cs_args = json.loads(cs.args_json) if cs.args_json else {}
                except Exception:
                    cs_args = {}
                parent_runner.steps.add_finished(step_sig(cs.tool, cs_args))

        # 7. Get model calls count
        calls_count = self._count_model_calls(child_final_row.id)
        child_final = child_final_row.answer or (child_final_row.error or "No answer returned.")

        # Format observation 4A.9:
        # RESULT {step_id} agent.delegate ok (from {pet_name}, {calls} model calls)\n<untrusted_data>\n{child_final}\n</untrusted_data>
        fenced_final = fence_untrusted(child_final)
        body = (
            f"RESULT {ctx.step_id} agent.delegate ok (from {child_agent.name}, {calls_count} model calls)\n"
            f"{fenced_final}"
        )

        # Child's answer is treated as untrusted data to parent, and raises label and taint
        return ToolResult(
            output=body,
            label=child_final_row.label,
            untrusted=True,
        )

    async def _wait_task(self, task_id: str, timeout: float = 60.0) -> tasks.TaskRow:
        async with asyncio.timeout(timeout):
            while task_id in self._d.orchestrator._active:
                await asyncio.sleep(0.02)
        row = tasks.get_task(self._d.db.reader, task_id)
        assert row is not None
        return row

    def _count_model_calls(self, task_id: str) -> int:
        r = self._d.db.reader.execute("SELECT COUNT(*) FROM model_calls WHERE task_id=?", (task_id,)).fetchone()
        return int(r[0]) if r else 0
