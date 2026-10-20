"""The Agent Loop: dynamic turn-by-turn reasoning and tool execution.

One model call decides the next action from everything seen so far.
Supports parallel read calls, serial execution for mutating steps, observation
generation, decline continuation, loop guard warnings, and budget enforcement.
"""
from __future__ import annotations

import datetime
import logging
from collections.abc import Callable, Mapping
from typing import Any

from lilly.core.shortlist import CONTROL_TOOLS, discover
from lilly.decide.system1 import System1Engine
from lilly.domain.caps import Cap
from lilly.domain.labels import ApprovalMode, Risk, Verdict
from lilly.domain.payload import canonical, payload_hash
from lilly.domain.plan import FINAL_TOOL, tool_call
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
from lilly.domain.settings import EngineSettings, GroundingSettings, LimitSettings
from lilly.domain.sheet import PetSheet, TaskProfile
from lilly.domain.tasks import ExecutionTarget, LoopAnswer, TaskOutcome, TaskState
from lilly.domain.text import fence
from lilly.engine.context import ContextManager
from lilly.engine.crew import resolve_ref
from lilly.engine.decisions import DecisionPipeline
from lilly.engine.grounding import GroundingVerifier
from lilly.engine.intent import Intent, classify_intent
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
from lilly.engine.outcome import StepDeclined, StepFailed, StepOutcome, Stop, clip
from lilly.engine.record import TaskRecord
from lilly.engine.steps import StepExecutor
from lilly.store import conversations, tasks
from lilly.store.db import Database
from lilly.tools.base import Tool

log = logging.getLogger("lilly.agent_loop")

