# Lilly 2.0 Migration Record

The in-place migration is complete. The normal runtime is one `SessionRuntime`-backed `AgentLoop`, typed Laya System-1 routing, and `ModelBroker`, with capability namespaces discovered lazily and policy applied before every action.

Computer work is owned by the persistent `ComputerRuntime` and DevBox integration. Frames carry IDs, actions reject stale observations, and each action captures and verifies a fresh state. Restarted tasks are reconciled in `SessionRuntime`; explicit redrive creates a child task and requires confirmation when an external action may have taken effect.

The remaining compatibility boundaries are deliberate: `mode="plan"` supports deterministic callers, `providers.router` is an alias to `ModelBroker`, and `core.shortlist` remains a small test/integration utility. None is used by the normal AgentLoop runtime.

See [Architecture](ARCHITECTURE.md) and [Verification](VERIFICATION.md) for the current design and release gates.
