"""User-editable settings: models and their order, optional modules, privacy and access.

Everything here is validated before it is saved, and a secret can never be stored in it.
"""
from __future__ import annotations

import contextlib
import ipaddress
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from lilly.domain.bridges import BridgeSettings, bridge_to_dict, parse_bridge
from lilly.domain.browser_policy import BrowserSettings, browser_to_dict, parse_browser
from lilly.domain.caps import Cap
from lilly.domain.decisions import DecisionSettings, decisions_to_dict, parse_decisions
from lilly.domain.devbox import DevboxSettings, devbox_to_dict, parse_devbox
from lilly.domain.labels import Label, Mode

PROVIDERS = frozenset({"mistral", "openrouter", "gemini", "ollama", "openai"})
# Optional features. Each decides which tools or endpoints exist at all.
MODULES = frozenset({"files", "web", "memory", "notes", "skills", "computer", "browser", "devbox"})
SEARCH_ENGINES = frozenset({"duckduckgo", "brave", "searxng"})

_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
_SECRET_KEYS = frozenset({"api_key", "apikey", "token", "secret", "password"})


_PRIVATE_V4 = tuple(ipaddress.ip_network(n) for n in
                    ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10"))  # last: Tailscale
_PRIVATE_V6 = tuple(ipaddress.ip_network(n) for n in ("::1/128", "fc00::/7"))


def is_private_url(url: str) -> bool:
    """True when `url` points at this computer or an address on a private network (home or Tailscale), the only
    places a local model's data may go. Names other than `localhost` are refused: a name can be pointed anywhere."""
    try:
        host = urlparse(url).hostname
    except ValueError:
        return False
    if host is None:
        return False
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped                    # ::ffff:a.b.c.d is judged as a.b.c.d
        else:
            return any(ip in net for net in _PRIVATE_V6)   # 6to4, Teredo and NAT64 embed outside addresses
    nets = _PRIVATE_V4 if isinstance(ip, ipaddress.IPv4Address) else _PRIVATE_V6
    return any(ip in net for net in nets)


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One entry in the user's model list. List order is priority order."""

    name: str                        # the user's label, e.g. "mistral-small"
    provider: str                    # one of PROVIDERS
    model_id: str                    # the provider's model id
    local: bool = False              # runs on this computer and never sends data out
    enabled: bool = True
    caps: Cap = Cap.NONE
    max_label: Label = Label.PUBLIC  # standing ceiling; more needs the user's permission
    rpm: int | None = None           # requests per minute, from the provider's console
    rpd: int | None = None           # requests per day
    tz: str = "America/Los_Angeles"  # where the daily quota resets
    key_ref: str | None = None       # key store item name; the key itself is never stored here
    private_access: str = "ask"      # "ask": may receive private data with permission; "never"
    trains: bool = True              # assume a remote tier may train on, or show humans, your inputs
    base_url: str | None = None      # override the provider's default endpoint (Ollama on another port)
    quick: bool = False              # try this model first for small, simple steps (a cheaper or faster model)


@dataclass(frozen=True, slots=True)
class NetworkSettings:
    allowed_hosts: tuple[str, ...] = ()          # extra Host names the UI answers to, e.g. a Tailscale name


@dataclass(frozen=True, slots=True)
class SearchSettings:
    engine: str = "duckduckgo"
    searxng_url: str | None = None


@dataclass(frozen=True, slots=True)
class LimitSettings:
    """How much Lilly may do at once. All of these can be changed live from the Resources screen."""
    max_running: int = 3          # tasks running at the same time; more wait in a queue
    step_timeout_s: int = 180     # one step (a tool call or a model call) is stopped after this long
    task_minutes: int = 60        # a whole task is stopped after this long
    lanes: int = 3                # read-only steps of one task that may run side by side
    local_unload_s: int = 300     # a local model leaves memory after this long unused (0: right after each answer)


LIMIT_BOUNDS = {"max_running": (1, 8), "step_timeout_s": (10, 900), "task_minutes": (1, 240), "lanes": (1, 8),
                "local_unload_s": (0, 3600)}


@dataclass(frozen=True, slots=True)
class Settings:
    models: tuple[ModelSpec, ...] = ()
    modules: frozenset[str] = frozenset({"files", "web", "memory", "notes", "skills"})
    default_mode: Mode = Mode.ASK
    file_roots: tuple[str, ...] = ()             # folders agents may touch; empty means no file access
    retention_days: int = 90
    network: NetworkSettings = NetworkSettings()
    search: SearchSettings = SearchSettings()
    stay_awake: bool = False                     # keep the computer awake while a task runs
    limits: LimitSettings = LimitSettings()
    decisions: DecisionSettings = DecisionSettings()   # the cheap deciders that advise before a model is asked
    browser: BrowserSettings = BrowserSettings()       # the agent's browser (module `browser`, off by default)
    bridges: BridgeSettings = BridgeSettings()         # chat apps (Telegram): off until paired and switched on
    devbox: DevboxSettings = DevboxSettings()          # the sealed container (module `devbox`, off by default)


def default_settings() -> Settings:
    """First-run defaults: free-tier models first, a local model ready but off."""
    both = Cap.JSON | Cap.LONG_CONTEXT
    return Settings(models=(
        ModelSpec("mistral-small", "mistral", "mistral-small-latest", caps=both, key_ref="mistral"),
        ModelSpec("openrouter-free", "openrouter", "openrouter/free", key_ref="openrouter"),
        ModelSpec("gemini-flash", "gemini", "gemini-flash-latest", caps=both, key_ref="gemini"),
        ModelSpec("openai", "openai", "gpt-4o-mini", enabled=False, caps=both, key_ref="openai"),
        ModelSpec("ollama-local", "ollama", "llama3.2", local=True, enabled=False, caps=Cap.JSON,
                  max_label=Label.PERSONAL, trains=False),
    ))


def _spec_from_dict(d: dict[str, Any]) -> tuple[ModelSpec | None, list[str]]:
    errs: list[str] = []
    name = d.get("name", "")
    if bad := _SECRET_KEYS & {k.lower() for k in d}:
        errs.append(f"{name}: secrets must not be stored in settings ({', '.join(sorted(bad))})")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        errs.append(f"invalid model name {name!r}")
    if d.get("provider") not in PROVIDERS:
        errs.append(f"{name}: provider must be one of {', '.join(sorted(PROVIDERS))}")
    if not isinstance(d.get("model_id"), str) or not d.get("model_id"):
        errs.append(f"{name}: model_id is required")
    caps = Cap.NONE
    try:
        for c in d.get("caps", []):
            caps |= Cap[c]
    except (KeyError, TypeError):
        errs.append(f"{name}: unknown capability in {d.get('caps')!r}")
    try:
        label = Label[d.get("max_label", "PUBLIC")]
    except (KeyError, TypeError):
        errs.append(f"{name}: unknown max_label {d.get('max_label')!r}")
        label = Label.PUBLIC
    local = d.get("local", False)
    if not isinstance(local, bool):
        errs.append(f"{name}: local must be true or false")
    elif not local and label > Label.PUBLIC:
        errs.append(f"{name}: a remote model's standing access is PUBLIC only; use permission for more")
    for f in ("rpm", "rpd"):
        v = d.get(f)
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 1):
            errs.append(f"{name}: {f} must be a positive whole number")
    if d.get("private_access", "ask") not in ("ask", "never"):
        errs.append(f"{name}: private_access must be 'ask' or 'never'")
    for f in ("trains", "enabled", "quick"):
        if not isinstance(d.get(f, True), bool):
            errs.append(f"{name}: {f} must be true or false")
    tz = d.get("tz", "America/Los_Angeles")
    try:
        ZoneInfo(tz)
    except (KeyError, ValueError, OSError, TypeError):
        errs.append(f"{name}: unknown time zone {tz!r}")
    base_url = d.get("base_url")
    if base_url is not None and not (isinstance(base_url, str) and base_url.startswith(("http://", "https://"))):
        errs.append(f"{name}: base_url must start with http:// or https://")
    elif local is True and d.get("provider") != "ollama":
        errs.append(f"{name}: only an Ollama model can be marked local; this provider receives your data")
    elif local is True and base_url is not None and not is_private_url(base_url):
        errs.append(f"{name}: a local model must run on this computer or your private network; "
                    "use localhost or an IP address, or turn off 'local'")
    if errs:
        return None, errs
    return ModelSpec(name, d["provider"], d["model_id"], local, bool(d.get("enabled", True)), caps, label,
                     d.get("rpm"), d.get("rpd"), tz, d.get("key_ref"), d.get("private_access", "ask"),
                     bool(d.get("trains", True)), base_url, bool(d.get("quick", False))), []


