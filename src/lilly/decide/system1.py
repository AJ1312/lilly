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
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from lilly.domain.caps import Cap
from lilly.domain.decisions import Context, Kind, Request, Answer
from lilly.domain.labels import Label
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
    RESEARCH = "research"           # Information gathering, web search, analysis
    CODING = "coding"               # Code generation, debugging, review
    DATA_ANALYSIS = "data_analysis" # Data processing, transformation, visualization
    DOCUMENTATION = "documentation" # Writing, editing, summarizing text
    SYSTEM_OPERATION = "system_operation"  # File operations, process management
    WEB_BROWSING = "web_browsing"   # Web navigation, extraction, interaction
    MULTI_STEP = "multi_step"       # Complex tasks requiring multiple steps
    SIMPLE_QUERY = "simple_query"   # Direct questions with simple answers
    CONVERSATION = "conversation"   # General conversation


class ComplexityLevel(Enum):
    """Estimated complexity of a task."""
    TRIVIAL = "trivial"      # Can be answered from general knowledge
    SIMPLE = "simple"        # Requires one model call, no tools
    MODERATE = "moderate"    # May require tools or multiple steps
    COMPLEX = "complex"      # Requires planning, multiple steps, tool usage
    EXPERT = "expert"        # Requires advanced reasoning, potentially delegation


class ModelTier(Enum):
    """Model tiers for routing decisions."""
    QUICK = "quick"          # Fast, cheap models for simple tasks
    STANDARD = "standard"    # Default models for most tasks
    STRONG = "strong"        # High-capability models for complex tasks
    VISION = "vision"        # Vision-capable models
    SPECIALIZED = "specialized"  # Specialized models for specific domains


class ToolFamily(Enum):
    """Tool capability families."""
    NONE = "none"            # No tools needed
    FILESYSTEM = "filesystem"  # File operations
    WEB = "web"              # Web search, browsing
    COMPUTER = "computer"    # Computer control, processes
    DATA = "data"            # Data processing, analysis
    MEMORY = "memory"        # Memory operations
    MCP = "mcp"              # MCP server tools
    BROWSER = "browser"      # Browser automation
    GIT = "git"              # Git operations
    SYSTEM = "system"        # System-level operations


class DelegationStrategy(Enum):
    """Strategies for task delegation."""
    NONE = "none"            # Handle task directly
    SINGLE_AGENT = "single_agent"  # Delegate to one specialist agent
    MULTI_AGENT = "multi_agent"  # Split among multiple specialist agents
    SUPERVISED = "supervised"    # Use supervisor with worker agents
    PARALLEL = "parallel"    # Parallel execution


class UrgencyLevel(Enum):
    """Urgency levels for tasks."""
    LOW = "low"              # Can wait, background processing
    NORMAL = "normal"        # Standard priority
    HIGH = "high"            # Should be prioritized
    IMMEDIATE = "immediate"  # Requires immediate attention


class WakeDecision(Enum):
    """Decisions about waking sleeping components."""
    STAY_ASLEEP = "stay_asleep"  # Don't wake, not needed
    WAKE = "wake"            # Wake the component
    CONDITIONAL = "conditional"  # Wake only if certain conditions are met


class RetryDecision(Enum):
    """Decisions about retrying failed operations."""
    NO_RETRY = "no_retry"      # Do not retry
    IMMEDIATE_RETRY = "immediate_retry"  # Retry immediately
    DELAYED_RETRY = "delayed_retry"    # Retry after delay
    FALLBACK = "fallback"      # Try a different approach