# An ACTION request is complete only after a state-changing interaction and a
# fresh browser/desktop observation. Read-only web research is intentionally
# outside this contract.
_ACTION_TOOLS = frozenset({
    "browser.click", "browser.type", "browser.select", "browser.submit", "browser.press",
    "browser.scroll", "browser.back", "browser.close",
    "computer.click", "computer.type", "computer.press", "computer.move",
    "computer.scroll", "computer.drag", "computer.open_app", "computer.open_url",
    "computer.stop_process", "computer.run", "computer.notify", "devbox.run",
    "fs.write", "fs.edit", "fs.apply_moves", "fs.trash",
    "notes.write", "memory.write",
})
_ACTION_OBSERVATION_TOOLS = frozenset({
    "browser.open", "browser.read", "browser.find", "browser.back",
    "computer.observe", "computer.processes",
    "fs.read", "fs.list", "fs.search", "notes.read", "notes.search", "memory.search",
})
_ACTION_TOOLS_WITH_FRESH_STATE = frozenset({
    "browser.click", "browser.type", "browser.select", "browser.submit", "browser.press",
    "browser.scroll", "browser.back",
    "computer.click", "computer.type", "computer.press", "computer.move",
    "computer.scroll", "computer.drag",
})


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
        grounding_settings: Callable[[], GroundingSettings] | GroundingSettings | None = None,
        sheet: PetSheet | None = None,
        profile: TaskProfile | None = None,
        system1_engine: System1Engine | None = None,
        requested_intent: Intent | None = None,
        target: ExecutionTarget = ExecutionTarget.HOST,
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
        self._sheet = sheet
        self._profile = profile
        self._system1 = system1_engine
        self._target = target
        self._task_complexity = 0.5
        self._system1_requires_vision = False
        self._system1_capability = Cap.NONE
        self._system1_model_tier: str | None = None
        self._system1_tool_family: str | None = None
        self._system1_verification: str | None = None
        self._outputs: dict[str, str] = {}
        self._steps.loop_mode = True
        self._used_tools: set[str] = set()
        self._discovered_tools: set[str] = set()
        self._schema_cache: dict[str, ToolSchema] = {}
        self._failed_calls: dict[tuple[str, str], str] = {}
        gs = grounding_settings() if callable(grounding_settings) else (grounding_settings or GroundingSettings())
        self._grounding = GroundingVerifier(file_roots=self._file_roots(), enabled=gs.enabled)
        self._context_mgr = ContextManager(self._engine_settings, self._completer)
        self._intent = requested_intent or classify_intent(goal)

    @property
    def target(self) -> ExecutionTarget:
        return self._target

    @property
    def current_stop_reason(self) -> str:
        if callable(self._stop_reason):
            return self._stop_reason()
        return str(self._stop_reason)

    async def _prepare_system1(self) -> None:
        """Make one cheap typed assessment before the first generative turn."""
        if self._system1 is None:
            return
        models = tuple(getattr(self._completer, "get_available_models", lambda: ())())
        tools = tuple(self._tools().keys())
        routed_goal = f"Requested intent: {self._intent.value}\nUser request: {self._goal}"
        classification, complexity = await self._system1.assess_task(routed_goal, self._rec.task_id)
        tier, capability, tool_family = await self._system1.determine_routing(
            routed_goal, models, tools, self._rec.task_id
        )
        self._task_complexity = {
            "TRIVIAL": 0.1, "SIMPLE": 0.3, "MODERATE": 0.6,
            "COMPLEX": 0.8, "EXPERT": 0.95,
        }.get(complexity.level.name, 0.5)
        self._system1_capability = capability.primary_capability
        self._system1_requires_vision = capability.needs_vision
        self._system1_model_tier = tier.tier.name
        self._system1_tool_family = tool_family.primary_family.name
        verification = await self._system1.assess_verification(
            self._rec.task_id, routed_goal, self._task_complexity, classification.task_class
        )
        self._system1_verification = verification.level.name
        await self._rec.event("system1", {
            "intent": self._intent.value,
            "classification": classification.task_class.name,
            "complexity": complexity.level.name,
            "model_tier": tier.tier.name,
            "capability": capability.primary_capability.name,
            "tool_family": tool_family.primary_family.name,
            "verification": verification.level.name,
            "reasoning": complexity.reasoning[:300],
        })

    def _get_visible_tools(self) -> dict[str, Tool]:
        if self._rec.ctx.approval_mode is ApprovalMode.OFF:
            # OFF mode stops all agentic tasks: direct conversational responses only
            return {}
        all_tools = dict(self._tools())
        if self._target is ExecutionTarget.DEVBOX:
            allowed_prefixes = ("devbox.", "result.", "agent.", "skill.")
            all_tools = {k: v for k, v in all_tools.items() if any(k.startswith(p) for p in allowed_prefixes)}
        elif self._target is ExecutionTarget.HOST:
            all_tools = {k: v for k, v in all_tools.items() if not k.startswith("devbox.")}

        visible: dict[str, Tool] = {}
        ALWAYS_VISIBLE = frozenset({"agent.ask"})   # the one tool a pet needs even with everything else off

        for name, tool in all_tools.items():
            if name not in ALWAYS_VISIBLE:
                if self._tool_allowlist is not None and name not in self._tool_allowlist:
                    continue
                if self._sheet is not None and not self._sheet.allows(name):
                    continue
                if self._profile is not None and name in self._profile.tools_off:
                    continue
            visible[name] = tool
        return visible

    def _evaluate_outcome(
        self,
        text: str,
        *,
        intent: Intent,
        action_performed: bool,
        action_verified: bool,
        had_blocked: bool,
        had_declined: bool,
        had_failed_step: bool,
    ) -> tuple[TaskOutcome, str | None, bool]:
        """Determine truthful goal outcome and verification state."""
        lower = text.lower()
        blocked_indicators = (
            "not optimized for", "isn't optimized for", "not supported",
            "blocked by policy", "unable to play", "cannot play",
            "access denied", "permission denied",
        )
        is_blocked_text = any(phrase in lower for phrase in blocked_indicators)

        question_indicators = (
            "would you like me to", "do you want me to", "should i",
            "how would you like to proceed", "what would you like to do",
            "let me know how to proceed", "please let me know",
            "would you prefer", "or try another",
        )
        asks_user = any(phrase in lower for phrase in question_indicators) or (
            "?" in text and ("switch" in lower or "proceed" in lower or "instead" in lower or "choose" in lower)
        )

        if had_blocked or is_blocked_text:
            return TaskOutcome.BLOCKED, "action was blocked by platform or policy", False
        if had_declined:
            return TaskOutcome.NEEDS_USER, "action approval was declined", False

        if intent is Intent.ACTION:
            if asks_user:
                return TaskOutcome.NEEDS_USER, "further user input or choice needed", False
            if action_verified:
                return TaskOutcome.SUCCESS, "action performed and verified", True
            if action_performed:
                return TaskOutcome.UNVERIFIED, "action performed but visible state was not verified", False
            if asks_user:
                return TaskOutcome.NEEDS_USER, "action not completed; user choice needed", False
            return TaskOutcome.PARTIAL, "requested action was not executed to completion", False

        if intent is Intent.NAVIGATE:
            if action_performed or action_verified:
                return TaskOutcome.SUCCESS, "navigated to destination", True
            return TaskOutcome.PARTIAL, "destination not reached", False

        # Intent is WEB_RETRIEVE or ANSWER
        if had_failed_step:
            return TaskOutcome.PARTIAL, "completed with errors during retrieval", False
        if asks_user and not action_performed:
            return TaskOutcome.NEEDS_USER, "clarification requested from user", False
        return TaskOutcome.SUCCESS, None, False

    async def _capabilities(self, visible: dict[str, Tool]) -> dict[str, Tool]:
        """Expose core tools + discovered/used tools, loading schemas on demand to save tokens."""
        if not visible:
            return {}
        if len(visible) <= 12:
            return visible

        # Core tools
        allowed = set(CONTROL_TOOLS)
        allowed.add(FINAL_TOOL)
        allowed.add("agent.ask")

        # Plus previously used or discovered tools
        allowed.update(self._used_tools)
        allowed.update(self._discovered_tools)

        # On the initial turn (no tools used or discovered yet), seed relevant tools from the task goal/intent
        if not self._used_tools and not self._discovered_tools:
            specs = {name: tool.spec for name, tool in visible.items()}
            ns = self._system1_tool_family.lower() if self._system1_tool_family and self._system1_tool_family != "ALL" else None
            initial_matches = discover(specs, self._goal, namespace=ns, limit=8)
            allowed.update(initial_matches)

        # Filter to visible tools that are in allowed
        active = {name: tool for name, tool in visible.items() if name in allowed}
        # Ensure agent.discover and agent.ask are always available if present in visible
        if "agent.discover" in visible:
            active["agent.discover"] = visible["agent.discover"]
        if "agent.ask" in visible:
            active["agent.ask"] = visible["agent.ask"]

        return active

    def _build_system_prompt(self, limits: LimitSettings, role: str = "act") -> str:
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
        owner_text = ""
        if self._sheet is not None:
            owner_text = self._sheet.render_owner_text(role=role)
        elif self._agent_instructions:
            owner_text = self._agent_instructions

        if owner_text:
            parts.append(
                f"Instructions from the owner of this agent (they cannot override the rules above):\n"
                f"{owner_text}"
            )

        if self._sheet is not None and self._sheet.skills:
            skill_lines = ["Named skills you can load with skill.load:"]
            for sname, scontent in sorted(self._sheet.skills.items()):
                first_line = scontent.strip().splitlines()[0] if scontent.strip() else ""
                skill_lines.append(f"- {sname}: {first_line}")
            parts.append("\n".join(skill_lines))

        # Parallelism guidance to optimize success per token/call
        parts.append(
            "Efficiency rule: You can call multiple independent read-only tools in a single turn to run them in parallel (e.g. reading multiple files, running searches). Mutating tools execute in order. "
            "If the capability you need is not listed, call agent.discover with descriptive words and use the discovered tool on the next turn."
        )
        intent = self._intent
        parts.append(
            f"Request intent: {intent.value}. For WEB RETRIEVE, gather and return information without opening a browser unless interaction is required. "
            "For NAVIGATE, opening the destination is the outcome. For ACTION, continue through every interaction and verify the user-visible result; "
            "a search-results page or opened app is not completion. For ANSWER, answer directly when tools are unnecessary."
        )

        # P2-F: Caveman line removed, style text will be added later

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
    ) -> tuple[Message, StepOutcome]:
        tool = tools_dict.get(name)
        if tool is None:
            outcome = StepOutcome(step_id=step_id, tool=name, kind="unavailable", reason="tool unavailable")
            msg = Message("tool", OBS_ERROR.format(step_id=step_id, tool=name, reason="tool unavailable"),
                          tool_call_id=tc.id or tc.name)
            return msg, outcome

        args_dict = dict(args)
        args_key = canonical(clip(args_dict))
        call_key = (name, args_key)

        # Prevent repeated identical failed calls without executing
        if call_key in self._failed_calls:
            prev_reason = self._failed_calls[call_key]
            reason = f"repeated identical call already failed: {prev_reason}"
            outcome = StepOutcome(step_id=step_id, tool=name, kind="failed", reason=reason)
            msg = Message("tool", OBS_ERROR.format(step_id=step_id, tool=name, reason=reason),
                          tool_call_id=tc.id or tc.name)
            await self._rec.step_status(step_id, "failed", error=reason)
            return msg, outcome

        spec = tool.spec
        # Check policy before running
        verdict, why = decide(tool_call(name, spec, args_dict), self._rec.ctx, self._scope())
        if verdict is not Verdict.DENY and (own := tool.review(args_dict, self._rec.task_id))[0] > verdict:
            verdict, why = own
        if verdict is Verdict.DENY:
            self._failed_calls[call_key] = why
            await self._rec.step_status(step_id, "failed", error=f"blocked: {why}")
            await self._rec.thought(Layer.ACT, f"{name} was blocked by policy: {why}.", step=step_id)
            outcome = StepOutcome(step_id=step_id, tool=name, kind="blocked", reason=why)
            msg = Message("tool", OBS_BLOCKED.format(step_id=step_id, tool=name, why=why),
                          tool_call_id=tc.id or tc.name)
            return msg, outcome

        try:
            output = await self._steps.run(
                {"tool": name, "args": args},
                step_id,
                self._outputs,
                tools_dict,
                decline_continues=True,
            )
            self._outputs[step_id] = output
            self._grounding.record_step(name, args, output)

            # Mutation occurred: clear failed calls cache to allow retries in modified environment
            if spec.risk > Risk.R0 or name in _ACTION_TOOLS:
                self._failed_calls.clear()

            # Format successful observation
            untrusted = spec.untrusted or self._rec.ctx.tainted
            obs_chars = self._engine_settings().observation_chars
            if untrusted:
                body, cut = fence(output, obs_chars)
            else:
                cut = len(output) > obs_chars
                body = output[:obs_chars] if cut else output
            shown_suffix = f", showing the first {obs_chars}" if cut else ""
            truncated_suffix = (f'\n[truncated: call result.read with {{"step": "{step_id}", "offset": {obs_chars}}} for more]'
                                if cut else "")

            obs = OBS_OK.format(
                step_id=step_id,
                tool=name,
                chars=len(output),
                shown_suffix=shown_suffix,
                body=body,
                truncated_suffix=truncated_suffix,
            )
            # Use the tool's terminal flag and summary method
            outcome = StepOutcome(
                step_id=step_id, 
                tool=name, 
                kind="ok", 
                output=output,
                terminal=spec.terminal,
                summary=tool.summary(args, output)
            )
            return Message("tool", obs, tool_call_id=tc.id or tc.name), outcome
        except StepDeclined as dec:
            self._failed_calls[call_key] = dec.user_reason or "declined by the user"
            if dec.user_reason:
                obs = OBS_DECLINED_REASON.format(step_id=step_id, tool=name, reason=dec.user_reason)
            else:
                obs = OBS_DECLINED.format(step_id=step_id, tool=name)
            outcome = StepOutcome(step_id=step_id, tool=name, kind="declined", reason=dec.user_reason or "declined by the user")
            return Message("tool", obs, tool_call_id=tc.id or tc.name), outcome
        except StepFailed as failed:
            self._failed_calls[call_key] = failed.reason
            if failed.kind == "policy":
                obs = OBS_BLOCKED.format(step_id=step_id, tool=name, why=failed.reason)
                outcome = StepOutcome(step_id=step_id, tool=name, kind="blocked", reason=failed.reason)
            else:
                obs = OBS_ERROR.format(step_id=step_id, tool=name, reason=failed.reason)
                outcome = StepOutcome(step_id=step_id, tool=name, kind="failed", reason=failed.reason)
            return Message("tool", obs, tool_call_id=tc.id or tc.name), outcome

    async def run(self) -> str:
        """Run the dynamic agent loop to completion, returning the candidate answer."""
        limits = self._limits()
        await self._prepare_system1()
        system_text = self._build_system_prompt(limits, role="plan")
        messages: list[Message] = [Message(role="system", content=system_text)]
        messages.extend(self._load_history())
        messages.append(Message(role="user", content=self._goal))

        turn = 0
        model_calls = 0
        tokens_used = 0
        last_input_tokens: int | None = None
        consecutive_invalid_turns = 0
        escalated = False
        escalation_triggered = False
        seen_looping_notice = False
        grounding_repaired = False
        self._grounding.record_user_message(self._goal)

        candidate_answer: str | None = None
        intent = self._intent
        action_performed = False
        action_verified = False
        action_prompted = False
        had_blocked = False
        had_declined = False
        had_failed_step = False

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

            # 2. Visible capability namespaces
            visible_tools = self._get_visible_tools()
            shown_tools = await self._capabilities(visible_tools)

            tool_schemas: list[ToolSchema] = []
            for name, t in sorted(shown_tools.items(), key=lambda item: item[0]):
                cached_schema = self._schema_cache.get(name)
                if cached_schema is None or cached_schema.description != t.spec.doc:
                    cached_schema = ToolSchema(name=name, description=t.spec.doc, parameters=dict(t.spec.schema))
                    self._schema_cache[name] = cached_schema
                tool_schemas.append(cached_schema)

            # 3. Check budgets
            max_steps = limits.max_agent_steps
            if self._sheet and self._sheet.limits and self._sheet.limits.steps is not None:
                max_steps = min(max_steps, self._sheet.limits.steps)
            if self._profile and self._profile.steps is not None:
                max_steps = min(max_steps, self._profile.steps)

            max_calls = limits.max_model_calls
            if self._sheet and self._sheet.limits and self._sheet.limits.model_calls is not None:
                max_calls = min(max_calls, self._sheet.limits.model_calls)

            max_tokens = limits.max_task_tokens
            if self._sheet and self._sheet.limits and self._sheet.limits.tokens is not None:
                max_tokens = min(max_tokens, self._sheet.limits.tokens)

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

            # Update system prompt if role has changed
            if messages and messages[0].role == "system":
                new_sys = self._build_system_prompt(limits, role=role)
                if messages[0].content != new_sys:
                    messages[0] = Message(role="system", content=new_sys)

            # 4. Resolve pinned model or role tag
            raw_pin = (
                (self._profile.models.get(role) if self._profile else None)
                or (self._sheet.models.get(role) if self._sheet else None)
                or self._role_models.get(role)
                or self._pin_model
            )
            tag = None
            if raw_pin and raw_pin.startswith("tag:"):
                tag = raw_pin.split(":", 1)[1].strip()
            role_pin, _tag_hint = resolve_ref(raw_pin, (), role=role)

            messages = await self._context_mgr.prepare(
                messages, label=self._rec.ctx.label, mode=self._rec.ctx.mode, task_id=self._rec.task_id,
                actual_tokens=last_input_tokens,
            )

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
                if getattr(self._completer, "supports_system1_routing", False):
                    done = await self._completer.complete(
                        r, need=self._system1_capability, label=self._rec.ctx.label, task_id=self._rec.task_id,
                        payload_hash=digest, mode=self._rec.ctx.mode, pin=p,
                        task_complexity=self._task_complexity,
                        requires_tools=bool(r.tools), requires_vision=self._system1_requires_vision,
                        model_tier=self._system1_model_tier, tool_family=self._system1_tool_family,
                        verification=self._system1_verification,
                    )
                else:
                    done = await self._completer.complete(
                        r, need=self._system1_capability, label=self._rec.ctx.label, task_id=self._rec.task_id,
                        payload_hash=digest, mode=self._rec.ctx.mode, pin=p,
                    )
                self._rec.models.append(done.model)
                return done

            done = await self._steps.with_model_permission(invoke_model, stage_name, self._rec.state_now)
            model_calls += 1
            last_input_tokens = done.result.input_tokens
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
            # Case B: Model returned direct answer without tool calls
            elif not done.result.tool_calls:
                candidate_answer = done.result.text.strip()

            if candidate_answer is not None:
                # Do not let a model stop after opening a page/app or after a
                # mutation whose resulting state has not been inspected. The
                # next turn is deliberately model-driven; this guard only
                # enforces the user's requested outcome boundary.
                if (intent.value == "ACTION" and not action_verified and tool_choice != "none"
                        and remaining_calls > 1 and (not action_prompted or action_performed)):
                    action_prompted = True
                    messages.append(Message(role="assistant", content=candidate_answer))
                    messages.append(Message(
                        role="user",
                        content=(
                            "This is an ACTION request. Do not report completion yet. "
                            "Perform the requested interaction if it has not happened, then inspect a fresh "
                            "browser/desktop state and verify the user-visible outcome."
                        ),
                    ))
                    turn += 1
                    candidate_answer = None
                    continue
                if self._grounding.enabled:
                    is_grounded, unseen = self._grounding.verify(candidate_answer)
                    if not is_grounded:
                        if not grounding_repaired and tool_choice != "none" and remaining_calls > 1:
                            grounding_repaired = True
                            repair_prompt = self._grounding.repair_prompt(unseen)
                            messages.append(Message(role="assistant", content=candidate_answer))
                            messages.append(Message(role="user", content=repair_prompt))
                            turn += 1
                            candidate_answer = None
                            continue
                        else:
                            candidate_answer = self._grounding.remove_unseen(candidate_answer, unseen)
                            await self._rec.event("ground", {"unseen": list(unseen), "action": "removed"})
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
            outcomes: dict[str, StepOutcome] = {}

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
                        cur_outcomes = outcomes

                        async def run_one(
                            st: Mapping[str, Any],
                            b: list[tuple[str, str, dict[str, Any], ModelToolCall]] = cur_batch,
                            vt: dict[str, Tool] = cur_tools,
                            om: dict[str, Message] = cur_obs,
                            oc: dict[str, StepOutcome] = cur_outcomes,
                        ) -> str:
                            sid_st, name_st, args_st = str(st["id"]), str(st["tool"]), st.get("args") or {}
                            args_map = dict(args_st) if isinstance(args_st, Mapping) else {}
                            tc_obj = next(tco for s, _, _, tco in b if s == sid_st)
                            msg, outcome = await self._execute_step(sid_st, name_st, args_map, tc_obj, vt)
                            om[sid_st] = msg
                            oc[sid_st] = outcome
                            return self._outputs.get(sid_st, "")

                        await lanes.run(
                            steps_list,
                            run_one,
                            lambda st: self._steps.abandon(st["id"]),
                            self._outputs,
                        )
                    else:
                        sid, name, args, tc_obj = batch[0]
                        msg, outcome = await self._execute_step(sid, name, args, tc_obj, visible_tools)
                        obs_by_sid[sid] = msg
                        outcomes[sid] = outcome

                # Loop guard advisory: inject notice on first LOOPING
                if self._steps.seen_looping == 1 and not seen_looping_notice:
                    seen_looping_notice = True
                    messages.append(Message(role="user", content=NOTICE_LOOPING))

            # Append all observations from this turn to messages in original call order
            all_sids = [f"t{turn}c{i}" for i in range(1, len(done.result.tool_calls) + 1)]
            messages.extend([obs_by_sid[sid] for sid in all_sids if sid in obs_by_sid])

            for outcome in outcomes.values():
                if outcome.kind == "blocked" or "blocked" in (outcome.reason or ""):
                    had_blocked = True
                elif outcome.kind == "declined":
                    had_declined = True
                elif not outcome.ok:
                    had_failed_step = True

            if intent.value == "ACTION":
                for outcome in outcomes.values():
                    if not outcome.ok:
                        continue
                    if outcome.tool in _ACTION_TOOLS:
                        action_performed = True
                        # Browser and ComputerRuntime interaction tools return
                        # a fresh post-action snapshot/frame. Other mutations
                        # still need an explicit read/observe step.
                        action_verified = outcome.tool in _ACTION_TOOLS_WITH_FRESH_STATE
                    elif action_performed and outcome.tool in _ACTION_OBSERVATION_TOOLS:
                        action_verified = True

            # Early finish for terminal tools (P2-Bc)
            text_with_calls = (done.result.text or "").strip()
            if (self._engine_settings().finish_on_terminal
                    and outcomes
                    and not text_with_calls                       # the model said nothing else this turn
                    and all(o.ok and o.terminal for o in outcomes.values())
                    and len(outcomes) == len(done.result.tool_calls)       # every call was valid and terminal
                    and (intent.value != "ACTION" or action_verified)):
                candidate_answer = " ".join(o.summary for o in outcomes.values())
                # Leave the loop through the same exit used when the model returns an answer with no tool calls
                break

            # Update used tools from outcomes (P2-C-2)
            for outcome in outcomes.values():
                if outcome.kind != "unavailable":  # only count tools that were actually available
                    self._used_tools.add(outcome.tool)

            # Expand the next turn from the existing, policy-filtered catalog. Discovery
            # cannot grant access or alter a tool's risk; it only removes prompt hiding.
            for sid, outcome in outcomes.items():
                if outcome.tool != "agent.discover" or not outcome.ok:
                    continue
                call = next((tc for step_id, _, _, tc in valid_calls if step_id == sid), None)
                if call is None:
                    continue
                args = dict(call.arguments or {}) if isinstance(call.arguments, Mapping) else {}
                raw_limit = args.get("limit", 12)
                limit = raw_limit if isinstance(raw_limit, int) and not isinstance(raw_limit, bool) else 12
                self._discovered_tools.update(discover(
                    {name: tool.spec for name, tool in visible_tools.items()},
                    str(args.get("query", "")),
                    namespace=str(args.get("namespace", "")) or None,
                    limit=limit,
                ))

            # Check whether any step on this turn failed or had schema error

        if not candidate_answer:
            raise Stop(TaskState.FAILED, "there was no answer to give")

        outcome_val, outcome_reason, verified = self._evaluate_outcome(
            candidate_answer,
            intent=intent,
            action_performed=action_performed,
            action_verified=action_verified,
            had_blocked=had_blocked,
            had_declined=had_declined,
            had_failed_step=had_failed_step,
        )
        return LoopAnswer(candidate_answer, outcome=outcome_val, outcome_reason=outcome_reason, verified=verified)
