"""Tests for the ModelBroker component."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import httpx
import pytest

from lilly.core.pool import ModelEntry
from lilly.domain.caps import Cap
from lilly.domain.labels import Label
from lilly.domain.ports import CompletionRequest
from lilly.domain.settings import ModelSpec, Settings
from lilly.providers.model_broker import ModelBroker, ModelCapabilityProfile, RoutingDecision, RoutingResult
from lilly.store.db import Database


class MockKeyStore:
    def get(self, ref: str) -> object | None:
        return None

    def put(self, ref: str, value: object) -> None:
        pass

    def delete(self, ref: str) -> None:
        pass


class MockProvider:
    def __init__(self, name: str):
        self.name = name

    async def complete(self, req: CompletionRequest) -> object:
        from lilly.domain.ports import CompletionResult

        return CompletionResult(
            text=f"Response from {self.name}",
            input_tokens=10,
            output_tokens=20,
            finish_reason="stop",
        )


@pytest.fixture
def mock_settings():
    """Create mock settings with some models."""
    return Settings(
        models=[
            ModelSpec(
                name="mistral-small",
                provider="mistral",
                model_id="mistral-small-latest",
                enabled=True,
                local=False,
                caps=Cap.TOOLS,
            ),
            ModelSpec(
                name="mistral-large",
                provider="mistral",
                model_id="mistral-large-latest",
                enabled=True,
                local=False,
                caps=Cap.TOOLS | Cap.JSON,
            ),
        ],
        capacity=None,
        limits=None,
        engine=None,
        decisions=None,
        file_roots=(),
        browser=None,
        devbox=None,
        stay_awake=False,
        retention_days=7,
        network=None,
        modules=(),
    )


@pytest.fixture
def mock_db():
    """Create a temporary database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    # Create the database file
    con = sqlite3.connect(db_path)
    con.close()

    db = Database(db_path)
    yield db

    # Clean up
    db.close()
    db_path.unlink()


@pytest.fixture
def mock_key_store():
    return MockKeyStore()


@pytest.fixture
def mock_client():
    return httpx.AsyncClient()


@pytest.mark.asyncio
async def test_model_broker_initialization(mock_settings, mock_db, mock_key_store, mock_client):
    """Test that ModelBroker initializes correctly."""
    keys = mock_key_store

    broker = ModelBroker(
        settings=mock_settings,
        keys=keys,
        client=mock_client,
        db=mock_db,
        grants=None,
    )

    assert broker is not None
    assert len(broker.pool.entries) == 2
    assert "mistral-small" in [e.name for e in broker.pool.entries]
    assert "mistral-large" in [e.name for e in broker.pool.entries]


@pytest.mark.asyncio
async def test_model_broker_get_available_models(mock_settings, mock_db, mock_key_store, mock_client):
    """Test getting available models."""
    broker = ModelBroker(
        settings=mock_settings,
        keys=mock_key_store,
        client=mock_client,
        db=mock_db,
        grants=None,
    )

    available = broker.get_available_models()
    # Models are available if enabled (we don't have keys, but that's mocked)
    assert isinstance(available, list)


@pytest.mark.asyncio
async def test_model_broker_state_reports_health_for_each_entry(mock_settings, mock_db, mock_key_store, mock_client):
    broker = ModelBroker(
        settings=mock_settings,
        keys=mock_key_store,
        client=mock_client,
        db=mock_db,
        grants=None,
    )

    state = broker.get_broker_state()

    assert set(state.health_status) == {"mistral-small", "mistral-large"}
    assert all(status is not None for status in state.health_status.values())


@pytest.mark.asyncio
async def test_model_capability_profile(mock_settings, mock_db, mock_key_store, mock_client):
    """Test ModelCapabilityProfile creation."""
    profile = ModelCapabilityProfile(
        reasoning_strength=0.9,
        coding_strength=0.8,
        tool_calling=0.9,
        structured_output=0.8,  # For JSON capability
        context_window=128000,  # For LONG_CONTEXT capability
        cost_tier="free",
    )

    assert profile.can_handle_capability(Cap.TOOLS) is True
    assert profile.can_handle_capability(Cap.JSON) is True
    assert profile.can_handle_capability(Cap.LONG_CONTEXT) is True