def _roots(raw: object, errs: list[str]) -> tuple[str, ...]:
    out: list[str] = []
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, str) or not r.strip():
            errs.append("file_roots must be a list of folder paths")
            continue
        p = Path(os.path.expanduser(r.strip()))
        if not p.is_absolute() or p == Path(p.anchor) or p == Path.home():
            errs.append(f"{r}: choose a specific folder, not the filesystem root or your whole home folder")
            continue
        out.append(str(p))
    return tuple(dict.fromkeys(out))


def _limits(raw: object, errs: list[str]) -> LimitSettings:
    if not isinstance(raw, dict):
        errs.append("limits must be an object")
        return LimitSettings()
    values: dict[str, int] = {}
    for key, (lo, hi) in LIMIT_BOUNDS.items():
        v = raw.get(key, getattr(LimitSettings(), key))
        if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
            errs.append(f"limits.{key} must be a whole number from {lo} to {hi}")
            continue
        values[key] = v
    return LimitSettings(**values) if len(values) == len(LIMIT_BOUNDS) else LimitSettings()


def parse_settings(raw: dict[str, Any]) -> tuple[Settings | None, list[str]]:
    """Validate user-edited settings. Returns (settings, []) or (None, problems)."""
    errs: list[str] = []
    specs: list[ModelSpec] = []
    for d in raw.get("models", []):
        if not isinstance(d, dict):
            errs.append("model entry is not an object")
            continue
        spec, e = _spec_from_dict(d)
        errs += e
        if spec:
            specs.append(spec)
    names = [s.name for s in specs]
    errs += [f"duplicate model name {n!r}" for n in sorted({n for n in names if names.count(n) > 1})]

    mods = frozenset(raw.get("modules", Settings().modules))
    errs += [f"unknown module {m!r}" for m in sorted(mods - MODULES)]

    try:
        mode = Mode[raw.get("default_mode", "ASK")]
    except (KeyError, TypeError):
        errs.append("default_mode must be LOCKED, ASK or OPEN")
        mode = Mode.ASK
    days = raw.get("retention_days", 90)
    if not isinstance(days, int) or isinstance(days, bool) or not 0 <= days <= 3650:
        errs.append("retention_days must be a whole number from 0 (keep forever) to 3650")
        days = 90

    net = raw.get("network", {})
    hosts = tuple(net.get("allowed_hosts", ()))
    if not all(isinstance(h, str) and _HOST.fullmatch(h) for h in hosts):
        errs.append("network.allowed_hosts must be host names without ports or paths")

    s = raw.get("search", {})
    engine = s.get("engine", "duckduckgo")
    url = s.get("searxng_url")
    if engine not in SEARCH_ENGINES:
        errs.append("search.engine must be duckduckgo, brave or searxng")
    if engine == "searxng" and not (isinstance(url, str) and url.startswith(("http://", "https://"))):
        errs.append("search.searxng_url is required for searxng and must be an http(s) URL")
    stay = raw.get("stay_awake", False)
    if not isinstance(stay, bool):
        errs.append("stay_awake must be true or false")

    roots = _roots(raw.get("file_roots", []), errs)
    limits = _limits(raw.get("limits", {}), errs)
    decisions, decision_errs = parse_decisions(raw.get("decisions", {}))
    errs += decision_errs
    browser, browser_errs = parse_browser(raw.get("browser", {}))
    errs += browser_errs
    bridges, bridge_errs = parse_bridge(raw.get("bridges", {}))
    errs += bridge_errs
    devbox, devbox_errs = parse_devbox(raw.get("devbox", {}))
    errs += devbox_errs
    if errs:
        return None, errs
    return Settings(tuple(specs), mods, mode, roots, days,
                    NetworkSettings(hosts), SearchSettings(engine, url), stay, limits, decisions or DecisionSettings(),
                    browser or BrowserSettings(), bridges or BridgeSettings(), devbox or DevboxSettings()), []


