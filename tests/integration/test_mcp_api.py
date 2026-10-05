"""MCP servers through the web API: add, review, approve, run a task with an approved tool, and the secret path."""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import pytest

from tests.helpers import plan, step
from tests.integration.conftest import Api
from tests.unit.test_mcp_support import SERVER

pytestmark = pytest.mark.asyncio

BODY = {"name": "fake", "command": sys.executable, "args": [SERVER]}


async def add(api: Api, **extra: Any) -> None:
    r = await api.send("POST", "/api/mcp", {**BODY, **extra})
    assert r.status_code == 200, r.text


async def approve(api: Api, risks: dict[str, str], name: str = "fake") -> Any:
    reviewed = (await api.send("POST", f"/api/mcp/{name}/review")).json()
    return await api.send("POST", f"/api/mcp/{name}/approve", {"fingerprint": reviewed["fingerprint"], "risks": risks})


async def servers(api: Api) -> dict[str, Any]:
    return {s["name"]: s for s in (await api.get("/api/mcp")).json()["servers"]}


async def test_a_new_server_offers_nothing_until_its_tools_are_reviewed_and_approved(api: Api) -> None:
    await api.sign_in()
    await add(api)
    row = (await servers(api))["fake"]
    assert row["approved"] is False and row["state"] == "stopped" and not row["approved_tools"]
    assert not [t for t in api.runtime.tools if t.startswith("mcp.")]
    reviewed = (await api.send("POST", "/api/mcp/fake/review")).json()
    assert {"echo", "env"} <= {t["name"] for t in reviewed["tools"]}
    assert not [t for t in api.runtime.tools if t.startswith("mcp.")]   # looking approves nothing
    assert (await approve(api, {"echo": "R1"})).status_code == 200
    assert sorted(t for t in api.runtime.tools if t.startswith("mcp.")) == ["mcp.fake.echo"]
    assert (await servers(api))["fake"]["approved_tools"][0]["risk"] == "R1"


async def test_approval_is_refused_for_a_stale_review_an_unknown_tool_or_a_high_risk(api: Api) -> None:
    await api.sign_in()
    await add(api)
    stale = await api.send("POST", "/api/mcp/fake/approve", {"fingerprint": "0" * 64, "risks": {"echo": "R1"}})
    assert stale.status_code == 400 and "changed" in stale.json()["error"]
    reviewed = (await api.send("POST", "/api/mcp/fake/review")).json()
    for risks in ({"nope": "R1"}, {"echo": "R3"}, {"echo": "R9"}, {}, {"echo": 1}):
        r = await api.send("POST", "/api/mcp/fake/approve", {"fingerprint": reviewed["fingerprint"], "risks": risks})
        assert r.status_code == 400, risks
    assert not (await servers(api))["fake"]["approved"]


async def test_an_approved_tool_runs_in_a_task_after_the_owner_confirms(api: Api) -> None:
    await api.sign_in()
    await add(api, data_label="PUBLIC")
    assert (await approve(api, {"echo": "R2"})).status_code == 200
    api.provider.replies = [plan(step("s1", "mcp.fake.echo", text="hello"), step("s2", "llm.work", task="report", input="$s1.output")),
        "It said hello."]
    task = (await api.send("POST", "/api/tasks", {"goal": "echo hello"})).json()["task"]
    pending = await api.approval()
    assert pending["kind"] == "step"
    decide = await api.send("POST", f"/api/approvals/{pending['id']}/decide",
                            {"approve": True, "payload_hash": pending["payload_hash"]})
    assert decide.status_code == 200
    done = await api.finished(task["id"])
    assert done["task"]["state"] == "DONE"
    assert "hello" in json.dumps(done)
    assert (await servers(api))["fake"]["state"] == "running"


async def test_changing_how_a_server_starts_withdraws_its_approval_and_its_tools(api: Api) -> None:
    await api.sign_in()
    await add(api)
    assert (await approve(api, {"echo": "R1"})).status_code == 200
    await add(api, args=[SERVER, "v2"])
    assert not (await servers(api))["fake"]["approved"]
    assert not [t for t in api.runtime.tools if t.startswith("mcp.")]


async def test_turning_a_server_off_removes_its_tools_and_stops_it_and_on_brings_them_back(api: Api) -> None:
    await api.sign_in()
    await add(api)
    await approve(api, {"echo": "R1"})
    assert (await api.send("PATCH", "/api/mcp/fake", {"enabled": False})).status_code == 200
    assert not [t for t in api.runtime.tools if t.startswith("mcp.")]
    assert (await api.send("PATCH", "/api/mcp/fake", {"enabled": True})).status_code == 200
    assert "mcp.fake.echo" in api.runtime.tools
    assert (await api.send("PATCH", "/api/mcp/fake", {"enabled": "yes"})).status_code == 400
    assert (await api.send("PATCH", "/api/mcp/ghost", {"enabled": True})).status_code == 404


