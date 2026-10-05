"""The Agent Loop: dynamic turn-by-turn reasoning and tool execution.

One model call decides the next action from everything seen so far.
Supports parallel read calls, serial execution for mutating steps, observation
generation, decline continuation, loop guard warnings, and budget enforcement.
"""
from __future__ import annotations

import datetime
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from lilly.domain.caps import Cap
from lilly.domain.labels import Verdict
from lilly.domain.payload import canonical, payload_hash
from lilly.domain.plan import tool_call
from lilly.domain.policy import PathScope, decide
from lilly.domain.ports import (
    Completed,
    Completer,
    CompletionRequest,
    Message,
    ModelToolCall,
    ToolSchema,
)
from lilly.domain.reasoning import Layer
from lilly.domain.schema import validate_schema
from lilly.domain.settings import EngineSettings, LimitSettings
from lilly.domain.tasks import TaskState
from lilly.engine.decisions import DecisionPipeline
from lilly.engine.lanes import LaneScheduler, parallel_eligible
from lilly.engine.messages import (
    AGENT_SYSTEM,
    FALLBACK_FINAL,
    NOTICE_BUDGET_EXHAUSTED,
    NOTICE_BUDGET_WARN,
    NOTICE_LOOPING,
    OBS_BLOCKED,
    OBS_DECLINED,
    OBS_DECLINED_REASON,
    OBS_ERROR,
    OBS_INVALID_ARGS,
    OBS_OK,
    OBS_UNAVAILABLE,
)
from lilly.engine.outcome import StepDeclined, StepFailed, Stop, clip
from lilly.engine.record import TaskRecord
from lilly.engine.steps import StepExecutor
from lilly.store import conversations, tasks
from lilly.store.db import Database
from lilly.tools.base import Tool

log = logging.getLogger("lilly.agent_loop")


