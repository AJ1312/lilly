"""MCP servers: what is configured, what a server offers, and what the owner has approved.

Everything here is plain data and pure functions. The process handling lives in `lilly.tools.mcp`.
A server is untrusted code and its answers are untrusted text; nothing in this module grants it more.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lilly.domain.errors import ValidationFailed
from lilly.domain.labels import Label, Risk

SERVER_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
SECRETISH_ENV = re.compile(r"(^|_)(API_?KEY|KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?|AUTH)(_|$)", re.IGNORECASE)

# Hard limits. A server that goes past one is treated as misbehaving: the call fails, nothing is trusted further.
MAX_MESSAGE_BYTES = 1_000_000        # one JSON-RPC line, in either direction
MAX_TOOLS_PER_SERVER = 64
MAX_TOOL_PAGES = 8                   # tools/list pagination
MAX_DESCRIPTION_CHARS = 1_000        # per tool description shown to the planner
MAX_SCHEMA_BYTES = 8_000             # per tool input schema
MAX_OUTPUT_CHARS = 100_000           # per tool result handed to the engine
MAX_ARGS = 32
MAX_ENV = 32
CALL_TIMEOUT_S = 60.0
START_TIMEOUT_S = 20.0
IDLE_STOP_S = 600.0                  # default: stop a server that has not been used for ten minutes
MAX_RESTARTS = 3                     # automatic restarts of one server before it is marked failed

# The only variables a server inherits from Lilly's own environment. Everything else, keys included, is withheld.
INHERITED_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "SYSTEMROOT", "TEMP", "TMP")

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")   # newest first; the server picks one we know


@dataclass(frozen=True, slots=True)
class McpServerConfig:
    """How to start one server. Values are checked by `validate_server`; a config is never run unchecked."""

    name: str
    command: str                                  # a program, found on PATH or given as an absolute path
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)          # extra, non-secret variables
    secret_env: Mapping[str, str] = field(default_factory=dict)   # variable name -> key-store reference
    enabled: bool = True
    data_label: Label = Label.PERSONAL            # how sensitive this server's answers are treated
    idle_stop_s: float = IDLE_STOP_S


@dataclass(frozen=True, slots=True)
class McpToolInfo:
    """One tool as the server described it. All fields are untrusted text."""

    name: str
    description: str
    input_schema: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class McpApproval:
    """What the owner reviewed and approved for one server: exactly this tool list, at these risk levels.

    If the server later offers a different list, the fingerprints differ and its calls are refused until
    the owner reviews the change. A tool absent from `risks` is not exposed."""

    server: str
    tools: tuple[McpToolInfo, ...]            # the list the owner reviewed (names, descriptions, schemas)
    risks: Mapping[str, Risk]                 # the risk level the owner chose for each approved tool

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.tools)


def validate_server(cfg: McpServerConfig) -> McpServerConfig:
    """Return `cfg` unchanged when it is safe to store and run, else raise ValidationFailed."""
    if not SERVER_NAME.fullmatch(cfg.name):
        raise ValidationFailed("a server name is 1 to 32 lowercase letters, digits, '-' or '_'")
    if not cfg.command.strip() or "\x00" in cfg.command or "\n" in cfg.command:
        raise ValidationFailed("the command to start the server is missing or invalid")
    if len(cfg.args) > MAX_ARGS or any("\x00" in a or len(a) > 4_000 for a in cfg.args):
        raise ValidationFailed("too many or invalid arguments")
    if len(cfg.env) + len(cfg.secret_env) > MAX_ENV:
        raise ValidationFailed("too many environment variables")
    for key in (*cfg.env, *cfg.secret_env):
        if not ENV_NAME.fullmatch(key):
            raise ValidationFailed(f"{key!r} is not a valid environment variable name")
    for key in cfg.env:
        if SECRETISH_ENV.search(key):
            raise ValidationFailed(f"{key} looks like a secret; add it under secret variables so it is kept in your keychain")
    if set(cfg.env) & set(cfg.secret_env):
        raise ValidationFailed("a variable cannot be both plain and secret")
    if any("\x00" in v for v in cfg.env.values()):
        raise ValidationFailed("invalid environment value")
    if not 10.0 <= cfg.idle_stop_s <= 86_400.0:
        raise ValidationFailed("idle stop must be between 10 seconds and one day")
    if cfg.data_label is Label.SECRET:
        raise ValidationFailed("a server cannot be marked as handling secret data")
    return cfg


def clean_tool(raw: object) -> McpToolInfo | None:
    """One entry of a tools/list answer made safe, or None when it is malformed and must be ignored."""
    if not isinstance(raw, dict):
        return None
    name, desc, schema = raw.get("name"), raw.get("description", ""), raw.get("inputSchema", {})
    if not isinstance(name, str) or not TOOL_NAME.fullmatch(name):
        return None
    if not isinstance(desc, str):
        desc = ""
    if not isinstance(schema, dict):
        return None
    if len(json.dumps(schema, sort_keys=True)) > MAX_SCHEMA_BYTES:
        return None
    return McpToolInfo(name, " ".join(desc.split())[:MAX_DESCRIPTION_CHARS], schema)


def fingerprint(tools: Sequence[McpToolInfo]) -> str:
    """A stable hash of everything the planner would be shown about a server's tools."""
    body = json.dumps([[t.name, t.description, t.input_schema] for t in sorted(tools, key=lambda t: t.name)],
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def exposed_name(server: str, tool: str) -> str:
    """The name the planner and the policy see: `mcp.<server>.<tool>`."""
    return f"mcp.{server}.{tool}"