async def test_revoking_an_approval_and_deleting_a_server(api: Api) -> None:
    await api.sign_in()
    await add(api)
    await approve(api, {"echo": "R1"})
    assert (await api.send("DELETE", "/api/mcp/fake/approval")).status_code == 200
    assert not (await servers(api))["fake"]["approved"] and "mcp.fake.echo" not in api.runtime.tools
    assert (await api.send("DELETE", "/api/mcp/fake")).status_code == 200
    assert await servers(api) == {}
    assert (await api.send("DELETE", "/api/mcp/fake")).status_code == 404


async def test_a_secret_is_stored_in_the_key_store_passed_to_the_server_and_never_listed(api: Api) -> None:
    await api.sign_in()
    await add(api, secret_vars=["API_TOKEN"], env={"PLAIN": "visible"}, data_label="PUBLIC")
    row = (await servers(api))["fake"]
    assert row["secret_vars"] == [{"var": "API_TOKEN", "ref": "mcp.fake.API_TOKEN", "present": False}]
    assert (await api.send("PUT", "/api/keys/mcp.fake.OTHER", {"value": "x"})).status_code == 404   # only its own refs
    assert (await api.send("PUT", "/api/keys/mcp.fake.API_TOKEN", {"value": "s3cret-value"})).status_code == 200
    listing = await api.get("/api/mcp")
    assert "s3cret-value" not in listing.text and (await servers(api))["fake"]["secret_vars"][0]["present"]
    assert "s3cret-value" not in (await api.get("/api/keys")).text
    await approve(api, {"env": "R0"})
    api.provider.replies = [plan(step("s1", "mcp.fake.env", name="API_TOKEN"),
                                 step("s2", "llm.work", task="report", input="$s1.output")), "ok"]
    task = (await api.send("POST", "/api/tasks", {"goal": "read env"})).json()["task"]
    done = await api.finished(task["id"])
    assert done["task"]["state"] == "DONE", done
    seen = json.loads(next(s["output"] for s in done["steps"] if s["tool"] == "mcp.fake.env"))
    assert seen["value"] == "s3cret-value"                        # the server received it
    assert "API_TOKEN" in seen["names"] and "PLAIN" in seen["names"]
    assert not [n for n in seen["names"] if n.startswith(("LILLY", "MISTRAL"))]   # and nothing else of ours


async def test_deleting_a_server_removes_its_secrets(api: Api) -> None:
    await api.sign_in()
    await add(api, secret_vars=["API_TOKEN"])
    await api.send("PUT", "/api/keys/mcp.fake.API_TOKEN", {"value": "v"})
    assert api.runtime.keys.get("mcp.fake.API_TOKEN") is not None
    await api.send("DELETE", "/api/mcp/fake")
    assert api.runtime.keys.get("mcp.fake.API_TOKEN") is None


async def test_dropping_a_secret_variable_removes_its_value(api: Api) -> None:
    await api.sign_in()
    await add(api, secret_vars=["A", "B"])
    await api.send("PUT", "/api/keys/mcp.fake.B", {"value": "v"})
    await add(api, secret_vars=["A"])
    assert api.runtime.keys.get("mcp.fake.B") is None


@pytest.mark.parametrize("body", [
    {"name": "Bad Name", "command": "x"}, {"name": "ok", "command": ""}, {"name": "ok"},
    {"name": "ok", "command": "x", "args": "not-a-list"}, {"name": "ok", "command": "x", "args": [1]},
    {"name": "ok", "command": "x", "env": {"bad name": "v"}}, {"name": "ok", "command": "x", "secret_vars": ["1bad"]},
    {"name": "ok", "command": "x", "secret_vars": ["A"], "env": {"A": "plain"}},
    {"name": "ok", "command": "x", "data_label": "SECRET"}, {"name": "ok", "command": "x", "idle_stop_s": 1},
    {"name": "ok", "command": "x", "idle_stop_s": True}, {"name": "ok", "command": "x", "enabled": "no"},
])
async def test_bad_server_definitions_are_refused_and_store_nothing(api: Api, body: dict[str, Any]) -> None:
    await api.sign_in()
    assert (await api.send("POST", "/api/mcp", body)).status_code == 400
    assert await servers(api) == {}


async def test_a_server_that_cannot_start_gives_a_short_actionable_error(api: Api) -> None:
    await api.sign_in()
    assert (await api.send("POST", "/api/mcp", {"name": "gone", "command": "/no/such/program"})).status_code == 200
    r = await api.send("POST", "/api/mcp/gone/review")
    assert r.status_code == 400 and "could not start" in r.json()["error"]
    assert (await api.send("POST", "/api/mcp/ghost/review")).status_code == 400


