"""The Laya endpoints, and the running app picking Laya up without a restart."""
from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from lilly.app.laya import LayaService
from lilly.decide import laya_install
from lilly.decide.laya_decider import LayaDecider
from lilly.decide.laya_pins import LAYA_VERSION, REVISION
from lilly.domain.decisions import Kind
from tests.integration.conftest import Api
from tests.unit.test_laya_decider import decider as stub_decider

pytestmark = pytest.mark.asyncio


def finished_install(addon: Path, say: Any) -> None:
    """What a successful install leaves behind (the real one is tested on its own)."""
    say("Downloading model.safetensors")
    py = laya_install.python_of(addon)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("")
    (addon / laya_install.MARKER).write_text(json.dumps({"revision": REVISION, "laya": LAYA_VERSION}))


def failing_install(addon: Path, say: Any) -> None:
    raise laya_install.LayaInstallError("pip could not install Laya on this computer: no matching distribution")


async def finished(api: Api) -> dict[str, Any]:
    for _ in range(200):
        body = (await api.get("/api/laya")).json()
        if not body["installing"]:
            return body  # type: ignore[no-any-return]
        await asyncio.sleep(0.02)
    raise AssertionError("the install never finished")


def use(api: Api, tmp_path: Path, installer: Any) -> None:
    api.runtime.laya = LayaService(tmp_path / "laya", installer)


async def test_laya_endpoints_need_a_session(api: Api) -> None:
    assert (await api.http.get("/api/laya")).status_code == 401
    assert (await api.http.post("/api/laya/install", json={})).status_code == 401
    assert (await api.http.put("/api/laya/enabled", json={"enabled": True})).status_code == 401
    assert (await api.http.delete("/api/laya")).status_code == 401


async def test_it_starts_absent_and_cannot_be_turned_on(api: Api, tmp_path: Path) -> None:
    await api.sign_in()
    use(api, tmp_path, finished_install)
    body = (await api.get("/api/laya")).json()
    assert body["installed"] is False and body["installing"] is False and body["enabled_for"] == []
    assert body["download_mb"] > 500 and body["worker"] == "off"
    r = await api.send("PUT", "/api/laya/enabled", {"enabled": True})
    assert r.status_code == 409 and "not installed" in r.json()["error"]


async def test_installing_then_turning_on_works_without_a_restart(api: Api, tmp_path: Path) -> None:
    await api.sign_in()
    use(api, tmp_path, finished_install)
    assert "laya" not in api.runtime._deciders()
    assert (await api.send("POST", "/api/laya/install", {})).status_code == 202
    body = await finished(api)
    assert body["installed"] is True and body["error"] is None and "Downloading model.safetensors" in body["progress"]
    assert "laya" in api.runtime._deciders()
    on = (await api.send("PUT", "/api/laya/enabled", {"enabled": True})).json()
    assert set(on["enabled_for"]) == {"loop", "instructions", "pick"}
    assert {s.decider for s in api.runtime.settings.decisions.for_kind(Kind.LOOP).chain} >= {"laya"}
    off = (await api.send("PUT", "/api/laya/enabled", {"enabled": False})).json()
    assert off["enabled_for"] == [] and off["installed"] is True


async def test_a_failed_install_says_why_and_can_be_retried(api: Api, tmp_path: Path) -> None:
    await api.sign_in()
    use(api, tmp_path, failing_install)
    await api.send("POST", "/api/laya/install", {})
    body = await finished(api)
    assert body["installed"] is False and "no matching distribution" in body["error"]
    use(api, tmp_path, finished_install)
    await api.send("POST", "/api/laya/install", {})
    assert (await finished(api))["error"] is None


async def test_one_install_at_a_time_and_remove_waits_for_it(api: Api, tmp_path: Path) -> None:
    await api.sign_in()
    gate = threading.Event()

    def slow(addon: Path, say: Any) -> None:
        gate.wait(5)
        finished_install(addon, say)

    use(api, tmp_path, slow)
    await api.send("POST", "/api/laya/install", {})
    assert (await api.send("POST", "/api/laya/install", {})).status_code == 409
    assert (await api.send("DELETE", "/api/laya")).status_code == 409
    gate.set()
    assert (await finished(api))["installed"] is True


async def test_remove_deletes_the_files_and_turns_it_off(api: Api, tmp_path: Path) -> None:
    await api.sign_in()
    use(api, tmp_path, finished_install)
    await api.send("POST", "/api/laya/install", {})
    await finished(api)
    await api.send("PUT", "/api/laya/enabled", {"enabled": True})
    r = await api.send("DELETE", "/api/laya")
    body = r.json()
    assert r.status_code == 200 and body["installed"] is False and body["enabled_for"] == []
    assert not (tmp_path / "laya").exists() and "laya" not in api.runtime._deciders()


