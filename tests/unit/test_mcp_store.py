"""Stored MCP servers and approvals: validation, cascade, and withdrawal of an approval when a server changes."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from lilly.domain.errors import NotFound, ValidationFailed
from lilly.domain.labels import Label, Risk
from lilly.domain.mcp import McpApproval, McpServerConfig, McpToolInfo
from lilly.store import mcp
from lilly.store.connection import open_db

TOOL = McpToolInfo("echo", "says it back", {"type": "object"})


@pytest.fixture
def con(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = open_db(tmp_path / "t.db")
    yield c
    c.close()


def cfg(**kw: object) -> McpServerConfig:
    base: dict[str, object] = {"name": "files", "command": "node", "args": ("server.js",)}
    return McpServerConfig(**{**base, **kw})  # type: ignore[arg-type]


def test_a_stored_server_comes_back_unchanged(con: sqlite3.Connection) -> None:
    c = cfg(env={"A": "1"}, secret_env={"TOKEN": "mcp.files.TOKEN"}, data_label=Label.PUBLIC, idle_stop_s=30.0)
    mcp.put_server(con, c, 1.0)
    assert mcp.list_servers(con) == [c]


def test_an_invalid_server_is_refused_and_nothing_is_stored(con: sqlite3.Connection) -> None:
    with pytest.raises(ValidationFailed):
        mcp.put_server(con, cfg(name="Bad Name"), 1.0)
    assert mcp.list_servers(con) == []


def test_changing_how_a_server_starts_withdraws_its_approval(con: sqlite3.Connection) -> None:
    mcp.put_server(con, cfg(), 1.0)
    mcp.put_approval(con, McpApproval("files", (TOOL,), {"echo": Risk.R1}), 2.0)
    mcp.put_server(con, cfg(args=("other.js",)), 3.0)
    assert mcp.get_approvals(con) == {}


def test_turning_a_server_off_and_on_keeps_its_approval(con: sqlite3.Connection) -> None:
    mcp.put_server(con, cfg(), 1.0)
    mcp.put_approval(con, McpApproval("files", (TOOL,), {"echo": Risk.R2}), 2.0)
    mcp.set_enabled(con, "files", False)
    assert not mcp.list_servers(con)[0].enabled
    mcp.put_server(con, cfg(enabled=True), 3.0)
    assert mcp.list_servers(con)[0].enabled
    assert mcp.get_approvals(con)["files"].risks == {"echo": Risk.R2}


def test_an_approval_round_trips_and_can_be_replaced_or_revoked(con: sqlite3.Connection) -> None:
    mcp.put_server(con, cfg(), 1.0)
    a = McpApproval("files", (TOOL,), {"echo": Risk.R0})
    mcp.put_approval(con, a, 2.0)
    assert mcp.get_approvals(con)["files"] == a
    mcp.put_approval(con, McpApproval("files", (TOOL,), {"echo": Risk.R2}), 3.0)
    assert mcp.get_approvals(con)["files"].risks == {"echo": Risk.R2}
    mcp.revoke_approval(con, "files")
    assert mcp.get_approvals(con) == {}


def test_an_approval_cannot_name_a_tool_that_was_not_reviewed_or_a_risk_above_r2(con: sqlite3.Connection) -> None:
    mcp.put_server(con, cfg(), 1.0)
    with pytest.raises(ValidationFailed):
        mcp.put_approval(con, McpApproval("files", (TOOL,), {"other": Risk.R1}), 2.0)
    with pytest.raises(ValidationFailed):
        mcp.put_approval(con, McpApproval("files", (TOOL,), {"echo": Risk.R3}), 2.0)
    assert mcp.get_approvals(con) == {}


def test_an_approval_needs_its_server(con: sqlite3.Connection) -> None:
    with pytest.raises(NotFound):
        mcp.put_approval(con, McpApproval("ghost", (TOOL,), {"echo": Risk.R1}), 2.0)


def test_deleting_a_server_deletes_its_approval(con: sqlite3.Connection) -> None:
    mcp.put_server(con, cfg(), 1.0)
    mcp.put_approval(con, McpApproval("files", (TOOL,), {"echo": Risk.R1}), 2.0)
    mcp.delete_server(con, "files")
    assert mcp.list_servers(con) == [] and mcp.get_approvals(con) == {}
    with pytest.raises(NotFound):
        mcp.delete_server(con, "files")
    with pytest.raises(NotFound):
        mcp.set_enabled(con, "files", True)
