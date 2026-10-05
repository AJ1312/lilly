"""GET /api/decisions: signed-in only, bounded, filterable."""
from __future__ import annotations

import pytest

from lilly.domain.decisions import DecisionRecord, Kind
from lilly.store import decisions
from tests.integration.conftest import Api

pytestmark = pytest.mark.asyncio


def rec(i: int, kind: Kind = Kind.PICK) -> DecisionRecord:
    return DecisionRecord(float(i), kind, "t", "match", "a", 0.9, False, 2, f"request {i}", "ok")


async def test_the_decision_log_needs_a_session(api: Api) -> None:
    assert (await api.http.get("/api/decisions")).status_code == 401


async def test_recent_decisions_and_a_summary_are_listed(api: Api) -> None:
    await api.sign_in()
    for i in range(3):
        await api.runtime.db.write(lambda con, i=i: decisions.insert(con, rec(i, Kind.LOOP if i == 0 else Kind.PICK)))
    body = (await api.get("/api/decisions")).json()
    assert [d["summary"] for d in body["decisions"]] == ["request 2", "request 1", "request 0"]
    assert body["decisions"][0]["decider"] == "match" and body["decisions"][0]["shadow"] is False
    assert {(s["kind"], s["decisions"]) for s in body["summary"]} == {("pick", 2), ("loop", 1)}
    assert len((await api.get("/api/decisions?limit=1")).json()["decisions"]) == 1
    only = (await api.get("/api/decisions?kind=loop")).json()["decisions"]
    assert [d["kind"] for d in only] == ["loop"]


async def test_an_unknown_kind_is_a_plain_error(api: Api) -> None:
    await api.sign_in()
    r = await api.get("/api/decisions?kind=allow")
    assert r.status_code == 400 and "kind must be one of" in r.json()["error"]


async def test_the_owner_can_mark_a_decision_right_or_wrong(api: Api) -> None:
    assert (await api.http.post("/api/decisions/1/outcome", json={"outcome": "accepted"})).status_code == 401
    await api.sign_in()
    log_id = await api.runtime.db.write(lambda con: decisions.insert(con, rec(1)))
    ok = await api.send("POST", f"/api/decisions/{log_id}/outcome", {"outcome": "corrected"})
    assert ok.status_code == 200
    assert (await api.get("/api/decisions")).json()["summary"][0]["corrected"] == 1
    assert (await api.send("POST", f"/api/decisions/{log_id}/outcome", {"outcome": "allow"})).status_code == 400
    assert (await api.send("POST", "/api/decisions/999/outcome", {"outcome": "accepted"})).status_code == 404
    assert (await api.send("POST", "/api/decisions/abc/outcome", {"outcome": "accepted"})).status_code == 400