async def test_enabled_must_be_a_boolean(api: Api) -> None:
    await api.sign_in()
    assert (await api.send("PUT", "/api/laya/enabled", {"enabled": "yes"})).status_code == 400


# ---- the pre-check and the self-test --------------------------------------------------------------------
GOOD = [laya_install.Check("This computer", True, "Linux (x86_64)"), laya_install.Check("Disk space", True, "50.0 GB free")]


def set_up(api: Api, tmp_path: Path, *, installed: bool = True, checks: list[laya_install.Check] | None = None,
           maker: Any = None) -> None:
    addon = tmp_path / "laya"
    if installed:
        finished_install(addon, lambda line: None)
    api.runtime.laya = LayaService(addon, finished_install, checker=lambda path: checks or GOOD,
                                   maker=maker or (lambda path: stub_decider()))


async def test_the_check_and_the_test_need_a_session(api: Api) -> None:
    assert (await api.http.get("/api/laya/check")).status_code == 401
    assert (await api.http.post("/api/laya/test", json={})).status_code == 401


async def test_the_check_lists_what_was_found_and_whether_all_of_it_is_fine(api: Api, tmp_path: Path) -> None:
    await api.sign_in()
    set_up(api, tmp_path, installed=False)
    body = (await api.get("/api/laya/check")).json()
    assert body["ok"] is True and [c["name"] for c in body["checks"]] == ["This computer", "Disk space"]
    assert set(body["checks"][0]) == {"name", "ok", "detail"}
    bad = [*GOOD, laya_install.Check("Python", False, "Laya needs Python 3.10 or newer, and none was found.")]
    set_up(api, tmp_path, installed=False, checks=bad)
    again = (await api.get("/api/laya/check")).json()
    assert again["ok"] is False and again["checks"][-1]["ok"] is False


async def test_the_real_check_runs_without_downloading_anything(api: Api) -> None:
    await api.sign_in()
    body = (await api.get("/api/laya/check")).json()
    assert [c["name"] for c in body["checks"]] == ["This computer", "Python", "Disk space", "Download"]


async def test_testing_needs_laya_installed(api: Api, tmp_path: Path) -> None:
    await api.sign_in()
    set_up(api, tmp_path, installed=False)
    r = await api.send("POST", "/api/laya/test", {})
    assert r.status_code == 409 and "not installed" in r.json()["error"]


async def test_the_test_proves_it_works_and_changes_nothing(api: Api, tmp_path: Path) -> None:
    await api.sign_in()
    made: list[LayaDecider] = []

    def maker(path: Path) -> LayaDecider:
        made.append(stub_decider())
        return made[0]

    set_up(api, tmp_path, maker=maker)
    before = api.runtime.settings.decisions
    r = await api.send("POST", "/api/laya/test", {})
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True and body["loaded"] is True and body["error"] is None
    assert [(x["expected"], x["got"], x["ok"]) for x in body["results"]] == [("yes", "yes", True), ("no", "no", True),
                                                                              ("loop", "loop", True)]
    assert set(body["results"][0]) == {"name", "expected", "got", "confidence", "ms", "ok"} and "load_ms" in body
    assert api.runtime.settings.decisions == before and (await api.get("/api/laya")).json()["enabled_for"] == []
    assert made[0]._proc is None and made[0].state == "off"          # not left loaded


async def test_a_failing_test_is_a_report_not_an_error(api: Api, tmp_path: Path) -> None:
    await api.sign_in()
    set_up(api, tmp_path, maker=lambda path: stub_decider(command=["/definitely/not/a/program"]))
    r = await api.send("POST", "/api/laya/test", {})
    assert r.status_code == 200 and r.json()["ok"] is False and "lilly laya install" in r.json()["error"]


async def test_a_second_test_while_one_is_running_is_refused(api: Api, tmp_path: Path) -> None:
    await api.sign_in()
    set_up(api, tmp_path, maker=lambda path: stub_decider(command=[sys.executable, "-c", "import time; time.sleep(30)"]))
    first = asyncio.create_task(api.send("POST", "/api/laya/test", {}))
    for _ in range(200):
        if api.runtime.laya._testing:
            break
        await asyncio.sleep(0.01)
    second = await api.send("POST", "/api/laya/test", {})
    assert second.status_code == 409 and "already running" in second.json()["error"]
    assert (await api.send("DELETE", "/api/laya")).status_code == 409           # nor can it be removed under the test
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    assert not api.runtime.laya._testing


async def test_a_test_that_could_not_be_made_says_laya_is_not_installed(api: Api, tmp_path: Path) -> None:
    await api.sign_in()
    set_up(api, tmp_path, maker=lambda path: None)
    assert (await api.send("POST", "/api/laya/test", {})).status_code == 409
