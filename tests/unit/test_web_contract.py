"""The interface and the server agree: every call the interface makes has a route, and the TypeScript types
name exactly the fields the server sends. These fail the build when one side changes without the other."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from lilly.app.laya import LayaService
from lilly.domain.settings import default_settings, settings_to_dict
from lilly.ui.app import api_routes

WEB = Path(__file__).parents[2] / "web" / "src"
TYPES = (WEB / "types.ts").read_text()
CALL = re.compile(r"api\.(get|post|put|patch|del)(?:<[^>]*>)?\(\s*([`'\"])(.*?)\2")
METHOD = {"get": "GET", "post": "POST", "put": "PUT", "patch": "PATCH", "del": "DELETE"}


def _routes() -> set[tuple[str, str]]:
    found = set()
    for route in api_routes():
        for method in route.methods or ():
            if method != "HEAD":
                found.add((method, re.sub(r"\{[^}]*\}", "{x}", route.path)))
    return found


def _calls() -> set[tuple[str, str, str]]:
    found = set()
    for file in WEB.rglob("*.ts*"):
        for m in CALL.finditer(file.read_text()):
            path = re.sub(r"\$\{[^}]*\}", "{x}", m.group(3)).split("?")[0]
            found.add((METHOD[m.group(1)], path, file.name))
    return found


def test_every_call_the_interface_makes_has_a_route() -> None:
    routes = _routes()
    missing = sorted(f"{method} {path} ({file})" for method, path, file in _calls() if (method, path) not in routes)
    assert not missing, "the interface calls routes that do not exist: " + ", ".join(missing)


def _fields(interface: str) -> set[str]:
    """Top-level field names of `interface Name { ... }` in types.ts, whatever its layout."""
    start = TYPES.find(f"interface {interface} ")
    assert start >= 0, f"interface {interface} is missing from types.ts"
    open_at = TYPES.index("{", start)
    depth, top, current = 0, [], ""
    for ch in TYPES[open_at:]:
        if ch in "{[(":
            depth += 1
            if depth == 1:
                continue
        elif ch in "}])":
            depth -= 1
            if depth == 0:
                break
        if depth == 1:                      # only what sits directly inside the body, not nested types
            current += ch
    for part in re.split(r"[;\n]", current):
        top.extend(re.findall(r"(?:^|\s)(\w+)\??\s*:", part))
    return set(top)


def test_settings_types_match_what_the_server_sends() -> None:
    sent = settings_to_dict(default_settings())
    assert _fields("Settings") == set(sent)
    assert _fields("Limits") == set(sent["limits"])
    assert _fields("DecisionSettings") == set(sent["decisions"])
    assert _fields("KindSettings") == set(sent["decisions"]["tools"])
    assert _fields("BrowserSettings") == set(sent["browser"])
    assert _fields("BridgeSettings") == set(sent["bridges"])
    assert _fields("DevboxSettings") == set(sent["devbox"])


async def test_laya_and_plan_types_match_the_server(tmp_path: Path) -> None:
    status = LayaService(tmp_path / "laya").status()
    from lilly.domain.decisions import laya_kinds
    sent = {**status, "enabled_for": list(laya_kinds(default_settings().decisions))}
    assert _fields("LayaStatus") == set(sent)


def test_laya_setup_types_match_what_the_server_sends() -> None:
    from dataclasses import asdict

    from lilly.decide.laya_install import Check
    from lilly.decide.laya_selftest import CaseResult, Report

    assert _fields("LayaCheck") == set(asdict(Check("n", True, "d")))
    case = CaseResult("n", "yes", "yes", 0.9, 1, True)
    assert _fields("LayaTestCase") == set(asdict(case))
    assert _fields("LayaTestReport") == set(asdict(Report(True, True, 1, (case,), None)))


@pytest.mark.parametrize("name", ["PlanStep"])
def test_plan_step_type_names_what_the_runner_announces(name: str) -> None:
    runner = (Path(__file__).parents[2] / "src" / "lilly" / "engine" / "runner.py").read_text()
    announced = set(re.findall(r'"(\w+)": ', re.search(r"steps = \[\{(.*?)\}\n", runner, re.S).group(1)))  # type: ignore[union-attr]
    assert _fields(name) == announced
