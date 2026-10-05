"""Lilly's own secrets (access token, session secret, settings, database) cannot be reached by a file tool, however the
path is spelled and whatever folder the owner shares. What else keeps them from a model is covered where it lives:
the MCP child's environment (test_mcp_security), loopback addresses for the web and the browser (test_web_guard),
the devbox's shared folder (test_devbox)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lilly.domain.errors import PolicyDenied
from lilly.domain.ports import ToolContext
from lilly.domain.settings import settings_to_dict
from tests.integration.conftest import Api

CTX = ToolContext("t", "s1", 5.0, lambda: False)
NEEDLE = "needle-4f9c1"


async def _share(api: Api, folder: Path) -> None:
    await api.sign_in()
    current = settings_to_dict(api.runtime.settings)
    current["file_roots"] = [str(folder)]
    assert (await api.send("PUT", "/api/settings", current)).status_code == 200


def _secrets(api: Api) -> list[Path]:
    p = api.runtime.paths
    for f in (p.token, p.secret):
        f.write_text("not-a-real-secret")
    (p.config / "notes.txt").write_text(NEEDLE)
    return [p.token, p.secret, p.settings, p.db, p.config / "notes.txt", p.root, p.config, p.backups]


async def _run(api: Api, tool: str, **args: Any) -> str:
    return (await api.runtime.tools[tool].run(args, CTX)).output


@pytest.mark.parametrize("tool,key,extra", [
    ("fs.read", "path", {}), ("fs.list", "path", {}), ("fs.search", "path", {"query": NEEDLE}),
    ("fs.write", "path", {"content": "x", "overwrite": True}), ("fs.trash", "path", {}), ("data.profile", "path", {})])
async def test_no_file_tool_reaches_lilly_home_even_when_its_parent_folder_is_shared(
        api: Api, tool: str, key: str, extra: dict[str, Any]) -> None:
    await _share(api, api.shared.parent)                    # the owner shared a folder that contains Lilly's home
    for target in _secrets(api):
        with pytest.raises(PolicyDenied):
            await _run(api, tool, **{key: str(target)}, **extra)


async def test_a_search_from_the_parent_finds_nothing_inside_lilly_home(api: Api) -> None:
    await _share(api, api.shared.parent)
    _secrets(api)
    (api.shared / "ok.txt").write_text(NEEDLE)
    hits = json.loads(await _run(api, "fs.search", path=str(api.shared.parent), query=NEEDLE))["hits"]
    assert [Path(h["path"]).name for h in hits] == ["ok.txt"]


async def test_a_link_in_a_shared_folder_cannot_lead_into_lilly_home(api: Api) -> None:
    await _share(api, api.shared)
    p = api.runtime.paths
    _secrets(api)
    (api.shared / "token-link").symlink_to(p.token)
    (api.shared / "config-link").symlink_to(p.config)
    for target in (api.shared / "token-link", api.shared / "config-link" / "access-token", api.shared / "config-link"):
        for tool in ("fs.read", "fs.list"):
            with pytest.raises(PolicyDenied):
                await _run(api, tool, path=str(target))
    assert json.loads(await _run(api, "fs.search", path=str(api.shared), query=NEEDLE))["hits"] == []


async def test_another_spelling_of_the_path_does_not_get_in(api: Api) -> None:
    """On macOS `.LILLY` is the same folder as `.lilly`: the deny list must not depend on spelling."""
    await _share(api, api.shared.parent)
    p = api.runtime.paths
    for spelled in (p.token, Path(str(p.token).replace("lilly-home", "LILLY-HOME")),
                    Path(str(p.token).replace("config", "CONFIG"))):
        with pytest.raises(PolicyDenied):
            await _run(api, "fs.read", path=str(spelled))


async def test_sharing_lilly_home_itself_changes_nothing(api: Api) -> None:
    await _share(api, api.runtime.paths.root)
    for target in _secrets(api):
        with pytest.raises(PolicyDenied):
            await _run(api, "fs.read", path=str(target))
