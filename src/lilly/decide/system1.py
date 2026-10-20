"""Laya System 1 Decision Layer.

This module implements Laya as a fast, typed decision layer (System 1) that provides
intelligent routing, capability selection, and verification decisions before
expensive generative calls.

System 1 (Laya) vs System 2 (Generative LLM):
- System 1: Fast, cheap, typed decisions for routing and capability selection
- System 2: Expensive, generative reasoning for complex tasks

Laya should provide:
- task classification
- complexity estimation
- capability routing
- model-tier selection
- tool-family selection
- delegation choice
- urgency assessment
- wake/sleep decisions
- retry decisions
- memory relevance
- verification necessity

The probabilistic layer (Laya) can recommend.
The deterministic layer (policy) decides what is actually allowed.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

from lilly.domain.caps import Cap
from lilly.domain.decisions import Answer, Context, Kind, Option, Request
from lilly.domain.settings import EngineSettings

log = logging.getLogger("lilly.system1")


class DecisionType(Enum):
    """Types of decisions that Laya can make as System 1."""

    # Task classification
    TASK_CLASSIFICATION = "task_classification"
    COMPLEXITY_ESTIMATION = "complexity_estimation"

    # Routing decisions
    MODEL_TIER_SELECTION = "model_tier_selection"
    CAPABILITY_ROUTING = "capability_routing"
    TOOL_FAMILY_SELECTION = "tool_family_selection"

    # Execution decisions
    DELEGATION_CHOICE = "delegation_choice"
    URGENCY_ASSESSMENT = "urgency_assessment"
    WAKE_SLEEP_DECISION = "wake_sleep_decision"
    RETRY_DECISION = "retry_decision"

    # Memory decisions
    MEMORY_RELEVANCE = "memory_relevance"
    VERIFICATION_NECESSITY = "verification_necessity"


class TaskClass(Enum):
    """Classification of task types."""

    RESEARCH = "research"  # Information gathering, web search, analysis
    CODING = "coding"  # Code generation, debugging, review
    DATA_ANALYSIS = "data_analysis"  # Data processing, transformation, visualization
    DOCUMENTATION = "documentation"  # Writing, editing, summarizing text
    SYSTEM_OPERATION = "system_operation"  # File operations, process management
    WEB_BROWSING = "web_browsing"  # Web navigation, extraction, interaction
    MULTI_STEP = "multi_step"  # Complex tasks requiring multiple steps
    SIMPLE_QUERY = "simple_query"  # Direct questions with simple answers
    CONVERSATION = "conversation"  # General conversation


class ComplexityLevel(Enum):
    """Estimated complexity of a task."""

    TRIVIAL = "trivial"  # Can be answered from general knowledge
    SIMPLE = "simple"  # Requires one model call, no tools
    MODERATE = "moderate"  # May require tools or multiple steps
    COMPLEX = "complex"  # Requires planning, multiple steps, tool usage
    EXPERT = "expert"  # Requires advanced reasoning, potentially delegation


class ModelTier(Enum):
    """Model tiers for routing decisions."""

    QUICK = "quick"  # Fast, cheap models for simple tasks
    STANDARD = "standard"  # Default models for most tasks
    STRONG = "strong"  # High-capability models for complex tasks
    VISION = "vision"  # Vision-capable models
    SPECIALIZED = "specialized"  # Specialized models for specific domains


class ToolFamily(Enum):
    """Tool capability families."""

    NONE = "none"  # No tools needed
    FILESYSTEM = "filesystem"  # File operations
    WEB = "web"  # Web search, browsing
    COMPUTER = "computer"  # Computer control, processes
    DATA = "data"  # Data processing, analysis
    MEMORY = "memory"  # Memory operations
    MCP = "mcp"  # MCP server tools
    BROWSER = "browser"  # Browser automation
    GIT = "git"  # Git operations
    SYSTEM = "system"  # System-level operations


class DelegationStrategy(Enum):
    """Strategies for task delegation."""

    NONE = "none"  # Handle task directly
    SINGLE_AGENT = "single_agent"  # Delegate to one specialist agent
    MULTI_AGENT = "multi_agent"  # Split among multiple specialist agents
    SUPERVISED = "supervised"  # Use supervisor with worker agents
    PARALLEL = "parallel"  # Parallel execution


class UrgencyLevel(Enum):
    """Urgency levels for tasks."""

    LOW = "low"  # Can wait, background processing
    NORMAL = "normal"  # Standard priority
    HIGH = "high"  # Should be prioritized
    IMMEDIATE = "immediate"  # Requires immediate attention


class WakeDecision(Enum):
    """Decisions about waking sleeping components."""

    STAY_ASLEEP = "stay_asleep"  # Don't wake, not needed
    WAKE = "wake"  # Wake the component
    CONDITIONAL = "conditional"  # Wake only if certain conditions are met


class RetryDecision(Enum):
    """Decisions about retrying failed operations."""

    NO_RETRY = "no_retry"  # Do not retry
    IMMEDIATE_RETRY = "immediate_retry"  # Retry immediately
    DELAYED_RETRY = "delayed_retry"  # Retry after delay
    FALLBACK = "fallback"  # Try a different approach


class VerificationLevel(Enum):
    """Levels of verification needed."""

    NONE = "none"  # No verification needed
    LIGHT = "light"  # Quick sanity check
    STANDARD = "standard"  # Standard verification
    THOROUGH = "thorough"  # Comprehensive verification with multiple models


@dataclass(frozen=True, slots=True)
class TaskClassification:
    """Classification of a task."""

    task_class: TaskClass
    confidence: float  # 0.0-1.0
    reasoning: str

    @property
    def needs_tools(self) -> bool:
        """Whether this task likely needs tool usage."""
        return self.task_class in {
            TaskClass.RESEARCH,
            TaskClass.CODING,
            TaskClass.DATA_ANALYSIS,
            TaskClass.SYSTEM_OPERATION,
            TaskClass.WEB_BROWSING,
            TaskClass.MULTI_STEP,
        }

    @property
    def needs_complex_reasoning(self) -> bool:
        """Whether this task requires complex reasoning."""
        return self.task_class in {
            TaskClass.CODING,
            TaskClass.DATA_ANALYSIS,
            TaskClass.MULTI_STEP,
        }


@dataclass(frozen=True, slots=True)
class ComplexityAssessment:
    """Assessment of task complexity."""

    level: ComplexityLevel
    confidence: float  # 0.0-1.0
    estimated_steps: int
    estimated_model_calls: int
    reasoning: str


@dataclass(frozen=True, slots=True)
class ModelTierDecision:
    """Decision about which model tier to use."""

    tier: ModelTier
    confidence: float  # 0.0-1.0
    reasoning: str
    cost_consideration: str | None = None
    speed_consideration: str | None = None


@dataclass(frozen=True, slots=True)
class CapabilityRouting:
    """Routing decision based on required capabilities."""

    primary_capability: Cap
    secondary_capabilities: tuple[Cap, ...]
    required_model_capabilities: tuple[Cap, ...]
    needs_tool_use: bool
    needs_vision: bool
    reasoning: str


@dataclass(frozen=True, slots=True)
class ToolFamilyDecision:
    """Decision about which tool family to prioritize."""

    primary_family: ToolFamily
    secondary_families: tuple[ToolFamily, ...]
    confidence: float  # 0.0-1.0
    reasoning: str


@dataclass(frozen=True, slots=True)
class DelegationDecision:
    """Decision about task delegation."""

    strategy: DelegationStrategy
    confidence: float  # 0.0-1.0
    reasoning: str
    recommended_agents: tuple[str, ...] | None = None
    split_strategy: str | None = None


@dataclass(frozen=True, slots=True)
class UrgencyAssessment:
    """Assessment of task urgency."""

    level: UrgencyLevel
    confidence: float  # 0.0-1.0
    reasoning: str
    time_sensitivity: str | None = None


@dataclass(frozen=True, slots=True)
class WakeSleepDecision:
    """Decision about waking sleeping components."""

    decision: WakeDecision
    component: str
    confidence: float  # 0.0-1.0
    reasoning: str


@dataclass(frozen=True, slots=True)
class RetryDecisionResult:
    """Decision about retrying a failed operation."""

    decision: RetryDecision
    confidence: float  # 0.0-1.0
    reasoning: str
    delay_seconds: float | None = None
    fallback_strategy: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryRelevance:
    """Assessment of memory relevance for a task."""

    relevant: bool
    confidence: float  # 0.0-1.0
    reasoning: str
    relevant_memory_types: tuple[str, ...] = ()  # e.g., "episodic", "semantic", "working"
    query_suggestions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VerificationDecision:
    """Decision about verification necessity."""

    level: VerificationLevel
    confidence: float  # 0.0-1.0
    reasoning: str
    verification_models: tuple[str, ...] | None = None
    verification_criteria: tuple[str, ...] | None = None


# Union type for all System 1 decisions
System1Decision = (
    TaskClassification
    | ComplexityAssessment
    | ModelTierDecision
    | CapabilityRouting
    | ToolFamilyDecision
    | DelegationDecision
    | UrgencyAssessment
    | WakeSleepDecision
    | RetryDecisionResult
    | MemoryRelevance
    | VerificationDecision
)


@dataclass(frozen=True, slots=True)
class System1Request:
    """Request for a System 1 (Laya) decision."""

    decision_type: DecisionType
    task_id: str | None = None
    user_request: str | None = None
    context: Context | None = None
    available_models: tuple[str, ...] | None = None
    available_tools: tuple[str, ...] | None = None
    task_history: list[dict[str, Any]] | None = None
    current_state: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class System1Engine:
    """The System 1 decision engine that uses Laya for fast, typed decisions.

    This engine positions Laya as a fast decision layer before expensive
    generative calls. It provides typed decisions for routing, capability
    selection, and other quick judgments.
    """

    def __init__(
        self,
        laya_decider: Any | None = None,  # LayaDecider instance
        fallback_deciders: dict[DecisionType, Callable[[System1Request], System1Decision]] | None = None,
        engine_settings: Callable[[], EngineSettings] | EngineSettings | None = None,
        on_decision: Callable[[DecisionType, System1Decision], None] | None = None,
        on_missing_laya: Callable[[], None] | None = None,
        laya_enabled: Callable[[], bool] | bool | None = None,
    ) -> None:
        self._laya_decider = laya_decider
        self._fallback_deciders = fallback_deciders or {}
        self._engine_settings = engine_settings
        self._on_decision = on_decision
        self._on_missing_laya = on_missing_laya
        self._laya_enabled = laya_enabled

        # Telemetry
        self._decision_counts: dict[DecisionType, int] = {dt: 0 for dt in DecisionType}
        self._laya_usage_counts: dict[DecisionType, int] = {dt: 0 for dt in DecisionType}
        self._fallback_usage_counts: dict[DecisionType, int] = {dt: 0 for dt in DecisionType}

        log.info("System1Engine initialized")

    @property
    def laya_available(self) -> bool:
        """Check if Laya decider is available."""
        return self._laya_decider is not None

    def set_laya_decider(self, laya_decider: Any | None) -> None:
        """Set the Laya decider instance."""
        self._laya_decider = laya_decider
        log.info("Laya decider set")

    def set_engine_settings(self, engine_settings: Callable[[], EngineSettings] | EngineSettings) -> None:
        """Set the engine settings provider."""
        self._engine_settings = engine_settings

    def set_laya_enabled(self, enabled: Callable[[], bool] | bool) -> None:
        """Update the owner's Laya switch without rebuilding the engine."""
        self._laya_enabled = enabled

    def _deterministic_decide(self, request: System1Request) -> System1Decision | None:
        """Apply fast, free, deterministic classification rules before model calls."""
        text = (request.user_request or "").strip()
        if not text:
            return None
        dt = request.decision_type

        # 1. Task classification
        if dt == DecisionType.TASK_CLASSIFICATION:
            if re.search(
                r"^(?:hi|hello|hey|greetings|good\s+(?:morning|afternoon|evening)|thanks|thank you|bye|goodbye)\b",
                text,
                re.I,
            ):
                return TaskClassification(TaskClass.CONVERSATION, 0.95, "Conversational greeting")
            if re.search(r"^(?:who|what) are you\b|^(?:how are you|what's up|how's it going)\b", text, re.I):
                return TaskClassification(TaskClass.CONVERSATION, 0.92, "General conversational question")
            if re.search(
                r"\.(?:py|js|ts|tsx|jsx|json|html|css|yaml|yml|sh|toml|sql|rs|go)\b|\b(?:def |function|class |import |refactor|debug|compile|pytest|npm test)\b",
                text,
                re.I,
            ):
                return TaskClassification(TaskClass.CODING, 0.90, "Code structure or file extension recognized")
            if re.search(r"\b(?:search|google|find out|look up|research|browse|latest news on)\b", text, re.I):
                return TaskClassification(TaskClass.RESEARCH, 0.88, "Information retrieval request")
            if re.search(
                r"\b(?:read file|write file|edit file|delete file|move file|copy file|list files|create folder)\b",
                text,
                re.I,
            ):
                return TaskClassification(TaskClass.SYSTEM_OPERATION, 0.90, "File or system operation")
            if re.search(r"\b(?:open browser|browse to|navigate to|click on|type into|login to)\b", text, re.I):
                return TaskClassification(TaskClass.WEB_BROWSING, 0.90, "Browser interaction request")
            if re.search(r"\b(?:and then|after that|first.*then|step 1|pipeline|workflow)\b", text, re.I):
                return TaskClassification(TaskClass.MULTI_STEP, 0.85, "Multi-step sequencing pattern")
            if len(text) < 150 and (
                "?" in text or text.lower().startswith(("what ", "who ", "how ", "why ", "calculate ", "tell me "))
            ):
                return TaskClassification(TaskClass.SIMPLE_QUERY, 0.88, "Short direct query")
            return None

        # 2. Complexity estimation
        elif dt == DecisionType.COMPLEXITY_ESTIMATION:
            if re.search(r"^(?:hi|hello|hey|greetings|thanks|thank you|bye)\b", text, re.I):
                return ComplexityAssessment(ComplexityLevel.TRIVIAL, 0.95, 1, 1, "Trivial greeting/chat")
            if (
                len(text) < 120
                and "?" in text
                and not re.search(r"\b(?:file|browser|terminal|run|search|code|refactor|test)\b", text, re.I)
            ):
                return ComplexityAssessment(ComplexityLevel.SIMPLE, 0.88, 1, 1, "Simple knowledge query without tools")
            if re.search(r"\b(?:and then|after that|step 1|workflow|refactor all|benchmark)\b", text, re.I) or (
                len(text) > 400 and re.search(r"\.(?:py|js|ts)\b", text, re.I)
            ):
                return ComplexityAssessment(ComplexityLevel.COMPLEX, 0.85, 4, 3, "Complex multi-step or code workflow")
            return None

        # 3. Model tier selection
        elif dt == DecisionType.MODEL_TIER_SELECTION:
            if re.search(r"\b(?:screenshot|screen|image|photo|visual|crop|locate button)\b", text, re.I):
                return ModelTierDecision(ModelTier.VISION, 0.95, "Vision model required for visual targets")
            if re.search(r"^(?:hi|hello|hey|thanks|thank you|bye)\b", text, re.I) or (
                len(text) < 100
                and "?" in text
                and not re.search(r"\b(?:code|refactor|file|browser|terminal)\b", text, re.I)
            ):
                return ModelTierDecision(ModelTier.QUICK, 0.90, "Fast, lightweight model suited for simple query")
            if re.search(
                r"\b(?:refactor|architect|benchmark|complex|multi-step|security audit|optimize)\b", text, re.I
            ):
                return ModelTierDecision(ModelTier.STRONG, 0.85, "High-capability model required for complex task")
            return None

        # 4. Capability routing
        elif dt == DecisionType.CAPABILITY_ROUTING:
            if re.search(r"\b(?:screenshot|screen|image|photo|picture)\b", text, re.I):
                return CapabilityRouting(
                    Cap.VISION, (), (), needs_tool_use=True, needs_vision=True, reasoning="Vision capability required"
                )
            if re.search(r"^(?:hi|hello|hey|thanks|who are you)\b", text, re.I):
                return CapabilityRouting(
                    Cap.NONE,
                    (),
                    (),
                    needs_tool_use=False,
                    needs_vision=False,
                    reasoning="Conversational, no tools required",
                )
            if re.search(r"\b(?:search|file|read|write|browser|terminal|run|edit|delete|open|launch|click|type|press|app|spotify|music)\b", text, re.I):
                return CapabilityRouting(
                    Cap.NONE, (), (), needs_tool_use=True, needs_vision=False, reasoning="Requires tool use"
                )
            return None

        # 5. Tool family selection
        elif dt == DecisionType.TOOL_FAMILY_SELECTION:
            if re.search(r"^(?:hi|hello|hey|thanks|who are you)\b", text, re.I):
                return ToolFamilyDecision(ToolFamily.NONE, (), 0.95, "No tool family needed for conversational query")
            if re.search(r"\b(?:file|files|folder|path|read file|write file|edit file|delete file)\b", text, re.I):
                return ToolFamilyDecision(ToolFamily.FILESYSTEM, (), 0.90, "Filesystem family identified from keywords")
            if re.search(
                r"\b(?:app|apps|application|open|launch|run|terminal|command|process|click|type|press|screen|desktop|laptop|lap|mac|spotify|music|textedit|slack|finder)\b",
                text,
                re.I,
            ):
                return ToolFamilyDecision(
                    ToolFamily.COMPUTER, (), 0.90, "Computer/desktop family identified from keywords"
                )
            if re.search(r"\b(?:browser|navigate|webpage|url|http|html)\b", text, re.I):
                return ToolFamilyDecision(ToolFamily.BROWSER, (), 0.90, "Browser family identified from keywords")
            if re.search(r"\b(?:search|google|lookup|fetch|research)\b", text, re.I):
                return ToolFamilyDecision(ToolFamily.WEB, (), 0.90, "Web family identified from keywords")
            if re.search(r"\b(?:remember|memory|note|notes|recall)\b", text, re.I):
                return ToolFamilyDecision(ToolFamily.MEMORY, (), 0.90, "Memory/notes family identified")
            return None


        return None

    async def decide(self, request: System1Request) -> System1Decision:
        """Make a System 1 decision based on the request.

        Applies deterministic rules first. Uses Laya only for uncertain
        classifications. Routes simple tasks to lightweight models, complex
        tasks to stronger models, and falls back safely when confidence is low.
        """
        decision_type = request.decision_type
        self._decision_counts[decision_type] += 1

        # 1. Fast, free, deterministic rule pass
        deterministic = self._deterministic_decide(request)
        if deterministic is not None and getattr(deterministic, "confidence", 0.0) >= 0.80:
            if self._on_decision:
                self._on_decision(decision_type, deterministic)
            return deterministic

        # 2. Use Laya only for uncertain classifications when available and enabled
        enabled = self._laya_enabled() if callable(self._laya_enabled) else self._laya_enabled
        if self.laya_available and self._should_use_laya(decision_type) and enabled is not False:
            try:
                self._laya_usage_counts[decision_type] += 1
                decision = await self._make_laya_decision(request)
                if decision is not None and getattr(decision, "confidence", 0.0) >= 0.65:
                    if self._on_decision:
                        self._on_decision(decision_type, decision)
                    return decision
            except Exception as e:
                log.warning(f"Laya decision failed for {decision_type}: {e}")

        # 3. Custom fallback deciders if registered
        if decision_type in self._fallback_deciders:
            self._fallback_usage_counts[decision_type] += 1
            decider = self._fallback_deciders[decision_type]
            decision = decider(request)
            if self._on_decision:
                self._on_decision(decision_type, decision)
            return decision

        # 4. Safe fallback: deterministic suggestion if any, or safe default
        default_decision = deterministic or self._make_default_decision(request)
        if self._on_decision:
            self._on_decision(decision_type, default_decision)
        return default_decision

    def _should_use_laya(self, decision_type: DecisionType) -> bool:
        """Determine whether Laya should be used for this decision type."""
        # Laya is particularly good at these decision types
        laya_friendly = {
            DecisionType.TASK_CLASSIFICATION,
            DecisionType.COMPLEXITY_ESTIMATION,
            DecisionType.MODEL_TIER_SELECTION,
            DecisionType.CAPABILITY_ROUTING,
            DecisionType.TOOL_FAMILY_SELECTION,
            DecisionType.MEMORY_RELEVANCE,
            DecisionType.VERIFICATION_NECESSITY,
        }
        return decision_type in laya_friendly

    async def _make_laya_decision(self, request: System1Request) -> System1Decision | None:
        """Make a decision using Laya."""
        if not self._laya_decider:
            return None

        # Convert the request to a Laya-compatible format
        laya_request = self._convert_to_laya_request(request)

        try:
            # Use Laya to make the decision
            answer = await self._laya_decider.decide(laya_request)
            if answer and answer.choice:
                return self._convert_from_laya_answer(request.decision_type, answer)
        except Exception as e:
            log.warning(f"Laya decision making failed: {e}")

        return None

    def _convert_to_laya_request(self, request: System1Request) -> Request:
        """Convert a System1Request to a Laya Request."""
        # Map decision types to Laya kinds
        kind_mapping = {
            DecisionType.TASK_CLASSIFICATION: Kind.ROUTE,
            DecisionType.COMPLEXITY_ESTIMATION: Kind.ROUTE,
            DecisionType.MODEL_TIER_SELECTION: Kind.ROUTE,
            DecisionType.CAPABILITY_ROUTING: Kind.ROUTE,
            DecisionType.TOOL_FAMILY_SELECTION: Kind.TOOLS,
            DecisionType.DELEGATION_CHOICE: Kind.ROUTE,
            DecisionType.URGENCY_ASSESSMENT: Kind.ROUTE,
            DecisionType.WAKE_SLEEP_DECISION: Kind.ROUTE,
            DecisionType.RETRY_DECISION: Kind.LOOP,
            DecisionType.MEMORY_RELEVANCE: Kind.ROUTE,
            DecisionType.VERIFICATION_NECESSITY: Kind.PLAN,
        }

        kind = kind_mapping.get(request.decision_type, Kind.ROUTE)

        enum_options: dict[DecisionType, tuple[Option, ...]] = {
            DecisionType.TASK_CLASSIFICATION: tuple(Option(v.value, v.value) for v in TaskClass),
            DecisionType.COMPLEXITY_ESTIMATION: tuple(Option(v.value, v.value) for v in ComplexityLevel),
            DecisionType.MODEL_TIER_SELECTION: tuple(Option(v.value, v.value) for v in ModelTier),
            DecisionType.CAPABILITY_ROUTING: tuple(
                Option((v.name or "").lower(), (v.name or "").lower()) for v in Cap if v != Cap.NONE
            ),
            DecisionType.TOOL_FAMILY_SELECTION: tuple(Option(v.value, v.value) for v in ToolFamily),
            DecisionType.VERIFICATION_NECESSITY: tuple(Option(v.value, v.value) for v in VerificationLevel),
        }
        supplied = (
            request.available_models
            if request.decision_type is DecisionType.MODEL_TIER_SELECTION
            else request.available_tools
        )
        options = (
            tuple(Option(value, value) for value in supplied)
            if supplied
            else enum_options.get(request.decision_type, ())
        )
        return Request(
            kind=kind,
            task_id=request.task_id or "",
            options=options,
            context=Context(
                text=request.user_request or "",
            ),
            tokens_left=512,
            timeout_s=0.1,
        )

    def _convert_from_laya_answer(self, decision_type: DecisionType, answer: Answer) -> System1Decision:
        """Convert a Laya Answer to a System1Decision."""

        def enum_choice(enum_type: Any) -> Any:
            value = (answer.choice or "").strip().casefold()
            for member in enum_type:
                if member.value.casefold() == value:
                    return member
            raise ValueError(f"Laya returned an invalid {decision_type.value} choice: {answer.choice!r}")

        if decision_type == DecisionType.TASK_CLASSIFICATION:
            task_class = enum_choice(TaskClass)
            return TaskClassification(
                task_class=task_class, confidence=answer.confidence or 0.7, reasoning="Laya classification"
            )

        elif decision_type == DecisionType.COMPLEXITY_ESTIMATION:
            level = enum_choice(ComplexityLevel)
            return ComplexityAssessment(
                level=level,
                confidence=answer.confidence or 0.7,
                estimated_steps=1 if level in (ComplexityLevel.TRIVIAL, ComplexityLevel.SIMPLE) else 3,
                estimated_model_calls=1 if level in (ComplexityLevel.TRIVIAL, ComplexityLevel.SIMPLE) else 2,
                reasoning="Laya complexity estimation",
            )

        elif decision_type == DecisionType.MODEL_TIER_SELECTION:
            tier = enum_choice(ModelTier)
            return ModelTierDecision(tier=tier, confidence=answer.confidence or 0.7, reasoning="Laya tier selection")

        elif decision_type == DecisionType.CAPABILITY_ROUTING:
            value = (answer.choice or "").strip().casefold()
            by_name = {cap.name.casefold(): cap for cap in Cap if cap != Cap.NONE and cap.name}
            primary = by_name.get(value)
            if primary is None:
                raise ValueError(f"Laya returned an invalid {decision_type.value} choice: {answer.choice!r}")
            return CapabilityRouting(
                primary_capability=primary,
                secondary_capabilities=(),
                required_model_capabilities=(primary,),
                needs_tool_use=primary == Cap.TOOLS,
                needs_vision=primary == Cap.VISION,
                reasoning="Laya capability routing",
            )

        elif decision_type == DecisionType.TOOL_FAMILY_SELECTION:
            family = enum_choice(ToolFamily)
            return ToolFamilyDecision(
                primary_family=family,
                secondary_families=(),
                confidence=answer.confidence or 0.7,
                reasoning="Laya tool-family selection",
            )

        # Add more conversions for other decision types...

        elif decision_type == DecisionType.VERIFICATION_NECESSITY:
            verification_level = enum_choice(VerificationLevel)
            return VerificationDecision(
                level=verification_level, confidence=answer.confidence or 0.7, reasoning="Laya verification decision"
            )

        # Default fallback
        return self._make_default_decision(System1Request(decision_type=decision_type))

    def _make_default_decision(self, request: System1Request) -> System1Decision:
        """Make a default decision when no other method is available."""
        decision_type = request.decision_type

        if decision_type == DecisionType.TASK_CLASSIFICATION:
            return TaskClassification(
                task_class=TaskClass.CONVERSATION, confidence=0.5, reasoning="Default classification"
            )

        elif decision_type == DecisionType.COMPLEXITY_ESTIMATION:
            return ComplexityAssessment(
                level=ComplexityLevel.MODERATE,
                confidence=0.5,
                estimated_steps=2,
                estimated_model_calls=1,
                reasoning="Default complexity assessment",
            )

        elif decision_type == DecisionType.MODEL_TIER_SELECTION:
            return ModelTierDecision(tier=ModelTier.STANDARD, confidence=0.5, reasoning="Default tier selection")

        elif decision_type == DecisionType.CAPABILITY_ROUTING:
            return CapabilityRouting(
                primary_capability=Cap.NONE,
                secondary_capabilities=(),
                required_model_capabilities=(),
                needs_tool_use=False,
                needs_vision=False,
                reasoning="Default capability routing",
            )

        elif decision_type == DecisionType.TOOL_FAMILY_SELECTION:
            return ToolFamilyDecision(
                primary_family=ToolFamily.NONE,
                secondary_families=(),
                confidence=0.5,
                reasoning="Default tool family selection",
            )

        elif decision_type == DecisionType.DELEGATION_CHOICE:
            return DelegationDecision(
                strategy=DelegationStrategy.NONE, confidence=0.5, reasoning="Default delegation decision"
            )

        elif decision_type == DecisionType.URGENCY_ASSESSMENT:
            return UrgencyAssessment(level=UrgencyLevel.NORMAL, confidence=0.5, reasoning="Default urgency assessment")

        elif decision_type == DecisionType.WAKE_SLEEP_DECISION:
            return WakeSleepDecision(
                decision=WakeDecision.STAY_ASLEEP,
                component="unknown",
                confidence=0.5,
                reasoning="Default wake/sleep decision",
            )

        elif decision_type == DecisionType.RETRY_DECISION:
            return RetryDecisionResult(
                decision=RetryDecision.NO_RETRY, confidence=0.5, reasoning="Default retry decision"
            )

        elif decision_type == DecisionType.MEMORY_RELEVANCE:
            return MemoryRelevance(
                relevant=False,
                confidence=0.5,
                relevant_memory_types=(),
                query_suggestions=(),
                reasoning="Default memory relevance",
            )

        elif decision_type == DecisionType.VERIFICATION_NECESSITY:
            return VerificationDecision(
                level=VerificationLevel.NONE, confidence=0.5, reasoning="Default verification decision"
            )

        else:
            # Unknown decision type - return a safe default
            return TaskClassification(
                task_class=TaskClass.CONVERSATION, confidence=0.1, reasoning="Unknown decision type"
            )

    def get_telemetry(self) -> dict[str, Any]:
        """Get telemetry about System 1 decision making."""
        return {
            "decision_counts": {dt.name: self._decision_counts[dt] for dt in DecisionType},
            "laya_usage_counts": {dt.name: self._laya_usage_counts[dt] for dt in DecisionType},
            "fallback_usage_counts": {dt.name: self._fallback_usage_counts[dt] for dt in DecisionType},
            "laya_available": self.laya_available,
        }

    async def assess_task(
        self, user_request: str, task_id: str | None = None
    ) -> tuple[TaskClassification, ComplexityAssessment]:
        """Assess a task for classification and complexity."""
        task_request = System1Request(
            decision_type=DecisionType.TASK_CLASSIFICATION,
            user_request=user_request,
            task_id=task_id,
        )

        complexity_request = System1Request(
            decision_type=DecisionType.COMPLEXITY_ESTIMATION,
            user_request=user_request,
            task_id=task_id,
        )

        # Run both decisions in parallel
        classification, complexity = await asyncio.gather(
            self.decide(task_request),
            self.decide(complexity_request),
        )

        return cast(TaskClassification, classification), cast(ComplexityAssessment, complexity)

    async def determine_routing(
        self,
        user_request: str,
        available_models: tuple[str, ...],
        available_tools: tuple[str, ...],
        task_id: str | None = None,
    ) -> tuple[ModelTierDecision, CapabilityRouting, ToolFamilyDecision]:
        """Determine the routing strategy for a task."""
        tier_request = System1Request(
            decision_type=DecisionType.MODEL_TIER_SELECTION,
            user_request=user_request,
            available_models=available_models,
            task_id=task_id,
        )

        capability_request = System1Request(
            decision_type=DecisionType.CAPABILITY_ROUTING,
            user_request=user_request,
            available_models=available_models,
            available_tools=available_tools,
            task_id=task_id,
        )

        tool_request = System1Request(
            decision_type=DecisionType.TOOL_FAMILY_SELECTION,
            user_request=user_request,
            available_tools=available_tools,
            task_id=task_id,
        )

        tier, capability, tool_family = await asyncio.gather(
            self.decide(tier_request),
            self.decide(capability_request),
            self.decide(tool_request),
        )

        return cast(ModelTierDecision, tier), cast(CapabilityRouting, capability), cast(ToolFamilyDecision, tool_family)

    async def assess_verification(
        self, task_id: str, user_request: str, task_complexity: float = 0.5, task_class: TaskClass | None = None
    ) -> VerificationDecision:
        """Assess whether verification is needed for a task."""
        request = System1Request(
            decision_type=DecisionType.VERIFICATION_NECESSITY,
            user_request=user_request,
            task_id=task_id,
            metadata={
                "task_complexity": task_complexity,
                "task_class": task_class.name if task_class else "unknown",
            },
        )

        decision = await self.decide(request)
        if isinstance(decision, VerificationDecision):
            return decision
        else:
            # Fallback to default
            return VerificationDecision(
                level=VerificationLevel.NONE, confidence=0.5, reasoning="Fallback verification decision"
            )

    async def assess_memory_relevance(
        self, user_request: str, memory_types: tuple[str, ...], task_id: str | None = None
    ) -> MemoryRelevance:
        """Assess memory relevance for a task."""
        request = System1Request(
            decision_type=DecisionType.MEMORY_RELEVANCE,
            user_request=user_request,
            task_id=task_id,
            metadata={
                "available_memory_types": memory_types,
            },
        )

        decision = await self.decide(request)
        if isinstance(decision, MemoryRelevance):
            return decision
        else:
            return MemoryRelevance(
                relevant=False,
                confidence=0.5,
                relevant_memory_types=(),
                query_suggestions=(),
                reasoning="Fallback memory relevance",
            )