async def test_configuration_survives_a_restart_of_the_runtime(api: Api) -> None:
    await api.sign_in()
    await add(api)
    await approve(api, {"echo": "R1"})
    await api.runtime.mcp.aclose()          # simulate a fresh process: nothing in memory, only the database
    from lilly.tools.mcp import McpManager
    api.runtime.mcp = McpManager(api.runtime._secret)
    await api.runtime.reload_mcp()
    assert "mcp.fake.echo" in api.runtime.tools


async def test_what_a_personal_server_returns_needs_the_owners_consent_before_a_model_sees_it(api: Api) -> None:
    await api.sign_in()
    await add(api)                                   # the default label is PERSONAL
    await approve(api, {"echo": "R0"})
    api.provider.replies = [plan(step("s1", "mcp.fake.echo", text="hello"),
                                 step("s2", "llm.work", task="report", input="$s1.output")), "done"]
    task = (await api.send("POST", "/api/tasks", {"goal": "echo"})).json()["task"]
    first = await api.approval()
    assert first["kind"] == "step"                    # a server is outside Lilly: its call is confirmed first
    await api.send("POST", f"/api/approvals/{first['id']}/decide",
                   {"approve": True, "payload_hash": first["payload_hash"]})
    pending = await api.approval()
    assert pending["kind"] == "model" and pending["payload"]["label"] == "PERSONAL"
    assert len(api.provider.requests) == 1             # only the plan so far; the answer waits for consent
    await api.send("POST", f"/api/approvals/{pending['id']}/decide",
                   {"approve": True, "payload_hash": pending["payload_hash"]})
    assert (await api.finished(task["id"]))["task"]["state"] == "DONE"


async def test_last_use_is_reported_as_a_wall_clock_time(api: Api) -> None:
    await api.sign_in()
    await add(api, data_label="PUBLIC")
    await approve(api, {"echo": "R0"})
    assert (await servers(api))["fake"]["last_used"] is not None      # reviewing counted as a use
    await api.runtime.mcp.call("fake", "echo", {"text": "x"}, None)
    used = (await servers(api))["fake"]["last_used"]
    assert abs(used - api.runtime.clock()) < 60      # seconds since epoch, not a monotonic reading


async def test_a_failing_server_tool_taints_the_task_and_its_message_reaches_the_planner_as_data(api: Api) -> None:
    await api.sign_in()
    await add(api, data_label="PUBLIC")
    await approve(api, {"fail": "R0"})
    api.provider.replies = [
        plan(step("s1", "mcp.fake.fail"), step("s2", "llm.work", task="report", input="$s1.output")),
        plan(answer="That did not work."),
    ]
    task = (await api.send("POST", "/api/tasks", {"goal": "try it"})).json()["task"]     # public and read-only: no prompt
    done = await api.finished(task["id"])
    assert done["task"]["state"] == "DONE" and done["task"]["tainted"] is True      # a failed call still taints
    replanning = api.provider.requests[1]["messages"][-1]["content"]
    assert "<untrusted_data>" in replanning and "it broke: bad input" in replanning
    assert replanning.index("<untrusted_data>") < replanning.index("it broke: bad input")


async def test_overlapping_reloads_cannot_bring_back_a_revoked_approval(api: Api) -> None:
    from lilly.store import mcp as store

    await api.sign_in()
    await add(api)
    await approve(api, {"echo": "R1"})
    rt = api.runtime
    real, gate, calls = rt.mcp.configure, asyncio.Event(), []

    async def slow_first(servers: Any, approvals: Any) -> None:
        calls.append(1)
        if len(calls) == 1:
            await gate.wait()                     # the first reload is still busy when the revoke happens
        await real(servers, approvals)

    rt.mcp.configure = slow_first                 # type: ignore[method-assign]
    first = asyncio.create_task(rt.reload_mcp())
    await asyncio.sleep(0.05)
    await rt.db.write(lambda con: store.revoke_approval(con, "fake"))
    second = asyncio.create_task(rt.reload_mcp())
    await asyncio.sleep(0.05)
    gate.set()
    await asyncio.gather(first, second)
    assert not [t for t in rt.tools if t.startswith("mcp.")]       # what the database says, not the older read


@pytest.mark.parametrize("env", [{"API_KEY": "x"}, {"github_token": "x"}])
async def test_secrets_cannot_be_stored_as_plain_settings(api: Api, env: dict[str, str]) -> None:
    await api.sign_in()
    r = await api.send("POST", "/api/mcp", {**BODY, "env": env})
    assert r.status_code == 400 and "secret variables" in r.json()["error"]
    assert await servers(api) == {}


async def test_a_secret_variable_name_with_a_newline_is_refused(api: Api) -> None:
    await api.sign_in()
    r = await api.send("POST", "/api/mcp", {**BODY, "secret_vars": ["TOKEN\n"]})
    assert r.status_code == 400 and await servers(api) == {}
