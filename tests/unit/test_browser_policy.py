"""The browser rules as pure functions: targets, sites, modes, settings, and the network guard."""
from __future__ import annotations

import pytest

from lilly.domain.browser_policy import (
    Action,
    BrowserMode,
    BrowserSettings,
    browser_to_dict,
    check_url,
    host_allowed,
    judge,
    parse_browser,
    parse_target,
)
from lilly.domain.labels import Verdict
from lilly.domain.settings import MODULES, default_settings, parse_settings, settings_to_dict
from lilly.tools.browser import guard as guard_module
from lilly.tools.browser.chrome import find_browser
from lilly.tools.browser.guard import NetworkGuard

RISKY = ["Buy now", "Delete account", "Sign in", "Log in", "Place order", "Send", "Confirm payment", "Unsubscribe",
         "Accept all", "Download", "Publish post"]
SAFE = ["More info", "Next page", "Show details", "Close", "Home", "Search box", "Read more"]


def test_a_target_is_parsed_only_when_it_is_exactly_the_agreed_line() -> None:
    t = parse_target('s12.e7 button "Sign in" @example.com')
    assert t is not None and (t.snapshot, t.ref, t.role, t.name, t.host) == (12, 7, "button", "Sign in", "example.com")
    assert parse_target('s1.e0 link "" @localhost:8080') is not None
    for bad in ('s1.e0 button "x" @', 's1.e0 BUTTON "x" @a.com', 's1.e0 button "x" @a.com extra', "click it", None, 3,
                's1.e0 button "a\nb" @a.com', 's1.e0 button "x" @A.com', 's1.e0 button "x" @a.com/path'):
        assert parse_target(bad) is None


@pytest.mark.parametrize("host,allow,ok", [("example.com", ["example.com"], True), ("www.example.com", ["example.com"], True),
                                           ("example.com:8080", ["example.com"], True), ("badexample.com", ["example.com"], False),
                                           ("example.com.evil.io", ["example.com"], False), ("example.com", [], False)])
def test_a_site_matches_itself_and_its_subdomains_only(host: str, allow: list[str], ok: bool) -> None:
    assert host_allowed(host, allow) is ok


def test_ask_every_asks_for_everything_except_reading() -> None:
    cfg = BrowserSettings()
    for a in (Action.INTERACT, Action.TYPE, Action.PRESS, Action.SUBMIT):
        assert judge(a, "button", "More info", "a.com", cfg)[0] is Verdict.NEEDS_APPROVAL
    assert judge(Action.READ, "", "", "a.com", cfg)[0] is Verdict.ALLOW


def test_ask_risky_lets_plain_clicks_through_and_stops_the_risky_ones() -> None:
    cfg = BrowserSettings(mode=BrowserMode.ASK_RISKY)
    assert all(judge(Action.INTERACT, "button", n, "a.com", cfg)[0] is Verdict.ALLOW for n in SAFE)
    assert all(judge(Action.INTERACT, "button", n, "a.com", cfg)[0] is Verdict.NEEDS_APPROVAL for n in RISKY)
    assert judge(Action.SUBMIT, "submit", "Go", "a.com", cfg)[0] is Verdict.NEEDS_APPROVAL
    assert judge(Action.PRESS, "", "Enter", "a.com", cfg)[0] is Verdict.NEEDS_APPROVAL
    assert judge(Action.TYPE, "textbox", "Search", "a.com", cfg)[0] is Verdict.ALLOW


def test_allowlist_lets_everything_through_on_listed_sites_only() -> None:
    cfg = BrowserSettings(mode=BrowserMode.ALLOWLIST, allow_hosts=("shop.example",))
    assert judge(Action.SUBMIT, "submit", "Buy", "www.shop.example", cfg)[0] is Verdict.ALLOW
    assert judge(Action.SUBMIT, "submit", "Buy", "evil.example", cfg)[0] is Verdict.NEEDS_APPROVAL


@pytest.mark.parametrize("mode", list(BrowserMode))
def test_passwords_and_cards_are_refused_in_every_mode(mode: BrowserMode) -> None:
    cfg = BrowserSettings(mode=mode, allow_hosts=("a.com",))
    for role in ("password", "card"):
        assert judge(Action.TYPE, role, "x", "a.com", cfg)[0] is Verdict.DENY


@pytest.mark.parametrize("url,ok", [("https://example.com/a?b=1", True), ("http://localhost:8080/", True),
                                    ("file:///etc/passwd", False), ("javascript:alert(1)", False),
                                    ("https://user:pw@example.com/", False), ("https://exa mple.com", False),
                                    ("ftp://example.com", False), ("https://example.com/\n", False), ("x" * 3000, False)])