def settings_to_dict(s: Settings) -> dict[str, Any]:
    return {
        "modules": sorted(s.modules),
        "default_mode": s.default_mode.name,
        "file_roots": list(s.file_roots),
        "retention_days": s.retention_days,
        "network": {"allowed_hosts": list(s.network.allowed_hosts)},
        "search": {"engine": s.search.engine, "searxng_url": s.search.searxng_url},
        "stay_awake": s.stay_awake,
        "limits": {"max_running": s.limits.max_running, "step_timeout_s": s.limits.step_timeout_s,
                   "task_minutes": s.limits.task_minutes, "lanes": s.limits.lanes,
                   "local_unload_s": s.limits.local_unload_s},
        "decisions": decisions_to_dict(s.decisions),
        "browser": browser_to_dict(s.browser),
        "bridges": bridge_to_dict(s.bridges),
        "devbox": devbox_to_dict(s.devbox),
        "models": [{"name": m.name, "provider": m.provider, "model_id": m.model_id, "local": m.local,
                    "enabled": m.enabled, "caps": [c.name for c in Cap if c and c in m.caps],
                    "max_label": m.max_label.name, "rpm": m.rpm, "rpd": m.rpd, "tz": m.tz,
                    "key_ref": m.key_ref, "private_access": m.private_access, "trains": m.trains,
                    "base_url": m.base_url, "quick": m.quick} for m in s.models],
    }


def save_settings(path: Path, s: Settings) -> None:
    """Atomic write with 0600 permissions; a crash never leaves a half-written file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(settings_to_dict(s), f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _keep_unreadable(path: Path) -> None:
    """Defaults replace a settings file that cannot be used, and the next save would overwrite it. Keep a copy
    next to it, once, so nothing the person had typed is lost."""
    keep = path.with_name(path.name + ".invalid")
    if not keep.exists():
        with contextlib.suppress(OSError):
            keep.write_bytes(path.read_bytes())
            os.chmod(keep, 0o600)


def load_settings(path: Path) -> tuple[Settings, list[str]]:
    """Read settings, or the defaults when there is no file yet. Problems are returned, never swallowed:
    an unreadable or invalid file yields the defaults plus the reasons, so the UI can show them."""
    if not path.exists():
        return default_settings(), []
    try:
        parsed, errs = parse_settings(json.loads(path.read_text()))
    except (OSError, json.JSONDecodeError) as exc:
        _keep_unreadable(path)
        return default_settings(), [f"cannot read settings: {exc}"]
    if parsed is None:
        _keep_unreadable(path)
    return (parsed, []) if parsed else (default_settings(), errs)