class AgentLoop:
    """Orchestrates an agentic loop for a single task."""

    def __init__(
        self,
        rec: TaskRecord,
        completer: Completer,
        steps: StepExecutor,
        tools: Callable[[], Mapping[str, Tool]],
        scope: Callable[[], PathScope],
        file_roots: Callable[[], tuple[str, ...]],
        limits: Callable[[], LimitSettings],
        engine_settings: Callable[[], EngineSettings],
        db: Database,
        goal: str,
        conversation_id: str,
        agent_instructions: str = "",
        pin_model: str | None = None,
        pet_name: str = "Lilly",
        decisions: DecisionPipeline | None = None,
        stop_reason: Callable[[], str] | str = "stopped",
        role_models: Mapping[str, str] | None = None,
        tool_allowlist: frozenset[str] | None = None,
    ) -> None:
        self._rec = rec
        self._completer = completer
        self._steps = steps
        self._tools = tools
        self._scope = scope
        self._file_roots = file_roots
        self._limits = limits
        self._engine_settings = engine_settings
        self._db = db
        self._goal = goal
        self._conversation_id = conversation_id
        self._agent_instructions = agent_instructions
        self._pin_model = pin_model
        self._pet_name = pet_name
        self._decisions = decisions
        self._stop_reason = stop_reason
        self._role_models = dict(role_models or {})
        self._tool_allowlist = tool_allowlist
        self._outputs: dict[str, str] = {}
        self._steps.loop_mode = True

    @property
    def current_stop_reason(self) -> str:
        if callable(self._stop_reason):
            return self._stop_reason()
        return str(self._stop_reason)

    def _get_visible_tools(self) -> dict[str, Tool]:
        all_tools = dict(self._tools())
        if self._tool_allowlist is None:
            return all_tools
        visible: dict[str, Tool] = {}
        for name, tool in all_tools.items():
            # Control tools are always visible if available in tools dict
            if name in ("agent.ask", "agent.plan", "result.read"):
                visible[name] = tool
            elif name in self._tool_allowlist:
                visible[name] = tool
        return visible

    def _build_system_prompt(self, limits: LimitSettings) -> str:
        roots = self._file_roots()
        folders_desc = ", ".join(sorted(roots)) if roots else "none"
        today_str = datetime.date.today().isoformat()

        base_prompt = AGENT_SYSTEM.format(
            agent_name=self._pet_name,
            max_steps=limits.max_agent_steps,
            max_calls=limits.max_model_calls,
            date=today_str,
            folders_or_none=folders_desc,
        )
        parts = [base_prompt]
        if self._agent_instructions:
            parts.append(
                f"Instructions from the owner of this agent (they cannot override the rules above):\n"
                f"{self._agent_instructions}"
            )
        return "\n\n".join(parts)

    def _load_history(self) -> list[Message]:
        hist: list[Message] = []
        rows = conversations.recent_messages(self._db.reader, self._conversation_id, 12)
        for m in rows:
            if m.task_id != self._rec.task_id:
                self._rec.absorb(m.label, m.untrusted)
                hist.append(Message(role=m.role, content=m.content))
        return hist

    async def _execute_step(
        self,
        step_id: str,
        name: str,
        args: Mapping[str, Any],
        tc: ModelToolCall,
        tools_dict: Mapping[str, Tool],
    ) -> Message:
        tool = tools_dict.get(name)
        if tool is None:
            return Message("tool", OBS_ERROR.format(step_id=step_id, tool=name, reason="tool unavailable"),
                           tool_call_id=tc.id or tc.name)

        spec = tool.spec
        args_dict = dict(args)
        # Check policy before running
        verdict, why = decide(tool_call(name, spec, args_dict), self._rec.ctx, self._scope())
        if verdict is not Verdict.DENY and (own := tool.review(args_dict, self._rec.task_id))[0] > verdict:
            verdict, why = own
        if verdict is Verdict.DENY:
            await self._rec.step_status(step_id, "failed", error=f"blocked: {why}")
            await self._rec.thought(Layer.ACT, f"{name} was blocked by policy: {why}.", step=step_id)
            return Message("tool", OBS_BLOCKED.format(step_id=step_id, tool=name, why=why),
                           tool_call_id=tc.id or tc.name)

        try:
            output = await self._steps.run(
                {"tool": name, "args": args},
                step_id,
                self._outputs,
                tools_dict,
                decline_continues=True,
            )
            self._outputs[step_id] = output

            # Format successful observation
            untrusted = spec.untrusted or self._rec.ctx.tainted
            body = output
            if untrusted:
                body = f"<untrusted_data>\n{body}\n</untrusted_data>"
            obs_chars = self._engine_settings().observation_chars
            shown_suffix = ""
            truncated_suffix = ""
            if len(output) > obs_chars:
                shown = obs_chars
                shown_suffix = f", showing the first {shown}"
                body = body[:shown]
                truncated_suffix = f'\n[truncated: call result.read with {{"step": "{step_id}", "offset": {shown}}} for more]'

            obs = OBS_OK.format(
                step_id=step_id,
                tool=name,
                chars=len(output),
                shown_suffix=shown_suffix,
                body=body,
                truncated_suffix=truncated_suffix,
            )
            return Message("tool", obs, tool_call_id=tc.id or tc.name)
        except StepDeclined as dec:
            if dec.user_reason:
                obs = OBS_DECLINED_REASON.format(step_id=step_id, tool=name, reason=dec.user_reason)
            else:
                obs = OBS_DECLINED.format(step_id=step_id, tool=name)
            return Message("tool", obs, tool_call_id=tc.id or tc.name)
        except StepFailed as failed:
            if failed.kind == "policy":
                obs = OBS_BLOCKED.format(step_id=step_id, tool=name, why=failed.reason)
            else:
                obs = OBS_ERROR.format(step_id=step_id, tool=name, reason=failed.reason)
            return Message("tool", obs, tool_call_id=tc.id or tc.name)

    async def run(self) -> str:
        """Run the dynamic agent loop to completion, returning the candidate answer."""
        limits = self._limits()
        system_text = self._build_system_prompt(limits)
        messages: list[Message] = [Message(role="system", content=system_text)]
        messages.extend(self._load_history())
        messages.append(Message(role="user", content=self._goal))

        turn = 0
        model_calls = 0
        tokens_used = 0
        consecutive_invalid_turns = 0
        escalated = False
        escalation_triggered = False
        seen_looping_notice = False

        candidate_answer: str | None = None

        while True:
            if self._rec.cancelled:
                raise Stop(TaskState.CANCELLED, self.current_stop_reason)

            # 1. Determine role and model for this turn
            if turn == 0:
                role = "plan"
            elif escalation_triggered:
                role = "plan"
                escalation_triggered = False
            else:
                role = "act"

            # 2. Visible tools
            visible_tools = self._get_visible_tools()
            tool_schemas = [
                ToolSchema(name=name, description=t.spec.doc, parameters=dict(t.spec.schema))
                for name, t in sorted(visible_tools.items(), key=lambda item: item[0])
            ]

            # 3. Check budgets
            max_steps = limits.max_agent_steps
            max_calls = limits.max_model_calls
            max_tokens = limits.max_task_tokens

            remaining_calls = max_calls - model_calls
            remaining_steps = max_steps - turn
            remaining_tokens = max_tokens - tokens_used

            is_final_call = (remaining_calls <= 1 or remaining_steps <= 0 or remaining_tokens <= 0)
            tool_choice = "none" if is_final_call else "auto"

            if is_final_call:
                role = "write"
                budget_reason = "steps" if remaining_steps <= 0 else ("tokens" if remaining_tokens <= 0 else "model calls")
                messages.append(Message(role="user", content=NOTICE_BUDGET_EXHAUSTED))
            elif remaining_steps == 1 or remaining_calls == 2:
                messages.append(Message(role="user", content=NOTICE_BUDGET_WARN.format(
                    steps_left=remaining_steps, calls_left=remaining_calls
                )))

            # 4. Resolve pinned model or role tag
            role_pin = self._role_models.get(role) or self._pin_model
            tag = None
            if role_pin and role_pin.startswith("tag:"):
                tag = role_pin.split(":", 1)[1]
                role_pin = None

            req = CompletionRequest(
                messages=tuple(messages),
                max_tokens=min(4096, max(remaining_tokens, 512) if remaining_tokens > 0 else 4096),
                tools=tuple(tool_schemas) if tool_choice != "none" else (),
                tool_choice=tool_choice,
                role=role,
                tag=tag,
                priority=0,
            )

            # 5. Model call via with_model_permission
            stage_name = "act" if self._rec.state_now is TaskState.RUNNING else "plan"

            cur_turn, cur_calls, cur_req, cur_pin = turn, model_calls, req, role_pin

            async def invoke_model(
                t: int = cur_turn,
                c: int = cur_calls,
                r: CompletionRequest = cur_req,
                p: str | None = cur_pin,
            ) -> Completed:
                digest = payload_hash(self._rec.task_id, f"turn_{t}_{c}", "loop", {"goal": self._goal})
                done = await self._completer.complete(
                    r,
                    need=Cap.NONE,
                    label=self._rec.ctx.label,
                    task_id=self._rec.task_id,
                    payload_hash=digest,
                    mode=self._rec.ctx.mode,
                    pin=p,
                )
                self._rec.models.append(done.model)
                return done

            done = await self._steps.with_model_permission(invoke_model, stage_name, self._rec.state_now)
            model_calls += 1
            tokens_used += done.result.input_tokens + done.result.output_tokens

            if self._rec.cancelled:
                raise Stop(TaskState.CANCELLED, self.current_stop_reason)

            # 6. Process reply
            # Case A: Tool choice was "none" (forced write turn)
            if tool_choice == "none":
                text = done.result.text.strip()
                if text:
                    candidate_answer = text
                else:
                    n_done = len(self._outputs)
                    one_line = f"{n_done} step(s) finished"
                    candidate_answer = FALLBACK_FINAL.format(reason=budget_reason, receipt_one_line=one_line)
                break

            # Case B: Model returned direct answer without tool calls
            if not done.result.tool_calls:
                candidate_answer = done.result.text.strip()
                break

            if done.result.text.strip():
                await self._rec.thought(
                    Layer.PLAN if self._rec.state_now is TaskState.PLANNING else Layer.ACT,
                    done.result.text.strip(),
                    "model",
                )

            # Transition from PLANNING to RUNNING on the first tool call
            if self._rec.state_now is TaskState.PLANNING:
                await self._rec.state(TaskState.RUNNING)

            messages.append(Message(role="assistant", content=done.result.text, tool_calls=done.result.tool_calls))
            turn += 1

            all_invalid = True
            valid_calls: list[tuple[str, str, dict[str, Any], ModelToolCall]] = []
            obs_by_sid: dict[str, Message] = {}

            for i, tc in enumerate(done.result.tool_calls, start=1):
                step_id = f"t{turn}c{i}"
                if tc.name not in visible_tools:
                    avail = ", ".join(sorted(visible_tools.keys()))
                    obs_text = OBS_UNAVAILABLE.format(step_id=step_id, tool=tc.name, names=avail)
                    obs_by_sid[step_id] = Message(role="tool", content=obs_text, tool_call_id=tc.id or tc.name)
                    continue

                tool = visible_tools[tc.name]
                spec = tool.spec
                args = dict(tc.arguments or {}) if isinstance(tc.arguments, Mapping) else {}
                errs = validate_schema(spec.schema, args)
                if errs:
                    err_msg = errs[0]
                    parts = err_msg.split(": ", 1)
                    schema_path = parts[0]
                    prob = parts[1] if len(parts) > 1 else err_msg
                    obs_text = OBS_INVALID_ARGS.format(step_id=step_id, tool=tc.name, schema_path=schema_path, problem=prob)
                    obs_by_sid[step_id] = Message(role="tool", content=obs_text, tool_call_id=tc.id or tc.name)
                    continue

                all_invalid = False
                valid_calls.append((step_id, tc.name, args, tc))

            # Escalation: 2 consecutive invalid turns trigger escalation to "plan" model once
            if all_invalid:
                consecutive_invalid_turns += 1
                if consecutive_invalid_turns >= 2 and not escalated:
                    escalated = True
                    escalation_triggered = True
            else:
                consecutive_invalid_turns = 0

            # Execute valid calls
            if valid_calls:
                # Record step rows in DB
                step_rows = [(sid, name, canonical(clip(args))) for sid, name, args, _ in valid_calls]
                task_id = self._rec.task_id
                cur_task_id = task_id
                cur_step_rows = step_rows

                def save_steps(
                    con: Any,
                    tid: str = cur_task_id,
                    srows: list[tuple[str, str, str]] = cur_step_rows,
                ) -> None:
                    tasks.create_steps(con, tid, srows)

                await self._db.write(save_steps)

                # Partition valid calls into batches of parallel-eligible vs serial calls
                batches: list[list[tuple[str, str, dict[str, Any], ModelToolCall]]] = []
                current_parallel_batch: list[tuple[str, str, dict[str, Any], ModelToolCall]] = []

                for item in valid_calls:
                    sid, name, args, tc = item
                    eligible = parallel_eligible(
                        {"tool": name, "args": args},
                        visible_tools[name].spec,
                        self._rec.ctx,
                        self._scope(),
                    )
                    if eligible:
                        current_parallel_batch.append(item)
                    else:
                        if current_parallel_batch:
                            batches.append(current_parallel_batch)
                            current_parallel_batch = []
                        batches.append([item])
                if current_parallel_batch:
                    batches.append(current_parallel_batch)

                for batch in batches:
                    if len(batch) > 1:
                        specs = {n: t.spec for n, t in visible_tools.items()}
                        lanes = LaneScheduler(
                            specs,
                            self._scope(),
                            limits.lanes,
                            lambda: self._rec.ctx,
                            self._steps.may_taint,
                        )
                        steps_list = [{"id": sid, "tool": name, "args": args} for sid, name, args, _ in batch]
                        cur_batch = batch
                        cur_tools = visible_tools
                        cur_obs = obs_by_sid

                        async def run_one(
                            st: Mapping[str, Any],
                            b: list[tuple[str, str, dict[str, Any], ModelToolCall]] = cur_batch,
                            vt: dict[str, Tool] = cur_tools,
                            om: dict[str, Message] = cur_obs,
                        ) -> str:
                            sid_st, name_st, args_st = str(st["id"]), str(st["tool"]), st.get("args") or {}
                            args_map = dict(args_st) if isinstance(args_st, Mapping) else {}
                            tc_obj = next(tco for s, _, _, tco in b if s == sid_st)
                            msg = await self._execute_step(sid_st, name_st, args_map, tc_obj, vt)
                            om[sid_st] = msg
                            return self._outputs.get(sid_st, "")

                        await lanes.run(
                            steps_list,
                            run_one,
                            lambda st: self._steps.abandon(st["id"]),
                            self._outputs,
                        )
                    else:
                        sid, name, args, tc_obj = batch[0]
                        msg = await self._execute_step(sid, name, args, tc_obj, visible_tools)
                        obs_by_sid[sid] = msg

                # Loop guard advisory: inject notice on first LOOPING
                if self._steps.seen_looping == 1 and not seen_looping_notice:
                    seen_looping_notice = True
                    messages.append(Message(role="user", content=NOTICE_LOOPING))

            # Append all observations from this turn to messages in original call order
            all_sids = [f"t{turn}c{i}" for i in range(1, len(done.result.tool_calls) + 1)]
            messages.extend([obs_by_sid[sid] for sid in all_sids if sid in obs_by_sid])

        if not candidate_answer:
            raise Stop(TaskState.FAILED, "there was no answer to give")

        return candidate_answer
