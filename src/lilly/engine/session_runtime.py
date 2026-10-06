"""Persistent Session Runtime for Lilly 2.0.

This module implements the session runtime that maintains task state across
process restarts. It provides:
- Session persistence and recovery
- Task state management
- Event logging
- Integration with the ModelBroker and System1

The session runtime is the foundation of Lilly 2.0's persistent agent experience.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from typing import Any

from lilly.decide.system1 import (
    System1Engine,
)
from lilly.domain.clock import Clock
from lilly.providers.model_broker import ModelBroker, RoutingResult
from lilly.store.db import Database

log = logging.getLogger("lilly.session_runtime")


class SessionStatus(Enum):
    """Status of a session."""
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SessionType(Enum):
    """Type of a session."""
    INTERACTIVE = "interactive"  # User is actively engaged
    BACKGROUND = "background"    # Running in background
    SCHEDULED = "scheduled"    # Scheduled task
    ROUTINE = "routine"        # Routine execution


@dataclass(frozen=True, slots=True)
class SessionMetadata:
    """Metadata for a session."""
    session_id: str
    task_id: str
    user_id: str | None
    agent_id: str | None
    conversation_id: str | None
    status: SessionStatus
    session_type: SessionType
    created_at: float
    updated_at: float
    
    # Task information
    goal: str
    current_objective: str | None = None
    
    # Model and routing info
    current_model: str | None = None
    models_used: tuple[str, ...] = ()
    routing_decisions: tuple[dict[str, Any], ...] = ()
    
    # State and progress
    current_step: int = 0
    total_steps: int | None = None
    progress_percentage: float = 0.0
    
    # Resource usage
    model_calls: int = 0
    tokens_used: int = 0
    tool_calls: int = 0
    
    # Timing
    started_at: float | None = None
    completed_at: float | None = None
    last_activity_at: float = field(default=0.0)
    
    @property
    def is_active(self) -> bool:
        """Whether the session is currently active."""
        return self.status in (SessionStatus.CREATED, SessionStatus.RUNNING)
    
    @property
    def duration_seconds(self) -> float:
        """Duration of the session in seconds."""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        elif self.started_at:
            return time.time() - self.started_at
        else:
            return 0.0


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """A snapshot of session state for persistence."""
    session_id: str
    task_id: str
    status: SessionStatus
    type: SessionType
    metadata: dict[str, Any]
    state: dict[str, Any]  # Full session state
    created_at: float
    updated_at: float


@dataclass(slots=True)
class SessionArtifact:
    """An artifact produced by a session."""
    id: str
    session_id: str
    name: str
    type: str  # "text", "file", "data", "image", etc.
    content: str | bytes | dict[str, Any]
    created_at: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SessionEvent:
    """An event that occurred during a session."""
    id: str
    session_id: str
    task_id: str
    event_type: str
    timestamp: float
    data: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


class SessionRuntime:
    """The persistent session runtime for Lilly 2.0.
    
    This class manages sessions, their state, and their lifecycle. It provides:
    - Session creation, management, and cleanup
    - State persistence and recovery
    - Integration with ModelBroker for model selection
    - Integration with System1Engine for decision making
    - Event logging and observability
    """
    
    def __init__(
        self,
        db: Database,
        model_broker: ModelBroker,
        system1_engine: System1Engine | None = None,
        clock: Clock = time.monotonic,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        session_timeout: float = 3600.0,  # 1 hour default timeout
        max_sessions: int = 100,
    ) -> None:
        self._db = db
        self._model_broker = model_broker
        self._system1_engine = system1_engine
        self._clock = clock
        self._on_event = on_event
        self._session_timeout = session_timeout
        self._max_sessions = max_sessions
        
        # Active sessions
        self._sessions: dict[str, SessionMetadata] = {}
        self._session_state: dict[str, dict[str, Any]] = {}
        self._session_artifacts: dict[str, list[SessionArtifact]] = {}
        self._session_events: dict[str, list[SessionEvent]] = {}
        
        # Recovery tracking
        self._recovering_sessions: set[str] = set()
        
        log.info("SessionRuntime initialized")

    async def start(self) -> None:
        """Start the session runtime and recover any existing sessions."""
        await self._recover_sessions()
        log.info(f"SessionRuntime started with {len(self._sessions)} recovered sessions")

    async def _recover_sessions(self) -> None:
        """Recover sessions from persistence."""
        try:
            # Load saved sessions from database
            sessions = await self._load_sessions_from_db()
            for session_data in sessions:
                session_id = session_data["session_id"]
                try:
                    metadata_data = dict(session_data["metadata"])
                    metadata_data["status"] = SessionStatus(metadata_data["status"])
                    metadata_data["session_type"] = SessionType(metadata_data["session_type"])
                    metadata = SessionMetadata(**metadata_data)
                    state = session_data["state"]
                    
                    self._sessions[session_id] = metadata
                    self._session_state[session_id] = state
                    self._session_artifacts[session_id] = [SessionArtifact(**item) for item in session_data.get("artifacts", [])]
                    self._session_events[session_id] = [SessionEvent(**item) for item in session_data.get("events", [])]
                    self._recovering_sessions.add(session_id)
                    
                    log.info(f"Recovered session {session_id} with status {metadata.status}")
                    
                    # Emit recovery event
                    if self._on_event:
                        self._on_event("session.recovered", {
                            "session_id": session_id,
                            "status": metadata.status.name,
                            "goal": metadata.goal[:100] if metadata.goal else "",
                        })
                except Exception as e:
                    log.error(f"Failed to recover session {session_id}: {e}")
        except Exception as e:
            log.error(f"Session recovery failed: {e}")

    async def _load_sessions_from_db(self) -> list[dict[str, Any]]:
        """Load sessions from the database."""
        rows = self._db.reader.execute(
            "SELECT session_id, task_id, metadata_json, state_json, artifacts_json, events_json "
            "FROM session_snapshots").fetchall()
        return [{
            "session_id": row[0], "task_id": row[1],
            "metadata": json.loads(row[2]), "state": json.loads(row[3]),
            "artifacts": json.loads(row[4]), "events": json.loads(row[5]),
        } for row in rows]

    @staticmethod
    def _metadata_dict(session: SessionMetadata) -> dict[str, Any]:
        data = asdict(session)
        data["status"] = session.status.value
        data["session_type"] = session.session_type.value
        return data

    def create_session(
        self,
        task_id: str,
        goal: str,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        conversation_id: str | None = None,
        session_type: SessionType = SessionType.INTERACTIVE,
        initial_model: str | None = None,
    ) -> SessionMetadata:
        """Create a new session."""
        session_id = str(uuid.uuid4())
        now = self._clock()
        
        metadata = SessionMetadata(
            session_id=session_id,
            task_id=task_id,
            user_id=user_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            status=SessionStatus.CREATED,
            session_type=session_type,
            created_at=now,
            updated_at=now,
            goal=goal,
            current_model=initial_model,
        )
        
        self._sessions[session_id] = metadata
        self._session_state[session_id] = {
            "messages": [],
            "tool_calls": [],
            "results": [],
            "context": {},
        }
        self._session_artifacts[session_id] = []
        self._session_events[session_id] = []
        
        # Emit session created event
        if self._on_event:
            self._on_event("session.created", {
                "session_id": session_id,
                "task_id": task_id,
                "goal": goal[:100] if goal else "",
                "type": session_type.name,
            })
        
        log.info(f"Created session {session_id} for task {task_id}")
        return metadata

    async def start_session(self, session_id: str) -> None:
        """Start a session."""
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self._sessions[session_id]
        if session.status != SessionStatus.CREATED:
            log.warning(f"Session {session_id} is not in CREATED state (current: {session.status})")
        
        updated_session = replace(
            session,
            status=SessionStatus.RUNNING,
            started_at=self._clock(),
            updated_at=self._clock(),
        )
        
        self._sessions[session_id] = updated_session
        await self._persist_session(session_id)
        
        # Emit session started event
        if self._on_event:
            self._on_event("session.started", {
                "session_id": session_id,
                "task_id": session.task_id,
            })
        
        log.info(f"Started session {session_id}")

    async def pause_session(self, session_id: str) -> None:
        """Pause a session."""
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self._sessions[session_id]
        if session.status != SessionStatus.RUNNING:
            log.warning(f"Session {session_id} is not in RUNNING state (current: {session.status})")
        
        updated_session = replace(
            session,
            status=SessionStatus.PAUSED,
            updated_at=self._clock(),
        )
        
        self._sessions[session_id] = updated_session
        await self._persist_session(session_id)
        
        # Emit session paused event
        if self._on_event:
            self._on_event("session.paused", {
                "session_id": session_id,
                "task_id": session.task_id,
            })
        
        log.info(f"Paused session {session_id}")

    async def complete_session(self, session_id: str, result: Any | None = None) -> None:
        """Complete a session successfully."""
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self._sessions[session_id]
        
        updated_session = replace(
            session,
            status=SessionStatus.COMPLETED,
            completed_at=self._clock(),
            updated_at=self._clock(),
            progress_percentage=100.0,
        )
        
        self._sessions[session_id] = updated_session
        
        # Persist the session
        await self._persist_session(session_id)
        
        # Emit session completed event
        if self._on_event:
            self._on_event("session.completed", {
                "session_id": session_id,
                "task_id": session.task_id,
                "duration_seconds": updated_session.duration_seconds,
                "result_summary": str(result)[:200] if result else "",
            })
        
        log.info(f"Completed session {session_id}")

    async def fail_session(self, session_id: str, error: str) -> None:
        """Mark a session as failed."""
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self._sessions[session_id]
        
        updated_session = replace(
            session,
            status=SessionStatus.FAILED,
            completed_at=self._clock(),
            updated_at=self._clock(),
        )
        
        self._sessions[session_id] = updated_session
        await self._persist_session(session_id)
        
        # Emit session failed event
        if self._on_event:
            self._on_event("session.failed", {
                "session_id": session_id,
                "task_id": session.task_id,
                "error": error[:200],
            })
        
        log.warning(f"Failed session {session_id}: {error}")

    async def cancel_session(self, session_id: str) -> None:
        """Cancel a session."""
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self._sessions[session_id]
        
        updated_session = replace(
            session,
            status=SessionStatus.CANCELLED,
            completed_at=self._clock(),
            updated_at=self._clock(),
        )
        
        self._sessions[session_id] = updated_session
        await self._persist_session(session_id)
        
        # Emit session cancelled event
        if self._on_event:
            self._on_event("session.cancelled", {
                "session_id": session_id,
                "task_id": session.task_id,
            })
        
        log.info(f"Cancelled session {session_id}")

    async def cleanup_session(self, session_id: str) -> None:
        """Clean up a session and remove it from active sessions."""
        if session_id not in self._sessions:
            return
        
        # Persist before cleanup
        await self._persist_session(session_id)
        
        # Remove from active sessions
        del self._sessions[session_id]
        if session_id in self._session_state:
            del self._session_state[session_id]
        if session_id in self._session_artifacts:
            del self._session_artifacts[session_id]
        if session_id in self._session_events:
            del self._session_events[session_id]
        if session_id in self._recovering_sessions:
            self._recovering_sessions.remove(session_id)
        
        log.info(f"Cleaned up session {session_id}")

    async def _persist_session(self, session_id: str) -> None:
        """Persist a session to the database."""
        if session_id not in self._sessions:
            return
        
        session = self._sessions[session_id]
        state = self._session_state.get(session_id, {})
        
        # Create snapshot
        snapshot = SessionSnapshot(
            session_id=session_id,
            task_id=session.task_id,
            status=session.status,
            type=session.session_type,
            metadata=self._metadata_dict(session),
            state=state,
            created_at=session.created_at,
            updated_at=self._clock(),
        )
        
        artifacts = [asdict(a) for a in self._session_artifacts.get(session_id, [])]
        events = [asdict(e) for e in self._session_events.get(session_id, [])]
        await self._db.write(lambda con: con.execute(
            "INSERT INTO session_snapshots(session_id, task_id, status, session_type, metadata_json, state_json, "
            "artifacts_json, events_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET task_id=excluded.task_id, status=excluded.status, "
            "session_type=excluded.session_type, metadata_json=excluded.metadata_json, state_json=excluded.state_json, "
            "artifacts_json=excluded.artifacts_json, events_json=excluded.events_json, updated_at=excluded.updated_at",
            (snapshot.session_id, snapshot.task_id, snapshot.status.value, snapshot.type.value,
             json.dumps(snapshot.metadata, default=str), json.dumps(snapshot.state, default=str),
             json.dumps(artifacts, default=str), json.dumps(events, default=str),
             snapshot.created_at, snapshot.updated_at)))

    def get_session(self, session_id: str) -> SessionMetadata | None:
        """Get session metadata."""
        return self._sessions.get(session_id)

    def get_session_state(self, session_id: str) -> dict[str, Any] | None:
        """Get the full state of a session."""
        return self._session_state.get(session_id)

    def get_session_artifacts(self, session_id: str) -> list[SessionArtifact]:
        """Get artifacts for a session."""
        return self._session_artifacts.get(session_id, [])

    def get_session_events(self, session_id: str) -> list[SessionEvent]:
        """Get events for a session."""
        return self._session_events.get(session_id, [])

    def update_session_state(self, session_id: str, updates: dict[str, Any]) -> None:
        """Update the state of a session."""
        if session_id not in self._session_state:
            self._session_state[session_id] = {}
        
        self._session_state[session_id].update(updates)
        
        # Update timestamp
        if session_id in self._sessions:
            updated_session = replace(self._sessions[session_id], updated_at=self._clock())
            self._sessions[session_id] = updated_session
            self._schedule_persist(session_id)

    def _schedule_persist(self, session_id: str) -> None:
        """Persist a synchronous state mutation without blocking the caller."""
        try:
            asyncio.get_running_loop().create_task(self._persist_session(session_id))
        except RuntimeError:
            log.debug("session %s will persist at its next lifecycle transition", session_id)

    def add_session_event(self, session_id: str, event_type: str, data: dict[str, Any]) -> SessionEvent:
        """Add an event to a session."""
        event = SessionEvent(
            id=str(uuid.uuid4()),
            session_id=session_id,
            task_id=self._sessions[session_id].task_id if session_id in self._sessions else "",
            event_type=event_type,
            timestamp=self._clock(),
            data=data,
        )
        
        if session_id not in self._session_events:
            self._session_events[session_id] = []
        
        self._session_events[session_id].append(event)
        self._schedule_persist(session_id)
        
        # Emit event
        if self._on_event:
            self._on_event(f"session.{event_type}", {
                "session_id": session_id,
                "event_id": event.id,
                **data,
            })
        
        return event

    def add_artifact(self, session_id: str, name: str, artifact_type: str, content: str | bytes | dict[str, Any]) -> SessionArtifact:
        """Add an artifact to a session."""
        artifact = SessionArtifact(
            id=str(uuid.uuid4()),
            session_id=session_id,
            name=name,
            type=artifact_type,
            content=content,
            created_at=self._clock(),
        )
        
        if session_id not in self._session_artifacts:
            self._session_artifacts[session_id] = []
        
        self._session_artifacts[session_id].append(artifact)
        self._schedule_persist(session_id)
        
        # Emit artifact event
        if self._on_event:
            self._on_event("session.artifact_created", {
                "session_id": session_id,
                "artifact_id": artifact.id,
                "name": name,
                "type": artifact_type,
            })
        
        return artifact

    async def update_session_model(self, session_id: str, model_name: str) -> None:
        """Update the current model for a session."""
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self._sessions[session_id]
        
        # Track models used
        models_used = list(session.models_used)
        if model_name not in models_used:
            models_used.append(model_name)
        
        updated_session = replace(
            session,
            current_model=model_name,
            models_used=tuple(models_used),
            updated_at=self._clock(),
        )
        
        self._sessions[session_id] = updated_session
        await self._persist_session(session_id)

    async def add_routing_decision(self, session_id: str, routing: RoutingResult) -> None:
        """Add a routing decision to a session."""
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self._sessions[session_id]
        
        routing_decisions = list(session.routing_decisions)
        routing_decisions.append({
            "model": routing.model_name,
            "decision": routing.decision.value,
            "reason": routing.reason,
            "timestamp": self._clock(),
        })
        
        updated_session = replace(
            session,
            routing_decisions=tuple(routing_decisions),
            updated_at=self._clock(),
        )
        
        self._sessions[session_id] = updated_session
        await self._persist_session(session_id)

    async def cleanup_old_sessions(self) -> int:
        """Clean up old sessions that have timed out."""
        cleaned_up = 0
        now = self._clock()
        
        for session_id, session in list(self._sessions.items()):
            if session.status in (SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.CANCELLED):
                # Keep completed sessions for a while
                if now - session.updated_at > self._session_timeout:
                    await self.cleanup_session(session_id)
                    cleaned_up += 1
            elif session.status == SessionStatus.CREATED:
                # Clean up created sessions that never started
                if now - session.created_at > self._session_timeout / 2:
                    await self.cleanup_session(session_id)
                    cleaned_up += 1
        
        return cleaned_up

    def get_active_sessions(self) -> list[SessionMetadata]:
        """Get all active sessions."""
        return [s for s in self._sessions.values() if s.is_active]

    def get_session_count(self) -> int:
        """Get the total number of active sessions."""
        return len(self._sessions)

    def get_telemetry(self) -> dict[str, Any]:
        """Get telemetry about sessions."""
        active = sum(1 for s in self._sessions.values() if s.is_active)
        completed = sum(1 for s in self._sessions.values() if s.status == SessionStatus.COMPLETED)
        failed = sum(1 for s in self._sessions.values() if s.status == SessionStatus.FAILED)
        
        total_duration = sum(s.duration_seconds for s in self._sessions.values())
        total_tokens = sum(s.tokens_used for s in self._sessions.values())
        total_model_calls = sum(s.model_calls for s in self._sessions.values())
        
        return {
            "active_sessions": active,
            "completed_sessions": completed,
            "failed_sessions": failed,
            "total_sessions": len(self._sessions),
            "total_duration_seconds": total_duration,
            "total_tokens_used": total_tokens,
            "total_model_calls": total_model_calls,
            "recovering_sessions": len(self._recovering_sessions),
        }