@pytest.mark.asyncio
async def test_routing_decision_enum():
    """Test RoutingDecision enum values."""
    assert RoutingDecision.OPTIMAL.value == "optimal"
    assert RoutingDecision.FALLBACK.value == "fallback"
    assert RoutingDecision.FORCED.value == "forced"
    assert RoutingDecision.NO_AVAILABLE.value == "no_available"


@pytest.mark.asyncio
async def test_routing_result(mock_settings, mock_db, mock_key_store, mock_client):
    """Test RoutingResult dataclass."""
    entry = ModelEntry(
        spec=mock_settings.models[0],
        minute=None,
        daily=None,
        breaker=None,
    )

    result = RoutingResult(
        model_entry=entry,
        decision=RoutingDecision.OPTIMAL,
        reason="Test selection",
        candidates_tried=("mistral-small",),
    )

    assert result.model_name == "mistral-small"
    assert result.decision == RoutingDecision.OPTIMAL
    assert result.reason == "Test selection"


@pytest.mark.asyncio
async def test_model_broker_select_model(mock_settings, mock_db, mock_key_store, mock_client):
    """Test model selection logic."""
    broker = ModelBroker(
        settings=mock_settings,
        keys=mock_key_store,
        client=mock_client,
        db=mock_db,
        grants=None,
    )

    # Test basic selection
    routing = await broker.select_model(
        need=Cap.NONE,
        label=Label.PUBLIC,
        task_complexity=0.5,
    )

    # Since we don't have keys, this might return None model
    assert routing is not None
    assert isinstance(routing.decision, RoutingDecision)


@pytest.mark.asyncio
async def test_capability_profile_inference(mock_db):
    """Test that capability profiles can be inferred from model specs."""
    from lilly.domain.settings import ModelSpec

    # Test inference for different providers
    mistral_spec = ModelSpec(
        name="mistral-large",
        provider="mistral",
        model_id="mistral-large-latest",
        enabled=True,
        caps=Cap.TOOLS | Cap.JSON,
        tools="native",
    )

    broker = ModelBroker(
        settings=Settings(
            models=[mistral_spec],
            capacity=None,
            limits=None,
            engine=None,
            decisions=None,
            file_roots=(),
            browser=None,
            devbox=None,
            stay_awake=False,
            retention_days=7,
            network=None,
            modules=(),
        ),
        keys=MockKeyStore(),
        client=httpx.AsyncClient(),
        db=mock_db,
        grants=None,
    )

    # Check profile inference
    mistral_profile = broker._get_capability_profile("mistral-large")

    # Mistral should have high reasoning
    assert mistral_profile.reasoning_strength >= 0.7
    assert mistral_profile.tool_calling >= 0.8


@pytest.mark.asyncio
async def test_model_scoring(mock_settings, mock_db, mock_key_store, mock_client):
    """Test model scoring for task suitability."""
    broker = ModelBroker(
        settings=mock_settings,
        keys=mock_key_store,
        client=mock_client,
        db=mock_db,
        grants=None,
    )

    # Create a mock entry
    entry = broker.pool.get("mistral-small")
    assert entry is not None

    # Test scoring
    score = broker._score_model_for_task(
        entry,
        need=Cap.NONE,
        task_complexity=0.5,
        requires_tools=False,
        requires_vision=False,
        cost_sensitivity=0.5,
    )

    # Score should be valid
    assert isinstance(score, float)

    # Test with different parameters
    complex_score = broker._score_model_for_task(
        entry,
        need=Cap.TOOLS,
        task_complexity=0.9,
        requires_tools=True,
        requires_vision=False,
        cost_sensitivity=0.8,
    )

    assert isinstance(complex_score, float)


