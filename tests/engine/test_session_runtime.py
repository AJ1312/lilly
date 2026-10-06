from __future__ import annotations

from pathlib import Path

import pytest

from lilly.engine.session_runtime import SessionRuntime, SessionStatus
from lilly.store.db import Database
from tests.helpers import Clock


class Broker:
    pass


@pytest.mark.asyncio
async def test_session_runtime_persists_lifecycle_and_state(tmp_path: Path) -> None:
    clock = Clock()
    db = Database(tmp_path / "sessions.db")
    events: list[tuple[str, dict[str, object]]] = []
    runtime = SessionRuntime(db, Broker(), clock=clock, on_event=lambda kind, data: events.append((kind, data)))
    session = runtime.create_session("task-1", "open the browser", initial_model="quick")
    assert session.status is SessionStatus.CREATED
    await runtime.start_session(session.session_id)
    runtime.update_session_state(session.session_id, {"frame_id": "f1"})
    runtime.add_session_event(session.session_id, "observed", {"frame_id": "f1"})
    await runtime.update_session_model(session.session_id, "vision")
    await runtime.complete_session(session.session_id, "done")
    assert runtime.get_session(session.session_id).status is SessionStatus.COMPLETED
    assert runtime.get_session_state(session.session_id)["frame_id"] == "f1"
    assert any(kind == "session.completed" for kind, _ in events)

    recovered = SessionRuntime(db, Broker(), clock=clock)
    await recovered.start()
    assert recovered.get_session(session.session_id).status is SessionStatus.COMPLETED
    assert recovered.get_session_state(session.session_id)["frame_id"] == "f1"
    db.close()


@pytest.mark.asyncio
async def test_session_runtime_recovers_and_cleans_old_created_sessions(tmp_path: Path) -> None:
    clock = Clock()
    db = Database(tmp_path / "sessions.db")
    runtime = SessionRuntime(db, Broker(), clock=clock, session_timeout=10)
    session = runtime.create_session("task-2", "waiting")
    await runtime.start_session(session.session_id)
    await runtime.fail_session(session.session_id, "provider failed")
    clock.advance(11)
    assert await runtime.cleanup_old_sessions() == 1
    assert runtime.get_session(session.session_id) is None
    db.close()
