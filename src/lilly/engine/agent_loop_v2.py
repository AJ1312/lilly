"""Lilly 2.0 Agent Loop: Clean, iterative agent loop with System 1 integration.

This module implements the new agent loop that integrates:
- System 1 (Laya) for fast routing decisions
- ModelBroker for intelligent model selection
- SessionRuntime for persistent state
- Clean, iterative turn-by-turn execution

The core principles:
1. The model pool is a single logical inference layer
2. Laya is System 1, not the main agent
3. Deterministic policy remains the hard boundary
4. Runtime bookkeeping belongs to the runtime
5. Tools must be discoverable without crippling the model
6. Per-turn model selection is supported
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from lilly.providers.model_broker import ModelBroker, RoutingResult, RoutingDecision
from lilly.engine.session_runtime import SessionRuntime, SessionMetadata, SessionStatus
from lilly.decide.system1 import (
    System1Engine,
    DecisionType,
    TaskClassification,
    ComplexityAssessment,
    ModelTierDecision,
    CapabilityRouting,
    ToolFamilyDecision,
    VerificationDecision,
    MemoryRelevance,
    TaskClass,
    ComplexityLevel,
    ModelTier,
)
from lilly.domain.caps import Cap
from lilly.domain.clock import Clock
from lilly.domain.errors import NoModelAvailable, PolicyDenied
from lilly.domain.labels import Label, Mode, Verdict
from lilly.domain.ports import (
    Completed,
    CompletionRequest,
    CompletionResult,
    Message,
    ModelToolCall,
    ToolSchema,
    ToolContext,
)
from lilly.domain.policy import PathScope, decide
from lilly.domain.plan import tool_call
from lilly.domain.settings import EngineSettings, LimitSettings, GroundingSettings
from lilly.domain.tasks import TaskState
from lilly.domain.text import fence
from lilly.engine.bus import EventBus
from lilly.engine.context import ContextManager
from lilly.engine.lanes import LaneScheduler, parallel_eligible
from lilly.engine.outcome import StepOutcome, Stop
from lilly.engine.record import TaskRecord
from lilly.engine.steps import StepExecutor
from lilly.store.db import Database
from lilly.tools.base import Tool

log = logging.getLogger("lilly.agent_loop_v2")


@dataclass(frozen=True, slots=True)
class AgentLoopConfig:
    """Configuration for the agent loop."""
    max_iterations: int = 50
    max_model_calls: int = 20
    max_tokens: int = 16000
    step_timeout: float = 60.0  # seconds
    overall_timeout: float = 300.0  # seconds
    enable_system1: bool = True
    enable_verification: bool = True
    enable_memory: bool = True
    observation_chars: int = 4000
    finish_on_terminal: bool = True


@dataclass(slots=True)
class AgentState:
    """State of the agent loop for a specific task."""
    session_id: str
    task_id: str
    goal: str
    messages: list[Message]
    current_iteration: int
    model_calls: int
    tokens_used: int
    tool_results: dict[str, StepOutcome]
    pending_tool_calls: list[tuple[str, str, dict[str, Any], ModelToolCall]]
    completed: bool
    failed: bool
    candidate_answer: str | None
    
    # System 1 decisions
    task_classification: TaskClassification | None
    complexity_assessment: ComplexityAssessment | None
    routing_decision: ModelTierDecision | None
    capability_routing: CapabilityRouting | None
    verification_decision: VerificationDecision | None
    memory_relevance: MemoryRelevance | None
    
    # Runtime info
    current_model: str | None
    last_model_call_ms: int | None
    last_tool_call_ms: int | None
    started_at: float
    last_activity_at: float
    
    def can_continue(self, config: AgentLoopConfig) -> bool:
        """Check if the loop can continue based on limits."""
        return (self.current_iteration < config.max_iterations and
                self.model_calls < config.max_model_calls and
                self.tokens_used < config.max_tokens)


class AgentLoopV2:
    """Lilly 2.0 Agent Loop: Clean, iterative agent loop.
    
    This loop implements the core agent reasoning process with:
    - System 1 integration for fast decisions
    - ModelBroker for intelligent model selection
    - Per-turn model switching capability
    - Clean separation of concerns
    - Full observability
    """
    
    def __init__(
        self,
        session_runtime: SessionRuntime,
        model_broker: ModelBroker,
        steps: StepExecutor,
        tools: Callable[[], Mapping[str, Tool]],
        scope: Callable[[], PathScope],
        file_roots: Callable[[], tuple[str, ...]],
        limits: Callable[[], LimitSettings],
        engine_settings: Callable[[], EngineSettings],
        db: Database,
        bus: EventBus,
        task_record: TaskRecord,
        goal: str,
        conversation_id: str,
        agent_instructions: str = "",
        pin_model: str | None = None,
        pet_name: str = "Lilly",
        system1_engine: System1Engine | None = None,
        config: AgentLoopConfig | None = None,
        grounding_settings: Callable[[], GroundingSettings] | GroundingSettings | None = None,
    ) -> None:
        self._session_runtime = session_runtime
        self._model_broker = model_broker
        self._steps = steps
        self._tools = tools
        self._scope = scope
        self._file_roots = file_roots
        self._limits = limits
        self._engine_settings = engine_settings
        self._db = db
        self._bus = bus
        self._task_record = task_record
        self._goal = goal
        self._conversation_id = conversation_id
        self._agent_instructions = agent_instructions
        self._pin_model = pin_model
        self._pet_name = pet_name
        self._system1_engine = system1_engine
        self._config = config or AgentLoopConfig()
        self._grounding_settings = grounding_settings
        
        # Context manager for context assembly
        self._context_mgr = ContextManager(engine_settings, model_broker)
        
        # State will be initialized per-task
        self._state: AgentState | None = None
        
        log.info(f"AgentLoopV2 initialized for task {task_record.task_id}")

    async def run(self) -> str:
        """Run the agent loop to completion, returning the final answer."""
        # Create session
        session = self._session_runtime.create_session(
            task_id=self._task_record.task_id,
            goal=self._goal,
            conversation_id=self._conversation_id,
        )
        
        self._session_runtime.add_session_event(
            session.session_id, 
            "loop_started", 
            {"goal": self._goal[:100]}
        )
        
        # Initialize state
        self._state = AgentState(
            session_id=session.session_id,
            task_id=self._task_record.task_id,
            goal=self._goal,
            messages=[],
            current_iteration=0,
            model_calls=0,
            tokens_used=0,
            tool_results={},
            pending_tool_calls=[],
            completed=False,
            failed=False,
            candidate_answer=None,
            task_classification=None,
            complexity_assessment=None,
            routing_decision=None,
            capability_routing=None,
            verification_decision=None,
            memory_relevance=None,
            current_model=None,
            last_model_call_ms=None,
            last_tool_call_ms=None,
            started_at=time.monotonic(),
            last_activity_at=time.monotonic(),
        )
        
        try:
            # Start session
            await self._session_runtime.start_session(session.session_id)
            
            # Make System 1 decisions if enabled
            if self._config.enable_system1 and self._system1_engine:
                await self._make_system1_decisions()
            
            # Build initial context
            messages = await self._build_initial_context()
            self._state.messages = messages
            
            # Main loop
            while not self._state.completed and not self._state.failed:
                if self._task_record.cancelled:
                    raise Stop(TaskState.CANCELLED, "Task was cancelled")
                
                # Check limits
                if not self._state.can_continue(self._config):
                    log.info("Loop limits reached")
                    break
                
                # Determine next action
                action = self._determine_next_action()
                
                if action == "generate":
                    # Generate a response from the model
                    await self._generate_response()
                elif action == "execute_tools":
                    # Execute pending tool calls
                    await self._execute_pending_tools()
                elif action == "complete":
                    # We have a candidate answer, complete
                    self._state.completed = True
                else:
                    # Unknown action, break
                    log.warning(f"Unknown action: {action}")
                    break
                
                self._state.current_iteration += 1
                
            # Return the answer
            if self._state.candidate_answer:
                return self._state.candidate_answer
            elif self._state.tool_results:
                # Return summary of tool results
                summaries = [result.summary for result in self._state.tool_results.values() if result.summary]
                return " ".join(summaries) if summaries else "Task completed with no explicit answer."
            else:
                return "No answer generated."
                
        except Stop as stop:
            # Task was stopped
            await self._session_runtime.fail_session(session.session_id, str(stop.reason))
            raise
        except Exception as e:
            # Unexpected error
            log.exception(f"Agent loop failed: {e}")
            await self._session_runtime.fail_session(session.session_id, str(e))
            raise
        finally:
            # Complete or fail session
            if self._state and self._state.completed:
                await self._session_runtime.complete_session(session.session_id, self._state.candidate_answer)
            elif self._state and self._state.failed:
                await self._session_runtime.fail_session(session.session_id, "Loop failed")

    def _determine_next_action(self) -> str:
        """Determine the next action to take in the loop."""
        # If we have a candidate answer, we're done
        if self._state.candidate_answer:
            return "complete"
        
        # If we have pending tool calls, execute them
        if self._state.pending_tool_calls:
            return "execute_tools"
        
        # If we have tool results but no pending calls, generate a response
        if self._state.tool_results:
            return "generate"
        
        # If no tool results and no pending calls, generate initial response
        return "generate"

    async def _make_system1_decisions(self) -> None:
        """Make System 1 decisions for routing and capability assessment."""
        if not self._system1_engine:
            return
        
        # Task classification and complexity
        classification, complexity = await self._system1_engine.assess_task(
            self._goal, 
            self._state.task_id
        )
        self._state.task_classification = classification
        self._state.complexity_assessment = complexity
        
        # Determine routing based on classification
        available_models = tuple(self._model_broker.get_available_models())
        available_tools = tuple(self._tools().keys()) if self._tools else ()
        
        routing, capability, tool_family = await self._system1_engine.determine_routing(
            self._goal, available_models, available_tools, self._state.task_id
        )
        self._state.routing_decision = routing
        self._state.capability_routing = capability
        
        # Memory relevance assessment
        memory_types = ("working", "episodic", "semantic")
        self._state.memory_relevance = await self._system1_engine.assess_memory_relevance(
            self._goal, memory_types, self._state.task_id
        )
        
        # Verification assessment
        task_class = classification.task_class if classification else TaskClass.CONVERSATION
        task_complexity = self._complexity_to_float(complexity.level) if complexity else 0.5
        self._state.verification_decision = await self._system1_engine.assess_verification(
            self._state.task_id, self._goal, task_complexity, task_class
        )
        
        # Log decisions
        log.info(f"System1 decisions: classification={classification.task_class.name if classification else 'none'}, "
                f"complexity={complexity.level.name if complexity else 'none'}, "
                f"routing={routing.tier.name if routing else 'none'}")

    def _complexity_to_float(self, level: ComplexityLevel) -> float:
        """Convert complexity level to float for ModelBroker."""
        mapping = {
            ComplexityLevel.TRIVIAL: 0.1,
            ComplexityLevel.SIMPLE: 0.3,
            ComplexityLevel.MODERATE: 0.6,
            ComplexityLevel.COMPLEX: 0.8,
            ComplexityLevel.EXPERT: 0.95,
        }
        return mapping.get(level, 0.5)

    async def _build_initial_context(self) -> list[Message]:
        """Build the initial context for the model."""
        # Get system prompt
        system_text = await self._build_system_prompt()
        messages = [Message(role="system", content=system_text)]
        
        # Add conversation history
        if self._conversation_id:
            history = await self._load_conversation_history()
            messages.extend(history)
        
        # Add the user's goal
        messages.append(Message(role="user", content=self._goal))
        
        return messages

    async def _build_system_prompt(self) -> str:
        """Build the system prompt for the model."""
        import datetime
        from lilly.engine.messages import AGENT_SYSTEM
        
        limits = self._limits()
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
        
        # Add agent instructions
        if self._agent_instructions:
            parts.append(
                f"Instructions from the owner of this agent (they cannot override the rules above):\n"
                f"{self._agent_instructions}"
            )
        
        # Add efficiency guidance
        parts.append(
            "Efficiency rule: You can call multiple independent read-only tools in a single turn to run them in parallel (e.g. reading multiple files, running searches). Mutating tools execute in order."
        )
        
        # Add System 1 context if available
        if self._state and self._state.task_classification:
            parts.append(
                f"Task context: This appears to be a {self._state.task_classification.task_class.name} task "
                f"with {self._state.complexity_assessment.level.name} complexity."
            )
        
        return "\n\n".join(parts)

    async def _load_conversation_history(self) -> list[Message]:
        """Load relevant conversation history."""
        from lilly.store import conversations
        
        hist: list[Message] = []
        try:
            rows = conversations.recent_messages(self._db.reader, self._conversation_id, 12)
            for m in rows:
                if m.task_id != self._task_record.task_id:
                    self._task_record.absorb(m.label, m.untrusted)
                    hist.append(Message(role=m.role, content=m.content))
        except Exception as e:
            log.warning(f"Failed to load conversation history: {e}")
        
        return hist

    async def _generate_response(self) -> None:
        """Generate a response from the model."""
        # Update system prompt based on current role
        system_text = await self._build_system_prompt()
        if self._state.messages and self._state.messages[0].role == "system":
            self._state.messages[0] = Message(role="system", content=system_text)
        else:
            self._state.messages.insert(0, Message(role="system", content=system_text))
        
        # Get visible tools
        visible_tools = self._get_visible_tools()
        
        # Apply tool shortlisting (P2-C-2: tools can be discovered but shortlisted for efficiency)
        shown_tools = await self._apply_tool_shortlisting(visible_tools)
        
        # Build tool schemas
        tool_schemas = [
            ToolSchema(name=name, description=t.spec.doc, parameters=dict(t.spec.schema))
            for name, t in sorted(shown_tools.items(), key=lambda item: item[0])
        ]
        
        # Determine if this is a final call
        remaining_calls = self._config.max_model_calls - self._state.model_calls
        remaining_iterations = self._config.max_iterations - self._state.current_iteration
        remaining_tokens = self._config.max_tokens - self._state.tokens_used
        
        is_final_call = (remaining_calls <= 1 or remaining_iterations <= 0 or remaining_tokens <= 0)
        tool_choice = "none" if is_final_call else "auto"
        
        # Determine role based on iteration
        if self._state.current_iteration == 0:
            role = "plan"
        else:
            role = "act"
        
        if is_final_call:
            role = "write"
        
        # Select model using ModelBroker
        routing_result = await self._select_model_for_turn(role, visible_tools, shown_tools)
        
        # Update session with routing decision
        await self._session_runtime.add_routing_decision(self._state.session_id, routing_result)
        
        # Build completion request
        max_tokens = min(4096, max(remaining_tokens, 512) if remaining_tokens > 0 else 4096)
        
        req = CompletionRequest(
            messages=tuple(self._state.messages),
            max_tokens=max_tokens,
            tools=tuple(tool_schemas) if tool_choice != "none" else (),
            tool_choice=tool_choice,
            role=role,
            deadline_s=self._config.step_timeout,
        )
        
        # Execute the model call
        try:
            start_time = time.monotonic()
            
            completed = await self._model_broker.complete(
                req,
                need=self._get_required_capabilities(visible_tools),
                label=self._task_record.ctx.label,
                task_id=self._state.task_id,
                payload_hash=None,  # TODO: Implement proper payload hashing
                mode=self._task_record.ctx.mode,
                pin=self._pin_model,
                role=role,
                task_complexity=self._complexity_to_float(
                    self._state.complexity_assessment.level) if self._state.complexity_assessment else 0.5
                ,
                requires_tools=bool(shown_tools),
                requires_vision=False,
            )
            
            self._state.last_model_call_ms = int((time.monotonic() - start_time) * 1000)
            self._state.current_model = completed.model
            self._state.model_calls += 1
            self._state.tokens_used += completed.result.input_tokens + completed.result.output_tokens
            
            # Update session model
            await self._session_runtime.update_session_model(self._state.session_id, completed.model)
            
            # Process the response
            await self._process_model_response(completed.result, visible_tools, shown_tools, is_final_call, tool_choice)
            
        except NoModelAvailable as e:
            log.error(f"No model available: {e}")
            self._state.failed = True
            raise
        except Exception as e:
            log.error(f"Model call failed: {e}")
            self._state.failed = True
            raise

    def _get_required_capabilities(self, visible_tools: dict[str, Tool]) -> Cap:
        """Get the required capabilities based on visible tools."""
        required = Cap.NONE
        for tool in visible_tools.values():
            required |= tool.spec.caps
        return required



    def _get_visible_tools(self) -> dict[str, Tool]:
        """Get all visible tools for the current context."""
        all_tools = dict(self._tools())
        visible: dict[str, Tool] = {}
        
        # Always visible tools
        ALWAYS_VISIBLE = frozenset({"agent.ask"})
        
        for name, tool in all_tools.items():
            if name not in ALWAYS_VISIBLE:
                # Apply any filtering (e.g., from agent sheets, permissions)
                # For now, include all tools
                pass
            visible[name] = tool
        
        return visible

    async def _apply_tool_shortlisting(self, visible_tools: dict[str, Tool]) -> dict[str, Tool]:
        """Apply tool shortlisting for efficiency while preserving discoverability."""
        # For now, return all visible tools
        # In the future, this could implement smarter shortlisting
        return visible_tools

    async def _select_model_for_turn(
        self, 
        role: str, 
        visible_tools: dict[str, Tool], 
        shown_tools: dict[str, Tool]
    ) -> RoutingResult:
        """Select the best model for the current turn."""
        # Use System 1 routing decision if available
        if self._state.routing_decision:
            tier = self._state.routing_decision.tier
            if tier == ModelTier.QUICK:
                pin = self._find_quick_model()
            elif tier == ModelTier.STRONG:
                pin = self._find_strong_model()
            elif tier == ModelTier.VISION:
                pin = self._find_vision_model()
            else:
                pin = None
        else:
            pin = self._pin_model
        
        # Use ModelBroker for selection
        return await self._model_broker.select_model(
            need=self._get_required_capabilities(visible_tools),
            label=self._task_record.ctx.label,
            pin=pin,
            mode=self._task_record.ctx.mode,
            task_id=self._state.task_id,
            task_complexity=self._complexity_to_float(
                self._state.complexity_assessment.level) if self._state.complexity_assessment else 0.5,
            requires_tools=bool(shown_tools),
            requires_vision=False,
        )

    def _find_quick_model(self) -> str | None:
        """Find a quick model from available models."""
        for spec in self._model_broker.pool.entries:
            if spec.spec.enabled and spec.spec.quick:
                return spec.name
        return None

    def _find_strong_model(self) -> str | None:
        """Find a strong model from available models."""
        # Look for models with high reasoning capability
        strong_providers = ("mistral", "openrouter", "openai")
        for spec in self._model_broker.pool.entries:
            if (spec.spec.enabled and 
                spec.spec.provider in strong_providers and
                spec.spec.model_id):
                # Prefer larger models
                if "large" in spec.spec.model_id.lower() or "plus" in spec.spec.model_id.lower():
                    return spec.name
        
        # Fallback to first enabled model
        for spec in self._model_broker.pool.entries:
            if spec.spec.enabled:
                return spec.name
        return None

    def _find_vision_model(self) -> str | None:
        """Find a vision-capable model from available models."""
        vision_providers = ("gemini", "openai")
        for spec in self._model_broker.pool.entries:
            if (spec.spec.enabled and 
                spec.spec.provider in vision_providers and
                ("vision" in spec.spec.model_id.lower() or 
                 spec.spec.caps & Cap.VISION)):
                return spec.name
        return None

    async def _process_model_response(
        self, 
        result: CompletionResult, 
        visible_tools: dict[str, Tool],
        shown_tools: dict[str, Tool], 
        is_final_call: bool,
        tool_choice: str
    ) -> None:
        """Process the model's response and extract tool calls."""
        # Add model response to messages
        self._state.messages.append(Message(
            role="assistant", 
            content=result.text, 
            tool_calls=result.tool_calls
        ))
        
        # Check for direct answer (no tool calls and not final call)
        if not result.tool_calls and result.text.strip():
            # This might be the final answer
            self._state.candidate_answer = result.text.strip()
            return
        
        # If this was a final call, extract answer
        if is_final_call or tool_choice == "none":
            if result.text.strip():
                self._state.candidate_answer = result.text.strip()
            else:
                # No text, but maybe tool results
                n_done = len(self._state.tool_results)
                one_line = f"{n_done} step(s) finished"
                self._state.candidate_answer = f"Task completed. {one_line}"
            return
        
        # Process tool calls
        valid_calls: list[tuple[str, str, dict[str, Any], ModelToolCall]] = []
        obs_by_sid: dict[str, Message] = {}
        
        for i, tc in enumerate(result.tool_calls, start=1):
            step_id = f"t{self._state.current_iteration + 1}c{i}"
            
            if tc.name not in visible_tools:
                # Tool not available
                avail = ", ".join(sorted(visible_tools.keys()))
                obs_text = f"Tool {tc.name} is not available. Available tools: {avail}"
                obs_by_sid[step_id] = Message(role="tool", content=obs_text, tool_call_id=tc.id or tc.name)
                continue
            
            tool = visible_tools[tc.name]
            spec = tool.spec
            args = dict(tc.arguments or {}) if isinstance(tc.arguments, Mapping) else {}
            
            # Validate schema
            from lilly.domain.schema import validate_schema
            errs = validate_schema(spec.schema, args)
            if errs:
                err_msg = errs[0]
                obs_text = f"Invalid arguments for {tc.name}: {err_msg}"
                obs_by_sid[step_id] = Message(role="tool", content=obs_text, tool_call_id=tc.id or tc.name)
                continue
            
            valid_calls.append((step_id, tc.name, args, tc))
        
        # Store pending tool calls
        self._state.pending_tool_calls = valid_calls
        
        # Add any observations for invalid calls
        for sid, obs in obs_by_sid.items():
            self._state.messages.append(obs)

    async def _execute_pending_tools(self) -> None:
        """Execute all pending tool calls."""
        if not self._state.pending_tool_calls:
            return
        
        visible_tools = self._get_visible_tools()
        valid_calls = self._state.pending_tool_calls
        self._state.pending_tool_calls = []  # Clear pending calls
        
        # Partition into parallel and serial calls
        batches: list[list[tuple[str, str, dict[str, Any], ModelToolCall]]] = []
        current_parallel_batch: list[tuple[str, str, dict[str, Any], ModelToolCall]] = []
        
        for item in valid_calls:
            sid, name, args, tc = item
            eligible = parallel_eligible(
                {"tool": name, "args": args},
                visible_tools[name].spec,
                self._task_record.ctx,
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
        
        # Execute batches
        for batch in batches:
            if len(batch) > 1:
                # Parallel execution
                await self._execute_parallel_batch(batch, visible_tools)
            else:
                # Serial execution
                await self._execute_serial_batch(batch, visible_tools)

    async def _execute_parallel_batch(
        self, 
        batch: list[tuple[str, str, dict[str, Any], ModelToolCall]], 
        visible_tools: dict[str, Tool]
    ) -> None:
        """Execute a batch of tool calls in parallel."""
        limits = self._limits()
        specs = {n: t.spec for n, t in visible_tools.items()}
        
        lanes = LaneScheduler(
            specs,
            self._scope(),
            limits.lanes,
            lambda: self._task_record.ctx,
            self._steps.may_taint,
        )
        
        steps_list = [{"id": sid, "tool": name, "args": args} for sid, name, args, _ in batch]
        
        async def run_one(st: Mapping[str, Any]) -> str:
            sid_st, name_st, args_st = str(st["id"]), str(st["tool"]), st.get("args") or {}
            args_map = dict(args_st) if isinstance(args_st, Mapping) else {}
            tc_obj = next(tco for s, _, _, tco in batch if s == sid_st)
            
            msg, outcome = await self._execute_single_tool(sid_st, name_st, args_map, tc_obj, visible_tools)
            self._state.tool_results[sid_st] = outcome
            return self._state.tool_results[sid_st].output if outcome.output else ""
        
        try:
            await lanes.run(
                steps_list,
                run_one,
                lambda st: self._steps.abandon(st["id"]),
                self._state.tool_results,
            )
        except Exception as e:
            log.error(f"Parallel tool execution failed: {e}")

    async def _execute_serial_batch(
        self, 
        batch: list[tuple[str, str, dict[str, Any], ModelToolCall]], 
        visible_tools: dict[str, Tool]
    ) -> None:
        """Execute a batch of tool calls serially."""
        for sid, name, args, tc_obj in batch:
            msg, outcome = await self._execute_single_tool(sid, name, args, tc_obj, visible_tools)
            self._state.tool_results[sid] = outcome

    async def _execute_single_tool(
        self, 
        step_id: str, 
        name: str, 
        args: dict[str, Any], 
        tc: ModelToolCall,
        tools_dict: dict[str, Tool]
    ) -> tuple[Message, StepOutcome]:
        """Execute a single tool call."""
        tool = tools_dict.get(name)
        if tool is None:
            outcome = StepOutcome(step_id=step_id, tool=name, kind="unavailable", reason="tool unavailable")
            msg = Message("tool", f"Tool {name} is unavailable", tool_call_id=tc.id or tc.name)
            return msg, outcome
        
        spec = tool.spec
        args_dict = dict(args)
        
        # Check policy before running
        verdict, why = decide(tool_call(name, spec, args_dict), self._task_record.ctx, self._scope())
        if verdict is not Verdict.DENY and (own := tool.review(args_dict, self._task_record.task_id))[0] > verdict:
            verdict, why = own
        if verdict is Verdict.DENY:
            await self._task_record.step_status(step_id, "failed", error=f"blocked: {why}")
            await self._task_record.thought("blocked", f"{name} was blocked by policy: {why}.", step=step_id)
            outcome = StepOutcome(step_id=step_id, tool=name, kind="blocked", reason=why)
            msg = Message("tool", f"{name} was blocked by policy: {why}", tool_call_id=tc.id or tc.name)
            return msg, outcome
        
        try:
            start_time = time.monotonic()
            output = await self._steps.run(
                {"tool": name, "args": args},
                step_id,
                {},  # outputs
                tools_dict,
                decline_continues=True,
            )
            self._state.last_tool_call_ms = int((time.monotonic() - start_time) * 1000)
            
            # Format successful observation
            untrusted = spec.untrusted or self._task_record.ctx.tainted
            obs_chars = self._config.observation_chars
            if untrusted:
                body, cut = fence(output, obs_chars)
            else:
                cut = len(output) > obs_chars
                body = output[:obs_chars] if cut else output
            shown_suffix = f", showing the first {obs_chars}" if cut else ""
            truncated_suffix = ('\n[truncated: call result.read with {"step": "' + step_id + '", "offset": ' + str(obs_chars) + '} for more]' if cut else "")
            
            obs = f"RESULT {step_id}: {name} returned {len(output)} chars{shown_suffix}{truncated_suffix}"
            if body:
                obs += f"\n{body}"
            
            outcome = StepOutcome(
                step_id=step_id,
                tool=name,
                kind="ok",
                output=output,
                terminal=spec.terminal,
                summary=tool.summary(args, output)
            )
            return Message("tool", obs, tool_call_id=tc.id or tc.name), outcome
            
        except Exception as e:
            log.error(f"Tool {name} execution failed: {e}")
            outcome = StepOutcome(step_id=step_id, tool=name, kind="failed", reason=str(e))
            msg = Message("tool", f"Tool {name} failed: {e}", tool_call_id=tc.id or tc.name)
            return msg, outcome