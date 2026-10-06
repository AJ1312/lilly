# Lilly 2.0 Architecture Status

This document records the completed migration boundaries. It is not a second
runtime design: the active implementation is AgentLoop, Laya System-1,
ModelBroker, SessionRuntime, and the policy-bound tool registry. The explicit
`mode="plan"` path remains only as a deprecated compatibility path for callers
that require deterministic skill plans.

## What was wrong with the current architecture

The current Lilly codebase has excellent components but suffers from:

1. **Architectural diffusion**: Core concerns (routing, model selection, tool discovery) are spread across multiple layers
2. **Multiple overlapping systems**: Different routing mechanisms exist simultaneously (pool, capacity, router)
3. **Inconsistent abstractions**: Some components are highly abstracted while others are tightly coupled
4. **Missing unified model broker**: The model selection and routing logic is fragmented
5. **Limited Laya integration**: Laya is used primarily for ranking tools rather than as a System 1 decision layer
6. **Tool discovery complexity**: Tool shortlisting can hide capabilities from the model unnecessarily

## Migration Goals

1. **Unified Model Broker**: Create a single component that handles all model selection, routing, and failover
2. **Clean Agent Loop**: Simplify the core reasoning loop while maintaining all safety features
3. **Enhanced Laya Integration**: Position Laya as System 1 decision layer for routing, capability selection, and verification decisions
4. **Capability-based Tool Architecture**: Implement namespace-based tool discovery with lazy schema loading
5. **Persistent Session Runtime**: Ensure sessions survive process restarts
6. **Event-driven Architecture**: Make events first-class citizens for observability and debugging

## Components to Keep

- Core policy enforcement (`domain/policy.py`)
- Provider abstractions (`providers/`)
- Model pool and capacity management (`core/pool.py`, `core/capacity.py`)
- Existing Laya infrastructure
- Store layer for persistence
- Tool registry and base classes
- Event bus system

## Components to Refactor/Replace

1. **ModelRouter → ModelBroker**: Enhance to be a true broker with better routing decisions
2. **AgentLoop**: Clean up and simplify, integrate better with Laya
3. **Tool Discovery**: Move to capability namespaces
4. **Memory System**: Separate into working/episodic/semantic layers
5. **Session Management**: Make more robust for persistence

## Migration Strategy

The migration is complete in place. Compatibility is limited to the explicit
plan mode and the `providers.router` import alias; neither is used by the
normal interactive runtime.

## Phase 1: Model Broker Implementation
- Create `ModelBroker` that unifies existing `ProviderPool` and `ModelRouter` functionality
- Add capability profiles for models
- Implement enhanced routing with Laya integration
- Maintain existing quota, rate limiting, and circuit breaker functionality

## Phase 2: Laya as System 1
- Enhance Laya decision types for routing, capability selection, verification
- Position Laya decisions before expensive generative calls
- Ensure Laya cannot override deterministic policy

## Phase 3: Clean Agent Loop
- Simplify the core loop while maintaining all safety features
- Integrate with new ModelBroker
- Better error handling and fallback

## Phase 4: Capability-based Tools
- Implement namespace-based tool discovery
- Add lazy schema loading
- Maintain existing tool safety and policy enforcement

## Phase 5: Memory and Session Enhancements
- Separate memory into logical layers
- Improve session persistence and recovery
- Add better event logging

## Testing Strategy

Each phase will include:
- Unit tests for new components
- Integration tests for end-to-end flows
- Failure tests for error conditions
- Security tests to ensure no regression in safety