class VerificationLevel(Enum):
    """Levels of verification needed."""
    NONE = "none"            # No verification needed
    LIGHT = "light"           # Quick sanity check
    STANDARD = "standard"    # Standard verification
    THOROUGH = "thorough"    # Comprehensive verification with multiple models


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
            TaskClass.MULTI_STEP
        }
    
    @property
    def needs_complex_reasoning(self) -> bool:
        """Whether this task requires complex reasoning."""
        return self.task_class in {
            TaskClass.CODING,
            TaskClass.DATA_ANALYSIS,
            TaskClass.MULTI_STEP,
            TaskClass.EXPERT
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
    TaskClassification |
    ComplexityAssessment |
    ModelTierDecision |
    CapabilityRouting |
    ToolFamilyDecision |
    DelegationDecision |
    UrgencyAssessment |
    WakeSleepDecision |
    RetryDecisionResult |
    MemoryRelevance |
    VerificationDecision
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
        fallback_deciders: dict[str, Callable[[System1Request], System1Decision]] | None = None,
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

    def set_laya_decider(self, laya_decider: Any) -> None:
        """Set the Laya decider instance."""
        self._laya_decider = laya_decider
        log.info("Laya decider set")

    def set_engine_settings(self, engine_settings: Callable[[], EngineSettings] | EngineSettings) -> None:
        """Set the engine settings provider."""
        self._engine_settings = engine_settings

    def set_laya_enabled(self, enabled: Callable[[], bool] | bool) -> None:
        """Update the owner's Laya switch without rebuilding the engine."""
        self._laya_enabled = enabled

    async def decide(self, request: System1Request) -> System1Decision:
        """Make a System 1 decision based on the request.
        
        This method routes the request to the appropriate decision maker,
        preferring Laya when available, with fallback to deterministic logic.
        """
        decision_type = request.decision_type
        self._decision_counts[decision_type] += 1
        
        # Try Laya first if available and appropriate for this decision type
        enabled = self._laya_enabled() if callable(self._laya_enabled) else self._laya_enabled
        if (self.laya_available and self._should_use_laya(decision_type) and enabled is not False):
            try:
                self._laya_usage_counts[decision_type] += 1
                decision = await self._make_laya_decision(request)
                if decision is not None:
                    if self._on_decision:
                        self._on_decision(decision_type, decision)
                    return decision
            except Exception as e:
                log.warning(f"Laya decision failed for {decision_type}: {e}")
        
        # Fallback to deterministic deciders
        if decision_type in self._fallback_deciders:
            self._fallback_usage_counts[decision_type] += 1
            decider = self._fallback_deciders[decision_type]
            decision = decider(request)
            if self._on_decision:
                self._on_decision(decision_type, decision)
            return decision
        
        # Default fallback decisions
        default_decision = self._make_default_decision(request)
        if self._on_decision:
            self._on_decision(decision_type, default_decision)
        return default_decision

    def _should_use_laya(self, decision_type: DecisionType) -> bool:
        """Determine whether Laya should be used for this decision type."""
        # Laya is particularly good at these decision types
        laya_friendly = {
            DecisionType.TASK_CLASSIFICATION,
            DecisionType.COMPLEXITY_ESTIMATION,
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
        
        return Request(
            kind=kind,
            task_id=request.task_id or "",
            options=(),  # Will be populated based on decision type
            context=Context(
                text=request.user_request or "",
                goal=request.user_request or "",
                history=[{"role": "user", "content": request.user_request or ""}] if request.user_request else [],
            ),
            temperature=0.1,  # Low temperature for deterministic-like decisions
            max_tokens=512,
        )

    def _convert_from_laya_answer(self, decision_type: DecisionType, answer: Answer) -> System1Decision:
        """Convert a Laya Answer to a System1Decision."""
        # This is a simplified conversion - in practice, this would be more sophisticated
        if decision_type == DecisionType.TASK_CLASSIFICATION:
            # Map Laya response to task classification
            task_class_map = {
                "research": TaskClass.RESEARCH,
                "coding": TaskClass.CODING,
                "data": TaskClass.DATA_ANALYSIS,
                "document": TaskClass.DOCUMENTATION,
                "system": TaskClass.SYSTEM_OPERATION,
                "web": TaskClass.WEB_BROWSING,
                "multi": TaskClass.MULTI_STEP,
                "simple": TaskClass.SIMPLE_QUERY,
                "conversation": TaskClass.CONVERSATION,
            }
            
            response_text = (answer.choice or "").lower()
            task_class = TaskClass.CONVERSATION  # Default
            for key, cls in task_class_map.items():
                if key in response_text:
                    task_class = cls
                    break
            
            return TaskClassification(
                task_class=task_class,
                confidence=answer.confidence or 0.7,
                reasoning=answer.reasoning or "Laya classification"
            )
        
        elif decision_type == DecisionType.COMPLEXITY_ESTIMATION:
            # Map response to complexity level
            if "complex" in (answer.choice or "").lower():
                level = ComplexityLevel.COMPLEX
            elif "expert" in (answer.choice or "").lower():
                level = ComplexityLevel.EXPERT
            elif "moderate" in (answer.choice or "").lower():
                level = ComplexityLevel.MODERATE
            elif "simple" in (answer.choice or "").lower():
                level = ComplexityLevel.SIMPLE
            else:
                level = ComplexityLevel.TRIVIAL
            
            return ComplexityAssessment(
                level=level,
                confidence=answer.confidence or 0.7,
                estimated_steps=1 if level in (ComplexityLevel.TRIVIAL, ComplexityLevel.SIMPLE) else 3,
                estimated_model_calls=1 if level in (ComplexityLevel.TRIVIAL, ComplexityLevel.SIMPLE) else 2,
                reasoning=answer.reasoning or "Laya complexity estimation"
            )
        
        elif decision_type == DecisionType.MODEL_TIER_SELECTION:
            if "strong" in (answer.choice or "").lower():
                tier = ModelTier.STRONG
            elif "vision" in (answer.choice or "").lower():
                tier = ModelTier.VISION
            elif "quick" in (answer.choice or "").lower():
                tier = ModelTier.QUICK
            else:
                tier = ModelTier.STANDARD
            
            return ModelTierDecision(
                tier=tier,
                confidence=answer.confidence or 0.7,
                reasoning=answer.reasoning or "Laya tier selection"
            )
        
        # Add more conversions for other decision types...
        
        elif decision_type == DecisionType.VERIFICATION_NECESSITY:
            if "thorough" in (answer.choice or "").lower():
                level = VerificationLevel.THOROUGH
            elif "standard" in (answer.choice or "").lower():
                level = VerificationLevel.STANDARD
            elif "light" in (answer.choice or "").lower():
                level = VerificationLevel.LIGHT
            else:
                level = VerificationLevel.NONE
            
            return VerificationDecision(
                level=level,
                confidence=answer.confidence or 0.7,
                reasoning=answer.reasoning or "Laya verification decision"
            )
        
        # Default fallback
        return self._make_default_decision(System1Request(decision_type=decision_type))

    def _make_default_decision(self, request: System1Request) -> System1Decision:
        """Make a default decision when no other method is available."""
        decision_type = request.decision_type
        
        if decision_type == DecisionType.TASK_CLASSIFICATION:
            return TaskClassification(
                task_class=TaskClass.CONVERSATION,
                confidence=0.5,
                reasoning="Default classification"
            )
        
        elif decision_type == DecisionType.COMPLEXITY_ESTIMATION:
            return ComplexityAssessment(
                level=ComplexityLevel.MODERATE,
                confidence=0.5,
                estimated_steps=2,
                estimated_model_calls=1,
                reasoning="Default complexity assessment"
            )
        
        elif decision_type == DecisionType.MODEL_TIER_SELECTION:
            return ModelTierDecision(
                tier=ModelTier.STANDARD,
                confidence=0.5,
                reasoning="Default tier selection"
            )
        
        elif decision_type == DecisionType.CAPABILITY_ROUTING:
            return CapabilityRouting(
                primary_capability=Cap.NONE,
                secondary_capabilities=(),
                required_model_capabilities=(),
                needs_tool_use=False,
                needs_vision=False,
                reasoning="Default capability routing"
            )
        
        elif decision_type == DecisionType.TOOL_FAMILY_SELECTION:
            return ToolFamilyDecision(
                primary_family=ToolFamily.NONE,
                secondary_families=(),
                confidence=0.5,
                reasoning="Default tool family selection"
            )
        
        elif decision_type == DecisionType.DELEGATION_CHOICE:
            return DelegationDecision(
                strategy=DelegationStrategy.NONE,
                confidence=0.5,
                reasoning="Default delegation decision"
            )
        
        elif decision_type == DecisionType.URGENCY_ASSESSMENT:
            return UrgencyAssessment(
                level=UrgencyLevel.NORMAL,
                confidence=0.5,
                reasoning="Default urgency assessment"
            )
        
        elif decision_type == DecisionType.WAKE_SLEEP_DECISION:
            return WakeSleepDecision(
                decision=WakeDecision.STAY_ASLEEP,
                component="unknown",
                confidence=0.5,
                reasoning="Default wake/sleep decision"
            )
        
        elif decision_type == DecisionType.RETRY_DECISION:
            return RetryDecisionResult(
                decision=RetryDecision.NO_RETRY,
                confidence=0.5,
                reasoning="Default retry decision"
            )
        
        elif decision_type == DecisionType.MEMORY_RELEVANCE:
            return MemoryRelevance(
                relevant=False,
                confidence=0.5,
                relevant_memory_types=(),
                query_suggestions=(),
                reasoning="Default memory relevance"
            )
        
        elif decision_type == DecisionType.VERIFICATION_NECESSITY:
            return VerificationDecision(
                level=VerificationLevel.NONE,
                confidence=0.5,
                reasoning="Default verification decision"
            )
        
        else:
            # Unknown decision type - return a safe default
            return TaskClassification(
                task_class=TaskClass.CONVERSATION,
                confidence=0.1,
                reasoning="Unknown decision type"
            )

    def get_telemetry(self) -> dict[str, Any]:
        """Get telemetry about System 1 decision making."""
        return {
            "decision_counts": {dt.name: self._decision_counts[dt] for dt in DecisionType},
            "laya_usage_counts": {dt.name: self._laya_usage_counts[dt] for dt in DecisionType},
            "fallback_usage_counts": {dt.name: self._fallback_usage_counts[dt] for dt in DecisionType},
            "laya_available": self.laya_available,
        }

    async def assess_task(self, user_request: str, task_id: str | None = None) -> tuple[TaskClassification, ComplexityAssessment]:
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
        
        return classification, complexity

    async def determine_routing(self, user_request: str, available_models: tuple[str, ...], 
                               available_tools: tuple[str, ...], task_id: str | None = None) -> tuple[ModelTierDecision, CapabilityRouting, ToolFamilyDecision]:
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
        
        return tier, capability, tool_family

    async def assess_verification(self, task_id: str, user_request: str, 
                                  task_complexity: float = 0.5, task_class: TaskClass | None = None) -> VerificationDecision:
        """Assess whether verification is needed for a task."""
        request = System1Request(
            decision_type=DecisionType.VERIFICATION_NECESSITY,
            user_request=user_request,
            task_id=task_id,
            metadata={
                "task_complexity": task_complexity,
                "task_class": task_class.name if task_class else "unknown",
            }
        )
        
        decision = await self.decide(request)
        if isinstance(decision, VerificationDecision):
            return decision
        else:
            # Fallback to default
            return VerificationDecision(
                level=VerificationLevel.NONE,
                confidence=0.5,
                reasoning="Fallback verification decision"
            )

    async def assess_memory_relevance(self, user_request: str, memory_types: tuple[str, ...],
                                       task_id: str | None = None) -> MemoryRelevance:
        """Assess memory relevance for a task."""
        request = System1Request(
            decision_type=DecisionType.MEMORY_RELEVANCE,
            user_request=user_request,
            task_id=task_id,
            metadata={
                "available_memory_types": memory_types,
            }
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
                reasoning="Fallback memory relevance"
            )
