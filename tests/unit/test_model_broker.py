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
async def test_capability_profile_inference():
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
        settings=Settings(models=[mistral_spec], capacity=None, limits=None, 
                        engine=None, decisions=None, file_roots=(), browser=None, devbox=None,
                        stay_awake=False, retention_days=7, network=None, modules=()),
        keys=MockKeyStore(),
        client=httpx.AsyncClient(),
        db=Database(":memory:"),
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
