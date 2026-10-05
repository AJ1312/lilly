"""MCP servers and the approvals that bind them to a reviewed tool list."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from lilly.domain.errors import NotFound, ValidationFailed
from lilly.domain.labels import Label, Risk
from lilly.domain.mcp import McpApproval, McpServerConfig, McpToolInfo, validate_server
from lilly.store.connection import tx


def _config_json(cfg: McpServerConfig) -> str:
    return json.dumps({"command": cfg.command, "args": list(cfg.args), "env": dict(cfg.env),
                       "secret_env": dict(cfg.secret_env), "data_label": cfg.data_label.name,
                       "idle_stop_s": cfg.idle_stop_s}, sort_keys=True)


def _config(name: str, config_json: str, enabled: bool) -> McpServerConfig:
    d: dict[str, Any] = json.loads(config_json)
    return McpServerConfig(name, d["command"], tuple(d["args"]), d["env"], d["secret_env"], enabled,
                           Label[d["data_label"]], float(d["idle_stop_s"]))


def put_server(con: sqlite3.Connection, cfg: McpServerConfig, now: float) -> None:
    """Add a server or change it. Changing how it is started withdraws its approval: a different program is a
    different thing to trust. Turning it on or off keeps the approval."""
    validate_server(cfg)
    new = _config_json(cfg)
    with tx(con):
        row = con.execute("SELECT config_json FROM mcp_servers WHERE name=?", (cfg.name,)).fetchone()
        if row is None:
            con.execute("INSERT INTO mcp_servers(name, config_json, enabled, created_at) VALUES(?,?,?,?)",
                        (cfg.name, new, int(cfg.enabled), now))
            return
        if row[0] != new:
            con.execute("DELETE FROM mcp_approvals WHERE server=?", (cfg.name,))
        con.execute("UPDATE mcp_servers SET config_json=?, enabled=? WHERE name=?", (new, int(cfg.enabled), cfg.name))


def set_enabled(con: sqlite3.Connection, name: str, enabled: bool) -> None:
    if con.execute("UPDATE mcp_servers SET enabled=? WHERE name=?", (int(enabled), name)).rowcount == 0:
        raise NotFound(name)


def delete_server(con: sqlite3.Connection, name: str) -> None:
    if con.execute("DELETE FROM mcp_servers WHERE name=?", (name,)).rowcount == 0:  # its approval cascades
        raise NotFound(name)


def list_servers(con: sqlite3.Connection) -> list[McpServerConfig]:
    return [_config(n, c, bool(e)) for n, c, e in
            con.execute("SELECT name, config_json, enabled FROM mcp_servers ORDER BY name")]


def put_approval(con: sqlite3.Connection, approval: McpApproval, now: float) -> None:
    """Record what the owner reviewed. Every approved tool must be one of the reviewed tools."""
    names = {t.name for t in approval.tools}
    if not set(approval.risks) <= names:
        raise ValidationFailed("a tool was approved that is not in the reviewed list")
    if any(r >= Risk.R3 for r in approval.risks.values()):
        raise ValidationFailed("that risk level cannot be approved")
    tools = json.dumps([{"name": t.name, "description": t.description, "input_schema": dict(t.input_schema)}
                        for t in approval.tools], sort_keys=True)
    risks = json.dumps({n: int(r) for n, r in sorted(approval.risks.items())})
    with tx(con):
        if con.execute("SELECT 1 FROM mcp_servers WHERE name=?", (approval.server,)).fetchone() is None:
            raise NotFound(approval.server)
        con.execute("INSERT INTO mcp_approvals(server, tools_json, risks_json, approved_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(server) DO UPDATE SET tools_json=excluded.tools_json, "
                    "risks_json=excluded.risks_json, approved_at=excluded.approved_at",
                    (approval.server, tools, risks, now))


def revoke_approval(con: sqlite3.Connection, name: str) -> None:
    con.execute("DELETE FROM mcp_approvals WHERE server=?", (name,))


def get_approvals(con: sqlite3.Connection) -> dict[str, McpApproval]:
    out: dict[str, McpApproval] = {}
    for server, tools_json, risks_json in con.execute("SELECT server, tools_json, risks_json FROM mcp_approvals"):
        tools = tuple(McpToolInfo(t["name"], t["description"], t["input_schema"]) for t in json.loads(tools_json))
        out[server] = McpApproval(server, tools, {n: Risk(r) for n, r in json.loads(risks_json).items()})
    return out
