"""The web API, end to end: real runtime, real policy, real database; only the model vendor is faked."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.routing import Route

from lilly.domain.settings import settings_to_dict
from tests.helpers import plan, step
from tests.integration.conftest import Api

pytestmark = pytest.mark.asyncio

PUBLIC = {"/healthz", "/login", "/api/session", "/api/login", "/api/{rest:path}", "/{path:path}"}


# ---- who gets in -------------------------------------------------------------------------------
async def test_every_route_but_the_public_ones_refuses_anonymous_requests(api: Api) -> None:
    app = api.http._transport.app  # type: ignore[attr-defined]
    checked = 0
    for route in app.routes:
        assert isinstance(route, Route)
        if route.path in PUBLIC:
            continue
        path = route.path.replace("{", "x").replace("}", "")
        for method in route.methods - {"HEAD"}:
            r = await api.http.request(method, path)
            assert r.status_code == 401, f"{method} {route.path} answered {r.status_code} without a session"
            checked += 1
    assert checked > 40


async def test_health_is_public_and_sign_in_needs_the_right_token(api: Api) -> None:
    assert (await api.get("/healthz")).json()["app"] == "lilly"
    assert (await api.get("/api/session")).json() == {"signed_in": False}
    assert (await api.http.post("/api/login", json={"token": "wrong"})).status_code == 401
    await api.sign_in()
    me = (await api.get("/api/session")).json()
    assert me["signed_in"] and me["csrf"] == api.csrf


async def test_repeated_wrong_tokens_are_throttled(api: Api) -> None:
    for _ in range(8):
        assert (await api.http.post("/api/login", json={"token": "nope"})).status_code == 401
    assert (await api.http.post("/api/login", json={"token": "nope"})).status_code == 429
    assert (await api.http.post("/api/login", json={"token": api.auth.token})).status_code == 429  # still locked


async def test_login_link_sets_a_cookie_and_redirects_away_from_the_token(api: Api) -> None:
    r = await api.get(f"/login?token={api.auth.token}")
    assert r.status_code == 303 and r.headers["location"] == "/" and "lilly_session" in r.headers["set-cookie"]
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    bad = await api.http.get("/login?token=wrong")
    assert bad.status_code == 303 and "set-cookie" not in bad.headers


async def test_state_changes_need_the_csrf_token_and_a_same_origin_request(api: Api) -> None:
    await api.sign_in()
    body = {"text": "I like tea"}
    assert (await api.http.post("/api/memory", json=body)).status_code == 403
    assert (await api.http.post("/api/memory", json=body, headers={"X-Lilly-CSRF": "x" * 64})).status_code == 403
    cross = {**api.headers(), "Origin": "https://evil.example"}
    assert (await api.http.post("/api/memory", json=body, headers=cross)).status_code == 403
    site = {**api.headers(), "Sec-Fetch-Site": "cross-site"}
    assert (await api.http.post("/api/memory", json=body, headers=site)).status_code == 403
    assert (await api.send("POST", "/api/memory", body)).status_code == 201


async def test_non_ascii_credentials_are_an_ordinary_refusal_not_a_crash(api: Api) -> None:
    await api.sign_in()
    odd = "é€".encode()
    assert (await api.http.get("/api/tasks", headers={"Cookie": b"lilly_session=1." + odd})).status_code == 401
    refused = await api.http.post("/api/memory", json={"text": "tea"}, headers={"X-Lilly-CSRF": odd})
    assert refused.status_code == 403


async def test_unknown_hosts_and_oversized_bodies_are_refused_and_headers_are_set(api: Api) -> None:
    assert (await api.http.get("/healthz", headers={"Host": "evil.example"})).status_code == 400
    await api.sign_in()
    big = await api.http.post("/api/memory", content=b"x" * 1_200_000, headers=api.headers())
    assert big.status_code == 413
    r = await api.get("/healthz")
    assert "default-src 'none'" in r.headers["content-security-policy"] and "unsafe-inline" not in r.headers[
        "content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"


async def test_extra_hosts_come_from_settings(api: Api) -> None:
    await api.sign_in()
    assert (await api.http.get("/healthz", headers={"Host": "mac.tail1234.ts.net"})).status_code == 400
    current = settings_to_dict(api.runtime.settings)
    current["network"] = {"allowed_hosts": ["mac.tail1234.ts.net"]}
    assert (await api.send("PUT", "/api/settings", current)).status_code == 200
    assert (await api.http.get("/healthz", headers={"Host": "mac.tail1234.ts.net"})).status_code == 200


async def test_sign_out_everywhere_invalidates_other_sessions(api: Api) -> None:
    import httpx

    await api.sign_in()
    other = httpx.AsyncClient(transport=api.http._transport, base_url="http://127.0.0.1:8787")  # noqa: SLF001
    assert (await other.post("/api/login", json={"token": api.auth.token})).status_code == 200
    assert (await other.get("/api/threads")).status_code == 200
    r = await api.send("POST", "/api/session/revoke-all")
    api.csrf = r.json()["csrf"]
    assert (await other.get("/api/threads")).status_code == 401
    assert (await api.get("/api/threads")).status_code == 200      # this browser stays signed in
    await other.aclose()


async def test_replacing_the_token_signs_out_others_and_the_old_token_stops_working(api: Api) -> None:
    await api.sign_in()
    old = api.auth.token
    r = await api.send("POST", "/api/session/token")
    new = r.json()["token"]
    assert new != old and api.auth.check_token(new) and not api.auth.check_token(old)
    assert (await api.http.post("/api/login", json={"token": old})).status_code == 401


# ---- doing work --------------------------------------------------------------------------------------
async def test_a_question_is_answered_through_the_real_router_and_provider(api: Api) -> None:
    await api.sign_in()
    api.provider.replies = [plan(answer="Four.")]
    r = await api.send("POST", "/api/tasks", {"goal": "What is 2+2?"})
    assert r.status_code == 202
    done = await api.finished(r.json()["task"]["id"])
    assert done["task"]["state"] == "DONE" and done["task"]["answer"] == "Four."
    thread = (await api.get(f"/api/threads/{done['task']['conversation_id']}")).json()
    assert [m["role"] for m in thread["messages"]] == ["user", "assistant"]
    assert thread["messages"][1]["content"] == "Four."
    sent = api.provider.requests[0]
    assert sent["model"] == "mistral-small-latest"
    assert (await api.get("/api/tasks/" + done["task"]["id"] + "/verify")).json() == {"intact": True}
    first = (await api.get("/api/models")).json()["models"][0]
    assert first["name"] == "mistral-small" and first["breaker"] == "closed" and first["last_error"] is None


async def test_writing_a_file_waits_for_approval_and_only_then_happens(api: Api) -> None:
    await api.sign_in()
    current = settings_to_dict(api.runtime.settings)
    current["file_roots"] = [str(api.shared)]
    assert (await api.send("PUT", "/api/settings", current)).status_code == 200
    agent = (await api.send("POST", "/api/agents", {"name": "Writer", "mode": 1, "files_allowed": True})).json()["agent"]
    target = api.shared / "hello.txt"
    api.provider.replies = [
        plan(step("s1", "fs.write", path=str(target), content="hi"), step("s2", "llm.work", task="say done", input="$s1.output")),
        "Done: wrote hello.txt",
    ]
    task = (await api.send("POST", "/api/tasks", {"goal": "write hello", "agent_id": agent["id"]})).json()["task"]
    pending = await api.approval()
    assert pending["kind"] == "step" and not target.exists()
    wrong = await api.send("POST", f"/api/approvals/{pending['id']}/decide", {"approve": True, "payload_hash": "0" * 64})
    assert wrong.status_code == 409 and not target.exists()
    ok = await api.send("POST", f"/api/approvals/{pending['id']}/decide",
                        {"approve": True, "payload_hash": pending["payload_hash"]})
    assert ok.status_code == 200
    done = await api.finished(task["id"])
    assert done["task"]["state"] == "DONE" and target.read_text() == "hi"
    again = await api.send("POST", f"/api/approvals/{pending['id']}/decide",
                           {"approve": True, "payload_hash": pending["payload_hash"]})
    assert again.status_code == 404                      # single use


async def test_declining_stops_the_task_and_the_kill_switch_stops_everything(api: Api) -> None:
    await api.sign_in()
    current = settings_to_dict(api.runtime.settings)
    current["file_roots"] = [str(api.shared)]
    await api.send("PUT", "/api/settings", current)
    agent = (await api.send("POST", "/api/agents", {"name": "W", "mode": 1, "files_allowed": True})).json()["agent"]
    target = str(api.shared / "no.txt")
    api.provider.replies = [plan(step("s1", "fs.write", path=target, content="x"), step("s2", "llm.work", task="t", input="i"))]
    task = (await api.send("POST", "/api/tasks", {"goal": "write", "agent_id": agent["id"]})).json()["task"]
    pending = await api.approval()
    await api.send("POST", f"/api/approvals/{pending['id']}/decide", {"approve": False, "payload_hash": pending["payload_hash"]})
    assert (await api.finished(task["id"]))["task"]["state"] == "CANCELLED" and not Path(target).exists()

    api.provider.replies = [plan(step("s1", "fs.write", path=target, content="x"), step("s2", "llm.work", task="t", input="i"))]
    task2 = (await api.send("POST", "/api/tasks", {"goal": "write again", "agent_id": agent["id"]})).json()["task"]
    await api.approval()
    assert (await api.send("POST", "/api/stop")).json()["stopped"] == 1
    assert (await api.finished(task2["id"]))["task"]["state"] == "CANCELLED"


async def test_a_bad_request_is_a_clear_400_not_a_crash(api: Api) -> None:
    await api.sign_in()
    assert (await api.send("POST", "/api/tasks", {"goal": ""})).status_code == 400
    assert (await api.send("POST", "/api/tasks", {"goal": "x", "skill": "nope"})).status_code == 404
    assert (await api.send("POST", "/api/tasks", {"goal": "x", "params": {"a": 1}})).status_code == 400
    assert (await api.http.post("/api/tasks", content=b"{not json", headers=api.headers())).status_code == 400
    assert (await api.get("/api/tasks/missing")).status_code == 404


# ---- settings, keys, data -------------------------------------------------------------------------
async def test_settings_round_trip_and_reject_secrets_and_bad_values(api: Api) -> None:
    await api.sign_in()
    current = (await api.get("/api/settings")).json()["settings"]
    assert (await api.send("PUT", "/api/settings", current)).status_code == 200
    current["retention_days"] = 30
    current["models"][0]["enabled"] = False
    saved = (await api.send("PUT", "/api/settings", current)).json()["settings"]
    assert saved["retention_days"] == 30 and saved["models"][0]["enabled"] is False
    assert json.loads(api.runtime.paths.settings.read_text())["retention_days"] == 30
    assert (api.runtime.paths.settings.stat().st_mode & 0o777) == 0o600
    bad = dict(current, retention_days=-1)
    assert (await api.send("PUT", "/api/settings", bad)).status_code == 400
    leaky = dict(current, models=[{**current["models"][0], "api_key": "sk-123"}])
    assert (await api.send("PUT", "/api/settings", leaky)).status_code == 400
    too_wide = dict(current, file_roots=["/"])
    assert (await api.send("PUT", "/api/settings", too_wide)).status_code == 400


async def test_keys_are_stored_but_never_returned(api: Api) -> None:
    await api.sign_in()
    listed = (await api.get("/api/keys")).json()
    assert {k["ref"]: k["present"] for k in listed["keys"]} == {"gemini": False, "mistral": True, "openai": False, "openrouter": False}
    assert (await api.send("PUT", "/api/keys/gemini", {"value": "secret-gemini-key"})).status_code == 200
    after = await api.get("/api/keys")
    assert "secret-gemini-key" not in after.text and {k["ref"]: k["present"] for k in after.json()["keys"]}["gemini"]
    for bad in ("caf\u00e9-key", "two\nlines", "tab\tkey"):
        assert (await api.send("PUT", "/api/keys/gemini", {"value": bad})).status_code == 400
    assert (await api.send("PUT", "/api/keys/not-a-provider", {"value": "x"})).status_code == 404
    assert (await api.send("DELETE", "/api/keys/gemini")).status_code == 200
    assert not {k["ref"]: k["present"] for k in (await api.get("/api/keys")).json()["keys"]}["gemini"]


async def test_model_test_reports_success_and_failure(api: Api) -> None:
    await api.sign_in()
    api.provider.replies = ["ok"]
    good = (await api.send("POST", "/api/models/mistral-small/test")).json()
    assert good["ok"] is True
    assert (await api.send("POST", "/api/models/openrouter-free/test")).json() == {
        "ok": False, "error": "no key saved for this model"}


async def test_memory_notes_and_agents_behave(api: Api) -> None:
    await api.sign_in()
    m = (await api.send("POST", "/api/memory", {"text": "Prefers metric units"})).json()["memory"]
    assert (await api.get("/api/memory?q=metric")).json()["memory"][0]["id"] == m["id"]
    assert (await api.send("PATCH", f"/api/memory/{m['id']}", {"text": "Prefers imperial"})).json()["memory"]["text"] == "Prefers imperial"
    assert (await api.send("DELETE", f"/api/memory/{m['id']}")).status_code == 200
    assert (await api.send("DELETE", f"/api/memory/{m['id']}")).status_code == 404
    assert (await api.send("POST", "/api/memory/clear", {})).status_code == 400

    space = (await api.send("POST", "/api/spaces", {"name": "Home"})).json()["space"]
    page = (await api.send("POST", f"/api/spaces/{space['id']}/pages", {"title": "Plan", "content": "paint the fence"})).json()["page"]
    url = f"/api/spaces/{space['id']}/pages/{page['id']}"
    newer = (await api.send("PUT", url, {"revision": 1, "content": "paint the gate"})).json()["page"]
    assert newer["revision"] == 2
    stale = await api.send("PUT", url, {"revision": 1, "content": "lost update"})
    assert stale.status_code == 409 and (await api.get(url)).json()["page"]["content"] == "paint the gate"
    assert (await api.get("/api/pages?q=gate")).json()["pages"][0]["id"] == page["id"]

    agent = (await api.send("POST", "/api/agents", {"name": "Reader", "instructions": "Be brief.", "mode": 0})).json()["agent"]
    assert (await api.send("PATCH", f"/api/agents/{agent['id']}", {"files_allowed": True})).json()["agent"]["files_allowed"]
    assert (await api.send("POST", "/api/agents", {"name": "Bad", "mode": 9})).status_code == 400


async def test_export_backup_and_system_info(api: Api) -> None:
    await api.sign_in()
    await api.send("POST", "/api/memory", {"text": "likes tea"})
    exported = await api.get("/api/data/export")
    assert "attachment" in exported.headers["content-disposition"]
    data = exported.json()
    assert data["memory"][0]["text"] == "likes tea" and "test-key" not in exported.text
    made = (await api.send("POST", "/api/data/backup")).json()
    assert (api.runtime.paths.backups / made["file"]).exists()
    info = (await api.get("/api/system")).json()
    assert info["maintenance"]["integrity_ok"] is True and info["key_store"]["kind"] == "memory"
    assert info["stats"]["memory"]["total"] > 0


async def test_pets_computer_permission_and_resource_limits(api: Api) -> None:
    await api.sign_in()
    agent = (await api.send("POST", "/api/agents", {"name": "Fox", "pet": "juno", "computer_allowed": True})).json()["agent"]
    assert agent["pet"] == "juno" and agent["computer_allowed"] is True
    plain = (await api.send("POST", "/api/agents", {"name": "Plain"})).json()["agent"]
    assert plain["pet"] == "lily" and plain["computer_allowed"] is False
    assert (await api.send("PATCH", f"/api/agents/{plain['id']}", {"pet": "dragon"})).status_code == 400
    assert (await api.send("PATCH", f"/api/agents/{plain['id']}", {"pet": "otto"})).json()["agent"]["pet"] == "otto"

    res = (await api.get("/api/resources")).json()
    assert res["machine"]["memory"]["total"] > 0 and res["lilly"]["memory_bytes"] > 0
    assert res["limits"] == {"max_running": 3, "step_timeout_s": 180, "task_minutes": 60, "lanes": 3,
                             "local_unload_s": 300}
    assert res["tasks"]["running"] == 0 and res["tasks"]["live"] == []
    assert isinstance(res["models"], list)

    current = (await api.get("/api/settings")).json()["settings"]
    current["limits"] = {"max_running": 2, "step_timeout_s": 60, "task_minutes": 10, "lanes": 2}
    current["modules"] = sorted({*current["modules"], "computer"})
    assert (await api.send("PUT", "/api/settings", current)).status_code == 200
    assert (await api.get("/api/resources")).json()["limits"]["max_running"] == 2
    assert (await api.get("/api/resources")).json()["limits"]["lanes"] == 2
    current["limits"]["max_running"] = 99
    bad = await api.send("PUT", "/api/settings", current)
    assert bad.status_code == 400 and "max_running" in bad.text


async def test_routines_can_be_created_changed_paused_run_and_deleted(api: Api) -> None:
    await api.sign_in()
    good = {"name": "Morning brief", "goal": "Summarise my notes",
            "schedule": {"kind": "at", "at": "08:30", "days": [0, 1, 2, 3, 4]}}
    made = (await api.send("POST", "/api/routines", good)).json()["routine"]
    assert made["when"] == "Weekdays at 08:30" and made["enabled"] and made["next_run"] > api.runtime.clock()
    assert (await api.get("/api/routines")).json()["routines"][0]["id"] == made["id"]

    for bad in ({**good, "schedule": {"kind": "every", "every_minutes": 1}}, {**good, "name": " "},
                {**good, "agent_id": "nope"}):
        assert (await api.send("POST", "/api/routines", bad)).status_code in (400, 404)

    path = f"/api/routines/{made['id']}"
    changed = (await api.send("PATCH", path, {"schedule": {"kind": "every", "every_minutes": 60}})).json()["routine"]
    assert changed["when"] == "Every hour"
    paused = (await api.send("PATCH", path, {"enabled": False})).json()["routine"]
    assert paused["enabled"] is False and paused["next_run"] is None and paused["pause_reason"] == "paused by you"
    resumed = (await api.send("PATCH", path, {"enabled": True})).json()["routine"]
    assert resumed["enabled"] and resumed["next_run"] and resumed["pause_reason"] is None

    api.provider.replies.append(plan(answer="Here is your brief."))
    started = await api.send("POST", f"{path}/run")
    assert started.status_code == 202
    assert (await api.finished(started.json()["task"]["id"]))["task"]["answer"] == "Here is your brief."

    assert (await api.send("DELETE", path)).status_code == 200
    assert (await api.send("DELETE", path)).status_code == 404


async def test_stop_all_pauses_routines_so_nothing_restarts_by_itself(api: Api) -> None:
    await api.sign_in()
    body = {"name": "Hourly", "goal": "Check disk", "schedule": {"kind": "every", "every_minutes": 60}}
    await api.send("POST", "/api/routines", body)
    stopped = (await api.send("POST", "/api/stop")).json()
    assert stopped["routines_paused"] == 1
    paused = (await api.get("/api/routines")).json()["routines"][0]
    assert paused["enabled"] is False and paused["pause_reason"] == "paused by Stop all"


async def test_a_finished_task_carries_its_plan_with_dependencies_and_verdicts(api: Api) -> None:
    await api.sign_in()
    api.provider.replies = [plan(step("s1", "system.stats"),
                                 step("s2", "llm.work", task="summarise", input="$s1.output")), "All fine."]
    r = await api.send("POST", "/api/tasks", {"goal": "how is my computer doing?"})
    done = await api.finished(r.json()["task"]["id"])
    steps = done["plan_steps"]
    assert [s["id"] for s in steps] == ["s1", "s2"]
    assert steps[1]["deps"] == ["s1"] and steps[0]["deps"] == []
    assert {s["verdict"] for s in steps} <= {"ALLOW", "NEEDS_APPROVAL", "DENY"} and steps[0]["why"]
    assert [s["status"] for s in done["steps"]] == ["done", "done"]


async def test_a_task_without_a_plan_has_none(api: Api) -> None:
    await api.sign_in()
    api.provider.replies = [plan(answer="Four.")]
    done = await api.finished((await api.send("POST", "/api/tasks", {"goal": "2+2?"})).json()["task"]["id"])
    assert done["plan_steps"] == []


async def test_presets_are_listed_applied_and_only_known_names_work(api: Api) -> None:
    assert (await api.get("/api/presets")).status_code == 401
    await api.sign_in()
    names = [p["name"] for p in (await api.get("/api/presets")).json()["presets"]]
    assert names == ["low-resource", "balanced", "fast", "careful"]
    done = await api.send("POST", "/api/presets", {"name": "low-resource"})
    assert done.status_code == 200 and done.json()["settings"]["limits"]["max_running"] == 1
    assert api.runtime.settings.limits.max_running == 1
    assert (await api.send("POST", "/api/presets", {"name": "yolo"})).status_code == 400


async def test_pets_carry_a_look_skills_and_a_model(api: Api) -> None:
    await api.sign_in()
    model = (await api.get("/api/models")).json()["models"][0]["name"]
    look = {"hue": 120, "accessory": "crown", "eyes": "sparkle", "blush": False}
    made = (await api.send("POST", "/api/agents", {"name": "Fox", "look": look, "skills": "# Skills\nDo X.",
                                                  "model": model})).json()["agent"]
    assert (made["look"], made["skills"], made["model"]) == (look, "# Skills\nDo X.", model)
    plain = (await api.send("POST", "/api/agents", {"name": "Plain"})).json()["agent"]
    assert plain["look"] == {"hue": None, "accessory": "none", "eyes": "round", "blush": True}
    assert (plain["skills"], plain["model"]) == ("", "")
    listed = {a["id"]: a for a in (await api.get("/api/agents")).json()["agents"]}
    assert listed[made["id"]]["look"] == look

    # an update changes only what it carries; "" returns a pet to automatic routing
    patched = (await api.send("PATCH", f"/api/agents/{made['id']}", {"look": {"hue": 7}, "model": ""})).json()["agent"]
    assert patched["look"] == {"hue": 7, "accessory": "none", "eyes": "round", "blush": True}
    assert (patched["skills"], patched["model"]) == ("# Skills\nDo X.", "")


@pytest.mark.parametrize("bad", [
    {"look": {"hue": 360}}, {"look": {"hue": True}}, {"look": {"accessory": "tiara"}},
    {"look": {"sparkles": 1}}, {"look": "red"}, {"look": None, "skills": 5},
    {"skills": "x" * 6001}, {"model": "no-such-model"}, {"model": 3},
])
async def test_bad_pet_fields_are_a_400_on_create_and_update(api: Api, bad: dict[str, object]) -> None:
    await api.sign_in()
    plain = (await api.send("POST", "/api/agents", {"name": "Plain"})).json()["agent"]
    assert (await api.send("POST", "/api/agents", {"name": "Bad", **bad})).status_code == 400
    assert (await api.send("PATCH", f"/api/agents/{plain['id']}", bad)).status_code == 400
    assert len((await api.get("/api/agents")).json()["agents"]) == 1


async def test_pet_fields_need_a_session(api: Api) -> None:
    r = await api.http.post("/api/agents", json={"name": "Fox", "look": {"hue": 1}})
    assert r.status_code == 401


async def test_the_export_keeps_everything_that_defines_an_agent_and_the_routines(api: Api) -> None:
    await api.sign_in()
    created = await api.send("POST", "/api/agents", {"name": "Pip", "instructions": "be brief", "mode": 1, "skills": "# how I work",
                                             "research_allowed": True})
    assert created.status_code in (200, 201), created.text
    await api.send("POST", "/api/routines", {"name": "Morning", "goal": "say hi", "schedule": {"kind": "every", "every_minutes": 60}})
    data = (await api.get("/api/data/export")).json()
    agent = next(a for a in data["agents"] if a["name"] == "Pip")
    assert agent["skills"] == "# how I work" and agent["allowed"]["research_allowed"] is True
    assert {"pet", "look", "model"} <= agent.keys()
    assert data["routines"][0]["name"] == "Morning" and data["routines"][0]["schedule"]["every_minutes"] == 60
