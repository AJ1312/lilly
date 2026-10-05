"""Rules for the agent's browser: what each action is, when it needs your approval, and when you have chosen to
let it go ahead on its own. Pure functions, no browser, no network.

An action names an element by a *target*: `s12.e7 button "Sign in" @example.com`, made by the page snapshot. It carries
the role, the visible name and the site, so what you are asked to approve is exactly what will be clicked.

Modes (chosen in Settings, default ask_every):
  ask_every   every click, key press and typed text asks first.
  ask_risky   plain navigation inside a page goes ahead; anything that could send, buy, delete, sign in or change
              an account asks first, and so does every form submit.
  allowlist   everything goes ahead on the sites you listed (submits included) and asks anywhere else.
In every mode: passwords and payment-card fields are never typed by the agent, file uploads and downloads are
refused, and reading a page is allowed (what it returns is untrusted text)."""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from lilly.domain.labels import Verdict


class BrowserMode(StrEnum):
    ASK_EVERY = "ask_every"
    ASK_RISKY = "ask_risky"
    ALLOWLIST = "allowlist"


class Action(StrEnum):
    READ = "read"          # open, read, find, scroll, back, close
    INTERACT = "interact"  # click, select
    TYPE = "type"          # typed text
    PRESS = "press"        # a key (Enter can submit)
    SUBMIT = "submit"      # a form submit


HOST = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
TARGET = re.compile(r'^s(\d{1,6})\.e(\d{1,5}) ([a-z]{1,20}) "([^"\n]{0,80})" @([a-z0-9.\-]{1,253}(?::\d{1,5})?)$')
RISKY_NAME = re.compile(
    r"\b(buy|purchase|pay|order|checkout|check out|place|confirm|delete|remove|erase|cancel|unsubscribe|subscribe|"
    r"sign ?in|log ?in|sign ?up|register|send|post|publish|share|transfer|withdraw|donate|accept|agree|approve|"
    r"authorize|grant|allow|install|download|upload|reset|save|apply|submit|book|reserve)\b", re.IGNORECASE)
SENSITIVE_ROLES = frozenset({"password", "card"})   # fields the agent never types into
KEYS = frozenset({"Enter", "Tab", "Escape", "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "PageDown",
                      "PageUp", "Home", "End", "Backspace", "Space"})


@dataclass(frozen=True, slots=True)
class Target:
    snapshot: int
    ref: int
    role: str
    name: str
    host: str


@dataclass(frozen=True, slots=True)
class BrowserSettings:
    """Off until the `browser` module is switched on. Defaults ask about everything."""

    mode: BrowserMode = BrowserMode.ASK_EVERY
    allow_hosts: tuple[str, ...] = ()      # sites the agent may act on without asking in allowlist mode
    max_actions: int = 40                  # clicks, keys and typed texts in one task
    idle_quit_s: int = 300                 # the browser quits after this long unused
    headless: bool = True
    chrome_path: str = ""                  # empty: look for Chrome, Chromium, Edge or Brave


BROWSER_BOUNDS = {"max_actions": (1, 500), "idle_quit_s": (30, 3600)}


def parse_target(text: object) -> Target | None:
    m = TARGET.fullmatch(text.strip()) if isinstance(text, str) else None
    return Target(int(m[1]), int(m[2]), m[3], m[4], m[5]) if m else None


def host_allowed(host: str, allow: Sequence[str]) -> bool:
    """The host, or a subdomain of it, is on the list. Ports are ignored; an empty list allows nothing."""
    bare = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return any(bare == a or bare.endswith("." + a) for a in allow)


def judge(action: Action, role: str, name: str, host: str, cfg: BrowserSettings) -> tuple[Verdict, str]:
    """Whether this action may go ahead. `role` and `name` describe the element ("" for a key press)."""
    if action is Action.READ:
        return Verdict.ALLOW, "ok"
    if action is Action.TYPE and role in SENSITIVE_ROLES:
        return Verdict.DENY, "the agent never types into password or card fields; use take-over to type them yourself"
    where = f"on {host}" if host else "on this page"
    if cfg.mode is BrowserMode.ASK_EVERY:
        return Verdict.NEEDS_APPROVAL, f"browser action {where} (every action asks)"
    if cfg.mode is BrowserMode.ALLOWLIST:
        if host_allowed(host, cfg.allow_hosts):
            return Verdict.ALLOW, "ok"
        return Verdict.NEEDS_APPROVAL, f"browser action {where}, which is not on your list of trusted sites"
    assert cfg.mode is BrowserMode.ASK_RISKY
    if action in (Action.SUBMIT, Action.PRESS):
        return Verdict.NEEDS_APPROVAL, f"sends a form or presses a key {where}"
    if RISKY_NAME.search(name):
        return Verdict.NEEDS_APPROVAL, f"could send, buy, delete or sign in {where}"
    return Verdict.ALLOW, "ok"


def check_url(url: str) -> str | None:
    """Why this address may not be opened, or None. Only plain http(s); the network side is checked at run time."""
    if len(url) > 2000 or any(c in url for c in "\x00\r\n\t "):
        return "that is not a valid address"
    m = re.fullmatch(r"(https?)://([^/?#:@]+)(?::(\d{1,5}))?(?:[/?#].*)?", url, re.IGNORECASE)
    if m is None:
        return "only plain http and https addresses (without a user name) can be opened"
    return None


def parse_browser(raw: object) -> tuple[BrowserSettings | None, list[str]]:
    """Validate the `browser` settings. Returns (settings, []) or (None, problems)."""
    if not isinstance(raw, dict):
        return None, ["browser must be an object"]
    errs = [f"browser: unknown setting {k!r}" for k in sorted(raw.keys() - {
        "mode", "allow_hosts", "max_actions", "idle_quit_s", "headless", "chrome_path"})]
    d = BrowserSettings()
    try:
        mode = BrowserMode(raw.get("mode", d.mode.value))
    except ValueError:
        errs.append("browser.mode must be ask_every, ask_risky or allowlist")
        mode = d.mode
    hosts = raw.get("allow_hosts", [])
    if not isinstance(hosts, list | tuple) or not all(isinstance(h, str) and HOST.fullmatch(h) for h in hosts) \
            or len(hosts) > 100:
        errs.append("browser.allow_hosts must be a list of up to 100 lower-case site names without ports or paths")
        hosts = []
    numbers = {}
    for key, (lo, hi) in BROWSER_BOUNDS.items():
        v = raw.get(key, getattr(d, key))
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            errs.append(f"browser.{key} must be a whole number from {lo} to {hi}")
        else:
            numbers[key] = v
    headless, path = raw.get("headless", True), raw.get("chrome_path", "")
    if not isinstance(headless, bool):
        errs.append("browser.headless must be true or false")
    if not isinstance(path, str) or len(path) > 1000 or "\x00" in path:
        errs.append("browser.chrome_path must be a file path")
    if errs:
        return None, errs
    return BrowserSettings(mode, tuple(dict.fromkeys(hosts)), headless=headless, chrome_path=path, **numbers), []


def browser_to_dict(b: BrowserSettings) -> dict[str, object]:
    return {"mode": b.mode.value, "allow_hosts": list(b.allow_hosts), "max_actions": b.max_actions,
            "idle_quit_s": b.idle_quit_s, "headless": b.headless, "chrome_path": b.chrome_path}
