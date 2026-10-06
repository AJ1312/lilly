"""ModelBroker: A unified interface for intelligent model selection and routing.

The ModelBroker is the single logical inference layer that abstracts heterogeneous
providers, models, and credentials. It provides intelligent routing based on:
- Task requirements and capabilities needed
- Model capability profiles
- Current provider health and availability
- Quota and rate limit status
- Cost and latency considerations
- Historical success and failure patterns

This component unifies the existing ProviderPool and ModelRouter functionality
while adding enhanced decision-making capabilities.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx

from lilly.core.capacity import CallProfile, CapacityManager
from lilly.core.pool import ModelEntry, ProviderPool, build_pool
from lilly.domain.caps import Cap
from lilly.domain.clock import Clock
from lilly.domain.errors import NoModelAvailable, ProviderError, QuotaExhausted, RateLimited
from lilly.domain.grants import GrantStore, label_access
from lilly.domain.labels import Label, Mode
from lilly.domain.ports import (
    Completed,
    CompletionRequest,
    CompletionResult,
    KeyStore,
    Message,
    Provider,
)
from lilly.domain.settings import Settings
from lilly.providers.factory import build_provider
from lilly.providers.local_gate import LocalGate
from lilly.providers.ollama import OllamaStatus, probe
from lilly.store.db import Database
from lilly.store.ledger import ModelCallRecord, record_model_call, save_usage

log = logging.getLogger("lilly.model_broker")


class RoutingDecision(Enum):
    """The type of routing decision made by the broker."""
    OPTIMAL = "optimal"           # Best model for the task
    FALLBACK = "fallback"         # Primary unavailable, using fallback
    FORCED = "forced"             # Pinned model or explicit override
    QUOTA_EXHAUSTED = "quota_exhausted"  # All models exhausted quotas
    NO_AVAILABLE = "no_available" # No models available for this task
    NEEDS_PERMISSION = "needs_permission"  # Requires user permission for sensitive data


@dataclass(frozen=True, slots=True)
class ModelCapabilityProfile:
    """Capability profile for a model, supporting intelligent routing decisions.
    
    These profiles can be user-configured and allow the broker to make
    informed decisions about which model is best suited for a given task.
    """
    # Core capabilities (0.0-1.0 scale)
    reasoning_strength: float = 0.7
    coding_strength: float = 0.5
    vision: float = 0.0
    tool_calling: float = 0.8
    structured_output: float = 0.6
    
    # Performance characteristics
    context_window: int = 32768
    expected_latency: float = 1.0  # seconds per response
    cost_tier: str = "free"  # "free", "low", "medium", "high"
    local: bool = False
    
    # Suitability flags
    suitable_for_complex_tasks: bool = True
    suitable_for_simple_tasks: bool = True
    suitable_for_tool_use: bool = True
    suitable_for_analysis: bool = True
    
    def can_handle_capability(self, required_cap: Cap) -> bool:
        """Check if this model can handle the required capability."""
        return ModelBroker._can_handle_capability(self, required_cap)


@dataclass(frozen=True, slots=True)
class RoutingResult:
    """The result of a routing decision."""
    model_entry: ModelEntry | None
    decision: RoutingDecision
    reason: str
    candidates_tried: tuple[str, ...] = ()
    grantable_models: tuple[str, ...] = ()  # Models that could work with user permission
    latency_estimate: float | None = None
    cost_estimate: str | None = None
    
    @property
    def model_name(self) -> str | None:
        return self.model_entry.name if self.model_entry else None


@dataclass(frozen=True, slots=True)
class ModelHealthStatus:
    """Current health status of a model."""
    available: bool
    last_error: str | None
    circuit_breaker_state: str
    rate_limited: bool
    quota_exhausted: bool
    inflight_requests: int
    last_successful_call: float | None
    total_calls_today: int
    total_tokens_in_today: int
    total_tokens_out_today: int


@dataclass(frozen=True, slots=True)
class BrokerState:
    """Current state snapshot of the broker for observability."""
    available_models: tuple[str, ...]
    enabled_models: tuple[str, ...]
    healthy_models: tuple[str, ...]
    current_routing_table: dict[str, RoutingResult]
    health_status: dict[str, ModelHealthStatus]
    total_calls_today: int
    total_tokens_in_today: int
    total_tokens_out_today: int


class ModelBroker:
    """The unified model broker that handles all model selection and routing.
    
    This class provides a clean interface for model completion while handling:
    - Model capability matching
    - Provider health and availability
    - Quota and rate limiting
    - Circuit breaker management
    - Intelligent routing based on task requirements
    - Fallback and retry logic
    - User permission management
    - Observability and telemetry
    """

    supports_system1_routing = True
    
    def __init__(
        self,
        settings: Settings,
        keys: KeyStore,
        client: httpx.AsyncClient,
        db: Database,
        grants: GrantStore,
        local_client: httpx.AsyncClient | None = None,
        clock: Clock = time.monotonic,
        sleep_fn: Callable[[float], Any] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        on_thought: Callable[[str], None] | None = None,
        capability_profiles: dict[str, ModelCapabilityProfile] | None = None,
    ) -> None:
        self._keys = keys
        self._client = client
        self._local_client = local_client or client
        self._db = db
        self._clock = clock
        self._sleep_fn = sleep_fn
        self._on_event = on_event
        self._on_thought = on_thought
        self.grants = grants
        
        # Initialize the provider pool
        self.pool: ProviderPool = build_pool(settings, clock=clock)
        self._settings = settings
        
        # Local model gate
        self._gate = LocalGate()
        
        # Provider instances
        self._providers: dict[str, Provider] = {}
        
        # Track which keys are present
        self._key_present: set[str] = set()
        
        # Capability profiles (can be configured per model)
        self._capability_profiles: dict[str, ModelCapabilityProfile] = capability_profiles or {}
        
        # Initialize providers
        self._build_providers(settings)
        
        # Capacity manager for rate limiting and quotas
        self.capacity = CapacityManager(
            self.pool,
            lambda: self._settings.capacity,
            clock=self._clock,
            has_key=self.has_key,
            on_event=self._on_event,
            on_thought=self._on_thought,
            sleep_fn=self._sleep_fn,
        )
        
        # Routing history for observability
        self._routing_history: dict[str, RoutingResult] = {}
        
        # Telemetry
        self._total_calls = 0
        self._total_tokens_in = 0
        self._total_tokens_out = 0
        
        log.info(f"ModelBroker initialized with {len(self.pool.entries)} models")

    def _build_providers(self, settings: Settings) -> None:
        """Build provider instances for all configured models."""
        self._providers = {
            s.name: build_provider(
                s,
                self._client,
                self._keys,
                self._local_client,
                self._gate,
                lambda: self._settings.limits.local_unload_s,
            )
            for s in settings.models
        }

    async def start(self) -> None:
        """Start the broker and initialize all systems."""
        await self.configure(self._settings)
        usage = self._load_usage()
        for e in self.pool.entries:
            if e.name in usage:
                day, count, tokens = usage[e.name]
                if e.daily is not None:
                    e.daily.restore(day, count)
                if e.daily_tokens is not None:
                    e.daily_tokens.restore(day, tokens)
        
        log.info("ModelBroker started")

    async def configure(self, settings: Settings) -> None:
        """Apply new settings to the broker."""
        self._settings = settings
        self.pool = build_pool(settings, self.pool, clock=self._clock)
        self.capacity.pool = self.pool
        self._build_providers(settings)
        await self.refresh_keys()

    async def refresh_keys(self) -> None:
        """Refresh the set of available keys."""
        refs = {s.key_ref or s.provider for s in self._settings.models if not s.local}
        present = await asyncio.to_thread(lambda: {r for r in refs if self._keys.get(r) is not None})
        self._key_present = present

    def has_key(self, entry: ModelEntry) -> bool:
        """Check if a key is available for the given model entry."""
        return entry.spec.local or (entry.spec.key_ref or entry.spec.provider) in self._key_present

    def _load_usage(self) -> dict[str, tuple[int, int, int]]:
        """Load usage data from the database."""
        try:
            from lilly.store.ledger import load_usage
            return load_usage(self._db.reader)
        except Exception:
            return {}

    @staticmethod
    def _can_handle_capability(profile: ModelCapabilityProfile, required_cap: Cap) -> bool:
        """Check if a profile can handle the required capability."""
        if required_cap == Cap.NONE:
            return True
        if required_cap == Cap.TOOLS and profile.tool_calling >= 0.5:
            return True
        if required_cap == Cap.JSON and profile.structured_output >= 0.7:
            return True
        if required_cap == Cap.LONG_CONTEXT and profile.context_window >= 32768:
            return True
        if required_cap == Cap.VISION and profile.vision >= 0.7:
            return True
        return False

    def _get_capability_profile(self, model_name: str) -> ModelCapabilityProfile:
        """Get the capability profile for a model, with defaults for unknown models."""
        if model_name in self._capability_profiles:
            return self._capability_profiles[model_name]
        
        # Try to find the model spec and infer capabilities
        entry = self.pool.get(model_name)
        if entry:
            spec = entry.spec
            return ModelCapabilityProfile(
                reasoning_strength=0.8 if spec.provider in ("mistral", "openrouter", "gemini", "openai") else 0.6,
                coding_strength=0.9 if spec.provider in ("mistral", "openrouter", "openai") else 0.5,
                vision=1.0 if (spec.caps & Cap.VISION) else 0.0,
                tool_calling=0.9 if spec.tools in ("native", "protocol") else 0.5,
                context_window=spec.max_context_tokens or 32768,
                local=spec.local,
                cost_tier="free" if spec.provider in ("mistral", "gemini") else "low",
            )
        
        # Default profile for unknown models
        return ModelCapabilityProfile()

    def _score_model_for_task(
        self, 
        entry: ModelEntry, 
        need: Cap = Cap.NONE, 
        task_complexity: float = 0.5, 
        requires_tools: bool = False,
        requires_vision: bool = False,
        cost_sensitivity: float = 0.5,
        model_tier: str | None = None,
        tool_family: str | None = None,
        verification: str | None = None,
    ) -> float:
        """Score a model's suitability for a given task (higher is better)."""
        if not entry.spec.enabled or not self.has_key(entry):
            return -1.0  # Not available
        
        if not entry.breaker.ready():
            return -0.5  # Circuit breaker tripped
        
        # Check capability match
        profile = self._get_capability_profile(entry.name)
        
        score = 0.0
        
        # Capability matching (most important)
        if need != Cap.NONE:
            if not self._can_handle_capability(profile, need):
                return -0.1  # Can't handle required capability
            score += 0.3  # Base score for capability match
        
        # Tool calling support
        if requires_tools:
            if profile.tool_calling >= 0.7:
                score += 0.2
            elif profile.tool_calling >= 0.4:
                score += 0.1
            else:
                score -= 0.1
        
        # Vision is an explicit capability, never a tool-calling proxy.
        if requires_vision:
            if profile.vision >= 0.7:
                score += 0.1
            else:
                return -0.1

        if model_tier == "STRONG":
            score += profile.reasoning_strength * 0.2
        elif model_tier == "QUICK":
            score += (1.0 - profile.reasoning_strength) * 0.1
        elif model_tier == "VISION" and profile.vision < 0.7:
            return -0.1
        if verification == "THOROUGH":
            score += profile.reasoning_strength * 0.1
        if tool_family and tool_family != "NONE" and profile.tool_calling < 0.7:
            return -0.1
        
        # Complexity matching
        if task_complexity >= 0.8:  # High complexity
            if profile.reasoning_strength >= 0.8:
                score += 0.2
            else:
                score -= 0.1
        elif task_complexity <= 0.3:  # Low complexity
            if profile.reasoning_strength <= 0.6:  # Faster, cheaper models
                score += 0.15
        
        # Cost sensitivity
        if cost_sensitivity >= 0.7:  # User is cost-sensitive
            if profile.cost_tier == "free":
                score += 0.15
            elif profile.cost_tier == "low":
                score += 0.05
            else:
                score -= 0.1
        
        # Local models get a boost for privacy
        if entry.spec.local:
            score += 0.1
        
        # Availability and health
        if entry.inflight > 2:  # Busy
            score -= 0.05 * entry.inflight
        
        # Daily quota status
        if entry.daily and not entry.daily.would_allow():
            score -= 0.5
        
        # Rate limit status
        if entry.minute and not entry.minute.would_allow():
            score -= 0.3
            
        return score

    def get_available_models(self) -> list[str]:
        """Get list of all available model names."""
        return [e.name for e in self.pool.entries if e.spec.enabled and self.has_key(e)]

    def status(self) -> list[dict[str, object]]:
        """Return the provider-neutral model status used by the admin UI."""
        rows = self.pool.snapshot()
        for row, entry in zip(rows, self.pool.entries, strict=True):
            row.update(
                provider=entry.spec.provider,
                model_id=entry.spec.model_id,
                local=entry.spec.local,
                has_key=self.has_key(entry),
            )
        return rows

    def get_model_health_status(self, model_name: str) -> ModelHealthStatus | None:
        """Get the current health status for a specific model."""
        entry = self.pool.get(model_name)
        if entry is None:
            return None
            
        return ModelHealthStatus(
            available=entry.spec.enabled and self.has_key(entry) and entry.breaker.ready(),
            last_error=entry.last_error,
            circuit_breaker_state=entry.breaker.state,
            rate_limited=entry.minute is not None and not entry.minute.would_allow(),
            quota_exhausted=entry.daily is not None and not entry.daily.would_allow(),
            inflight_requests=entry.inflight,
            last_successful_call=None,  # TODO: Track this
            total_calls_today=entry.tokens[0] if len(entry.tokens) > 0 else 0,
            total_tokens_in_today=entry.tokens[1] if len(entry.tokens) > 1 else 0,
            total_tokens_out_today=entry.tokens[2] if len(entry.tokens) > 2 else 0,
        )

    def get_broker_state(self) -> BrokerState:
        """Get a snapshot of the current broker state for observability."""
        available = tuple(e.name for e in self.pool.entries if e.spec.enabled and self.has_key(e))
        enabled = tuple(e.name for e in self.pool.entries if e.spec.enabled)
        healthy = tuple(e.name for e in self.pool.entries
                      if e.spec.enabled and self.has_key(e) and e.breaker.ready())
        
        health_status = {
            e.name: status
            for e in self.pool.entries
            if e.name and (status := self.get_model_health_status(e.name)) is not None
        }
        
        return BrokerState(
            available_models=available,
            enabled_models=enabled,
            healthy_models=healthy,
            current_routing_table=dict(self._routing_history),
            health_status=health_status,
            total_calls_today=self._total_calls,
            total_tokens_in_today=self._total_tokens_in,
            total_tokens_out_today=self._total_tokens_out,
        )

    async def select_model(
        self,
        need: Cap = Cap.NONE,
        label: Label = Label.PUBLIC,
        *,
        pin: str | None = None,
        grants: GrantStore | None = None,
        task_id: str | None = None,
        payload_hash: str | None = None,
        mode: Mode = Mode.ASK,
        skip: frozenset[str] = frozenset(),
        task_complexity: float = 0.5,
        requires_tools: bool = False,
        requires_vision: bool = False,
        cost_sensitivity: float = 0.5,
        model_tier: str | None = None,
        tool_family: str | None = None,
        verification: str | None = None,
        role: str = "act",
        tag: str | None = None,
    ) -> RoutingResult:
        """Select the best model for the given requirements.
        
        This is the core routing logic that determines which model should handle
        a completion request based on capabilities, availability, and other factors.
        """
        candidates = [e for e in self.pool.entries 
                     if e.spec.enabled and e.name not in skip and self.has_key(e)]
        
        if pin:
            # If a specific model is pinned, try to use it
            pinned_entry = next((e for e in candidates if e.name == pin), None)
            if pinned_entry is None:
                return RoutingResult(
                    model_entry=None,
                    decision=RoutingDecision.FORCED,
                    reason=f"Pinned model '{pin}' is unavailable",
                    candidates_tried=(pin,),
                )
            
            # Check if pinned model meets requirements
            if (pinned_entry.caps & need) != need:
                return RoutingResult(
                    model_entry=None,
                    decision=RoutingDecision.FORCED,
                    reason=f"Pinned model '{pin}' cannot handle capability {need}",
                    candidates_tried=(pin,),
                )
            
            # Check permissions
            ok, grant = label_access(pinned_entry, label, grants, task_id, payload_hash, mode)
            if not ok:
                pinned_grantable = [pinned_entry.name] if (pinned_entry.max_label < label and
                                                     pinned_entry.ask_private and 
                                                     mode is not Mode.LOCKED and 
                                                     (label is not Label.SECRET or pinned_entry.local)) else []
                if pinned_grantable:
                    return RoutingResult(
                        model_entry=None,
                        decision=RoutingDecision.NEEDS_PERMISSION,
                        reason=f"Model '{pin}' needs permission for this data",
                        candidates_tried=(pin,),
                        grantable_models=tuple(pinned_grantable),
                    )
                else:
                    return RoutingResult(
                        model_entry=None,
                        decision=RoutingDecision.NO_AVAILABLE,
                        reason=f"Model '{pin}' cannot access data with label {label}",
                        candidates_tried=(pin,),
                    )
            
            # Check if model can be used (rate limits, quotas, circuit breaker)
            return RoutingResult(
                model_entry=pinned_entry,
                decision=RoutingDecision.FORCED,
                reason=f"Using pinned model '{pin}'",
                candidates_tried=(pin,),
            )
        
        # Sort candidates by suitability score
        candidates.sort(
            key=lambda e: self._score_model_for_task(
                e, need, task_complexity, requires_tools, requires_vision, cost_sensitivity
                , model_tier, tool_family, verification
            ),
            reverse=True
        )
        
        tried: list[str] = []
        grantable: list[str] = []
        
        for entry in candidates:
            tried.append(entry.name)
            
            # Check capability match
            if (entry.caps & need) != need:
                continue
            
            # Check permissions
            ok, grant = label_access(entry, label, grants, task_id, payload_hash, mode)
            if not ok:
                if (entry.max_label < label and entry.ask_private and mode is not Mode.LOCKED 
                        and (label is not Label.SECRET or not entry.local) and (mode is Mode.ASK or entry.trains)):
                    grantable.append(entry.name)
                continue
            
            # Found a suitable model
            return RoutingResult(
                model_entry=entry,
                decision=RoutingDecision.OPTIMAL,
                reason=f"Selected '{entry.name}' as best match for requirements",
                candidates_tried=tuple(tried),
                grantable_models=tuple(grantable),
            )
        
        # No model found
        if grantable:
            return RoutingResult(
                model_entry=None,
                decision=RoutingDecision.NEEDS_PERMISSION,
                reason="No model available without permission",
                candidates_tried=tuple(tried),
                grantable_models=tuple(grantable),
            )
        
        if label >= Label.PERSONAL:
            return RoutingResult(
                model_entry=None,
                decision=RoutingDecision.NO_AVAILABLE,
                reason="No model may see this data: enable a local model or allow a model to ask",
                candidates_tried=tuple(tried),
            )
        
        return RoutingResult(
            model_entry=None,
            decision=RoutingDecision.NO_AVAILABLE,
            reason="Every model is busy, over quota, or down: try again shortly",
            candidates_tried=tuple(tried),
        )

    async def complete(
        self,
        req: CompletionRequest,
        *,
        need: Cap = Cap.NONE,
        label: Label = Label.PUBLIC,
        task_id: str | None = None,
        payload_hash: str | None = None,
        mode: Mode = Mode.ASK,
        pin: str | None = None,
        role: str = "act",
        tag: str | None = None,
        priority: int = 0,
        task_complexity: float = 0.5,
        requires_tools: bool = False,
        requires_vision: bool = False,
        cost_sensitivity: float = 0.5,
        model_tier: str | None = None,
        tool_family: str | None = None,
        verification: str | None = None,
    ) -> Completed:
        """Execute a completion request using the best available model.
        
        This is the main entry point for model execution. It handles:
        - Model selection based on requirements and current state
        - Automatic fallback on failure
        - Quota and rate limit management
        - Error handling and retry logic
        - Observability and event reporting
        """
        
        if not any(e.spec.enabled and self.has_key(e) for e in self.pool.entries):
            raise NoModelAvailable("No model has an API key yet. Add one in Settings → Models & keys "
                                   "(a free key works), or turn on a local model.")
        
        # Perform model selection
        routing = await self.select_model(
            need=need,
            label=label,
            pin=pin,
            grants=self.grants if mode != Mode.LOCKED else None,
            task_id=task_id,
            payload_hash=payload_hash,
            mode=mode,
            task_complexity=task_complexity,
            requires_tools=requires_tools,
            requires_vision=requires_vision,
            cost_sensitivity=cost_sensitivity,
            model_tier=model_tier, tool_family=tool_family, verification=verification,
            role=role,
            tag=tag,
        )
        
        if routing.model_entry is None:
            if routing.decision == RoutingDecision.NEEDS_PERMISSION:
                from lilly.domain.errors import NeedsGrant
                raise NeedsGrant(list(routing.grantable_models), int(label))
            else:
                raise NoModelAvailable(routing.reason)
        
        # Record the routing decision
        if task_id:
            self._routing_history[task_id] = routing
        
        entry = routing.model_entry
        entry.watch.began()
        
        # Estimate token usage
        chars = sum(len(m.content) for m in req.messages)
        cpt = getattr(self._settings.capacity, "chars_per_token", 4.0)
        est_in = math.ceil(chars / max(1.0, cpt))
        est_out = min(req.max_tokens, 1000)
        profile = CallProfile(est_in=est_in, est_out=est_out, role=role, need=need, priority=priority)
        
        # Use capacity manager for rate limiting and quotas
        retry_count = 0
        inline_retry_max_s = self._settings.capacity.inline_retry_max_s
        skip: set[str] = set()
        
        while True:
            max_w = inline_retry_max_s if retry_count > 0 and not pin else None
            
            try:
                lease = await self.capacity.acquire(
                    profile,
                    label=label,
                    mode=mode,
                    pin=pin,
                    tag=tag or ("quick" if req.quick else None),
                    grants=self.grants,
                    task_id=task_id,
                    payload_hash=payload_hash,
                    skip=frozenset(skip),
                    max_wait_s=max_w,
                )
                
                entry = lease.entry
                call_id = f"mc-{uuid.uuid4().hex[:12]}"
                started = self._clock()
                
                try:
                    result = await self._call(entry, req)
                except RateLimited as exc:
                    self.capacity.release(lease, tokens_in=0, tokens_out=0, outcome="rate_limited", error=exc)
                    await self._record_call(
                        call_id, task_id, role, entry.name, started,
                        int((self._clock() - started) * 1000), 0, 0,
                        int(lease.waited_s * 1000), "rate_limited",
                    )
                    retry_count += 1
                    if pin and (exc.retry_after or 0) > self._settings.capacity.max_wait_interactive_s:
                        raise
                    if not pin:
                        skip.add(entry.name)
                    continue
                    
                except asyncio.CancelledError:
                    self.capacity.release(lease, tokens_in=0, tokens_out=0, outcome="cancelled")
                    await self._record_call(
                        call_id, task_id, role, entry.name, started,
                        int((self._clock() - started) * 1000), 0, 0,
                        int(lease.waited_s * 1000), "cancelled",
                    )
                    raise
                    
                except ProviderError as exc:
                    self._record_failure(entry, exc)
                    self.capacity.release(lease, tokens_in=0, tokens_out=0, outcome="error")
                    await self._record_call(
                        call_id, task_id, role, entry.name, started,
                        int((self._clock() - started) * 1000), 0, 0,
                        int(lease.waited_s * 1000), "error",
                    )
                    if pin:
                        raise
                    skip.add(entry.name)
                    continue
                
                # Success
                self.capacity.release(lease, tokens_in=result.input_tokens, tokens_out=result.output_tokens, outcome="ok")
                entry.last_error = None
                entry.last_successful_call = self._clock()
                await self._record_call(
                    call_id, task_id, role, entry.name, started,
                    int((self._clock() - started) * 1000),
                    result.input_tokens, result.output_tokens,
                    int(lease.waited_s * 1000), "ok",
                )
                await self._persist_usage()
                
                # Update telemetry
                self._total_calls += 1
                self._total_tokens_in += result.input_tokens
                self._total_tokens_out += result.output_tokens
                
                return Completed(result, entry.name)
                
            except NoModelAvailable:
                # Try selection again with updated skip list
                if not pin:
                    routing = await self.select_model(
                        need=need,
                        label=label,
                        pin=pin,
                        grants=self.grants if mode != Mode.LOCKED else None,
                        task_id=task_id,
                        payload_hash=payload_hash,
                        mode=mode,
                        skip=frozenset(skip),
                        task_complexity=task_complexity,
                        requires_tools=requires_tools,
                        requires_vision=requires_vision,
                        cost_sensitivity=cost_sensitivity,
                        role=role,
                        tag=tag,
                    )
                    if routing.model_entry is None:
                        if routing.decision == RoutingDecision.NEEDS_PERMISSION:
                            from lilly.domain.errors import NeedsGrant
                            raise NeedsGrant(list(routing.grantable_models), int(label)) from None
                        else:
                            raise NoModelAvailable(routing.reason) from None
                    continue
                else:
                    raise

    async def _call(self, entry: ModelEntry, req: CompletionRequest) -> CompletionResult:
        """Make a single provider call."""
        try:
            return await self._providers[entry.name].complete(req)
        except ProviderError as pe:
            log.error("model %s raised ProviderError: %s (status=%s, retryable=%s)", 
                     entry.name, pe, pe.status, pe.retryable)
            raise
        except Exception as exc:
            # Only the type is logged: the message of an adapter error may quote the key
            log.error("model %s raised %s: %s", entry.name, type(exc).__name__, exc)
            raise ProviderError(retryable=True) from None

    def _record_failure(self, entry: ModelEntry, exc: ProviderError) -> None:
        """Record a model failure and update circuit breakers."""
        if isinstance(exc, QuotaExhausted):
            entry.watch.rejected(exc.retry_after)
            entry.breaker.trip(entry.watch.wait_after_refusal(exc.retry_after))
            entry.last_error = "rate limited by the provider"
        elif not exc.retryable:
            entry.breaker.failure(900.0)  # 15 minute cooldown for bad keys
            entry.last_error = f"rejected by the provider (HTTP {exc.status})" if exc.status else "rejected by the provider"
        else:
            entry.breaker.failure(exc.retry_after)
            entry.last_error = "temporarily unavailable"
        log.warning("model %s failed: %s", entry.name, entry.last_error)

    async def _persist_usage(self) -> None:
        """Persist usage data to the database."""
        usage = {
            e.name: (
                e.daily.day if e.daily else 0,
                e.daily.used if e.daily else 0,
                e.daily_tokens.used if e.daily_tokens else 0,
            )
            for e in self.pool.entries
            if e.daily is not None or e.daily_tokens is not None
        }
        if not usage:
            return
        try:
            await self._db.write(lambda con: save_usage(con, usage))
        except Exception:
            log.warning("quota usage not saved: database busy")

    async def _record_call(
        self,
        call_id: str,
        task_id: str | None,
        role: str | None,
        model: str,
        started_at: float,
        ms: int,
        tokens_in: int,
        tokens_out: int,
        waited_ms: int,
        outcome: str,
    ) -> None:
        """Record a model call to the ledger."""
        record = ModelCallRecord(
            id=call_id,
            task_id=task_id,
            turn=None,
            role=role,
            model=model,
            started_at=started_at,
            ms=ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            waited_ms=waited_ms,
            outcome=outcome,
        )
        try:
            await self._db.write(lambda con: record_model_call(con, record))
        except Exception:
            log.warning("model call record not saved: database busy")

    async def test(self, name: str) -> dict[str, object]:
        """Test a model to verify it works correctly."""
        entry = self.pool.get(name)
        if entry is None:
            return {"ok": False, "error": "unknown model"}
        if not self.has_key(entry):
            return {"ok": False, "error": "no key saved for this model"}
        if not entry.try_begin(8, 8):
            return {"ok": False, "error": "over its configured rate or quota limit"}
        
        started = time.monotonic()
        try:
            await self._call(entry, CompletionRequest(
                (Message("user", "Reply with the single word: ok"),), 8, deadline_s=20.0))
        except asyncio.CancelledError:
            entry.breaker.abort()
            raise
        except ProviderError as exc:
            self._record_failure(entry, exc)
            explanation = await self._explain(entry, exc)
            return {"ok": False, "error": explanation, "status": exc.status}
        
        entry.breaker.success()
        entry.last_error = None
        return {"ok": True, "latency_ms": round((time.monotonic() - started) * 1000)}

    async def _explain(self, entry: ModelEntry, exc: ProviderError) -> str | None:
        """Get a user-friendly explanation for a model failure."""
        if entry.spec.provider != "ollama":
            return entry.last_error
        return (await probe(self._local_client, entry.spec.base_url, entry.spec.model_id)).message

    async def discover_ollama(self, name: str) -> OllamaStatus | None:
        """Discover the status of an Ollama model."""
        entry = self.pool.get(name)
        if entry is None or entry.spec.provider != "ollama":
            return None
        return await probe(self._local_client, entry.spec.base_url, entry.spec.model_id)

    def snapshot(self) -> list[dict[str, object]]:
        """Get a snapshot of all model states for the UI."""
        return self.pool.snapshot()

    # For backward compatibility with existing interfaces
    async def route(self, need: Cap = Cap.NONE, label: Label = Label.PUBLIC, *, pin: str | None = None,
              grants: GrantStore | None = None, task_id: str | None = None, payload_hash: str | None = None,
              mode: Mode = Mode.ASK, skip: frozenset[str] = frozenset(), quick: bool = False,
              usable: Callable[[ModelEntry], bool] = lambda e: True) -> tuple[ModelEntry | None, str, tuple[str, ...]]:
        """Backward compatibility with existing route interface."""
        routing = await self.select_model(
            need=need, label=label, pin=pin, grants=grants, task_id=task_id,
            payload_hash=payload_hash, mode=mode, skip=skip,
        )
        if routing.model_entry:
            return routing.model_entry, routing.reason, routing.grantable_models
        else:
            return None, routing.reason, routing.grantable_models