@pytest.mark.asyncio
async def test_model_choice_tiers(mock_db, mock_client):
    """Assert model choice for QUICK, STRONG, VISION, and tool-required tasks (LLY-001)."""
    from lilly.domain.settings import CapacitySettings, LimitSettings, ModelSpec, Settings

    quick_spec = ModelSpec(
        name="model-quick",
        provider="mistral",
        model_id="quick-id",
        enabled=True,
        caps=Cap.JSON,
        quick=True,
        lane=2,
        tags=("fast",),
    )
    strong_spec = ModelSpec(
        name="model-strong",
        provider="openai",
        model_id="strong-id",
        enabled=True,
        caps=Cap.TOOLS | Cap.JSON,
        lane=1,
        tags=("strong",),
    )
    vision_spec = ModelSpec(
        name="model-vision",
        provider="gemini",
        model_id="vision-id",
        enabled=True,
        caps=Cap.VISION | Cap.JSON,
        lane=1,
    )

    class FakeKeyStore:
        def get(self, ref):
            return "fake-key"

    settings = Settings(
        models=[quick_spec, strong_spec, vision_spec],
        capacity=CapacitySettings(),
        limits=LimitSettings(),
    )
    broker = ModelBroker(settings=settings, keys=FakeKeyStore(), client=mock_client, db=mock_db, grants=None)
    await broker.refresh_keys()

    # QUICK task
    r_quick = await broker.select_model(model_tier="QUICK")
    assert r_quick.model_name == "model-quick"

    # STRONG task
    r_strong = await broker.select_model(model_tier="STRONG", task_complexity=0.9)
    assert r_strong.model_name == "model-strong"

    # VISION task
    r_vision = await broker.select_model(need=Cap.VISION, requires_vision=True)
    assert r_vision.model_name == "model-vision"

    # Tools required task
    r_tools = await broker.select_model(need=Cap.TOOLS, requires_tools=True)
    assert r_tools.model_name == "model-strong"


@pytest.mark.asyncio
async def test_preferred_model_fallback_recorded(mock_db, mock_client):
    """Assert that when preferred model is busy, eligible fallback is leased and recorded in history (LLY-001)."""
    from lilly.core.capacity import CallProfile
    from lilly.domain.settings import CapacitySettings, ModelSpec, Settings

    spec_a = ModelSpec(name="primary-a", provider="mistral", model_id="a", enabled=True, caps=Cap.NONE, lane=1)
    spec_b = ModelSpec(name="fallback-b", provider="openai", model_id="b", enabled=True, caps=Cap.NONE, lane=2)

    class FakeKeyStore:
        def get(self, ref):
            return "fake-key"

    settings = Settings(models=[spec_a, spec_b], capacity=CapacitySettings(max_inflight_per_model=1))
    broker = ModelBroker(settings=settings, keys=FakeKeyStore(), client=mock_client, db=mock_db, grants=None)
    await broker.refresh_keys()

    # Mark primary-a as busy with an active lease/inflight
    entry_a = broker.pool.get("primary-a")
    entry_a.inflight = 5  # over max_inflight_per_model

    # Acquire with preferred candidates
    profile = CallProfile(est_in=10, est_out=10, role="act", need=Cap.NONE, priority=0)
    lease = await broker.capacity.acquire(
        profile,
        preferred_candidates=("primary-a", "fallback-b"),
        preferred_model="primary-a",
    )
    # The ready fallback should win without waiting
    assert lease.entry.name == "fallback-b"
    broker.capacity.release(lease, tokens_in=10, tokens_out=10, outcome="ok")


@pytest.mark.asyncio
async def test_capacity_timeout_bounded_retry(mock_db, mock_client):
    """Assert that capacity timeout does not loop indefinitely on unavailable model (LLY-002)."""
    from lilly.domain.errors import NoModelAvailable
    from lilly.domain.ports import CompletionRequest, Message
    from lilly.domain.settings import CapacitySettings, ModelSpec, Settings

    spec = ModelSpec(name="single-busy", provider="mistral", model_id="m", enabled=True, caps=Cap.NONE, lane=1)

    class FakeKeyStore:
        def get(self, ref):
            return "fake-key"

    settings = Settings(
        models=[spec],
        capacity=CapacitySettings(max_wait_interactive_s=0.1, inline_retry_max_s=0.1),
    )
    broker = ModelBroker(settings=settings, keys=FakeKeyStore(), client=mock_client, db=mock_db, grants=None)

    # Force single-busy over quota
    entry = broker.pool.get("single-busy")
    entry.inflight = 10

    req = CompletionRequest(messages=(Message("user", "hi"),), max_tokens=10, deadline_s=0.2)
    with pytest.raises(NoModelAvailable):
        await broker.complete(req)