def test_only_plain_web_addresses_may_be_opened(url: str, ok: bool) -> None:
    assert (check_url(url) is None) is ok


def test_browser_settings_round_trip_and_reject_nonsense() -> None:
    cfg = BrowserSettings(mode=BrowserMode.ALLOWLIST, allow_hosts=("a.com", "b.org"), max_actions=10, idle_quit_s=60,
                          headless=False, chrome_path="/x/chrome")
    parsed, errs = parse_browser(browser_to_dict(cfg))
    assert errs == [] and parsed == cfg
    assert parse_browser({})[0] == BrowserSettings()
    for bad in ({"mode": "yolo"}, {"allow_hosts": ["A.com"]}, {"allow_hosts": ["a.com/path"]}, {"max_actions": 0},
                {"max_actions": True}, {"idle_quit_s": 5}, {"headless": "yes"}, {"chrome_path": 5}, {"extra": 1}, "x"):
        value, errs = parse_browser(bad)
        assert value is None and errs
    assert "browser" in MODULES and "browser" not in default_settings().modules     # off until switched on


def test_the_browser_section_is_part_of_the_saved_settings() -> None:
    s = default_settings()
    raw = settings_to_dict(s)
    assert raw["browser"]["mode"] == "ask_every"
    raw["browser"] = {"mode": "ask_risky"}
    parsed, errs = parse_settings(raw)
    assert errs == [] and parsed is not None and parsed.browser.mode is BrowserMode.ASK_RISKY
    raw["browser"] = {"mode": "wild"}
    assert parse_settings(raw)[0] is None


# ---- the network guard ---------------------------------------------------------------------------
async def test_the_guard_allows_public_addresses_and_refuses_the_rest() -> None:
    table = {"public.example": ["93.184.216.34"], "inside.example": ["10.0.0.5"], "mixed.example": ["93.184.216.34", "127.0.0.1"],
             "v6.example": ["2606:2800:220:1::1"], "none.example": []}
    g = NetworkGuard(lambda host: table.get(host, []))
    assert await g.refusal("https://public.example/", "Document") is None
    assert await g.refusal("https://v6.example/", "Document") is None
    for blocked in ("https://inside.example/", "https://mixed.example/", "http://127.0.0.1/", "http://[::1]/",
                    "http://169.254.169.254/latest", "https://none.example/", "http://0.0.0.0/", "http://192.168.1.1/"):
        assert await g.refusal(blocked, "Document") == "that address is not on the public internet"


async def test_the_guard_refuses_other_schemes_but_lets_inline_images_through() -> None:
    g = NetworkGuard(lambda host: ["93.184.216.34"])
    assert await g.refusal("file:///etc/passwd", "Document") == "only http and https pages can be opened"
    assert await g.refusal("chrome://settings", "Document")
    assert await g.refusal("data:text/html,<b>x</b>", "Document")
    assert await g.refusal("data:image/png;base64,AAAA", "Image") is None
    assert await g.refusal("about:blank", "Document") is None


async def test_the_guard_remembers_answers_briefly_and_stays_small(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def resolver(host: str) -> list[str]:
        calls.append(host)
        return ["93.184.216.34"]

    g = NetworkGuard(resolver)
    await g.refusal("https://a.example/", "Document")
    await g.refusal("https://a.example/x", "Image")
    assert calls == ["a.example"]
    monkeypatch.setattr(guard_module, "CACHE_ENTRIES", 3)
    for i in range(10):
        await g.refusal(f"https://h{i}.example/", "Document")
    assert len(g._seen) == 3


def test_the_system_resolver_returns_addresses_or_nothing() -> None:
    assert guard_module.system_resolver("localhost")
    assert guard_module.system_resolver("no-such-host.invalid") == []


def test_finding_the_browser_prefers_what_you_configured(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    from lilly.domain.errors import ToolError

    exe = tmp_path / "mychrome"  # type: ignore[operator]
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    assert find_browser(str(exe), {}) == str(exe)
    assert find_browser("", {"LILLY_CHROME": str(exe)}) == str(exe)
    with pytest.raises(ToolError, match="not found"):
        find_browser("/nope/chrome", {})
    monkeypatch.setattr("lilly.tools.browser.chrome.shutil.which", lambda n: None)
    monkeypatch.setattr("lilly.tools.browser.chrome._PLACES", ())
    with pytest.raises(ToolError, match="no Chrome"):
        find_browser("", {})
    monkeypatch.setattr("lilly.tools.browser.chrome.shutil.which", lambda n: "/usr/bin/chromium" if n == "chromium" else None)
    assert find_browser("", {}) == "/usr/bin/chromium"
