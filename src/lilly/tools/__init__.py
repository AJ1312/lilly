"""Built-in tools and the factory that assembles the set a given configuration enables."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

from lilly.domain.browser_policy import BrowserSettings
from lilly.domain.clock import Clock
from lilly.domain.errors import ConfigurationError
from lilly.domain.policy import PathScope
from lilly.domain.ports import Completer, KeyStore, ToolContext, ToolResult
from lilly.domain.settings import Settings
from lilly.domain.tools_registry import DEFAULT_TOOLS
from lilly.store.db import Database
from lilly.tools.agent import AgentAskTool, AgentDelegateTool, AgentPlanTool, SkillLoadTool
from lilly.tools.base import Tool
from lilly.tools.browser.actions import browser_tools
from lilly.tools.browser.manager import BrowserManager
from lilly.tools.computer import (
    NotifyTool,
    OpenAppTool,
    OpenUrlTool,
    ProcessesTool,
    RunCommandTool,
    StopProcessTool,
)
from lilly.tools.data import DataProfileTool
from lilly.tools.devbox.manager import DevboxManager
from lilly.tools.devbox.tool import DevboxRunTool
from lilly.tools.fs import FsApplyMovesTool, FsEditTool, FsListTool, FsReadTool, FsSearchTool, FsTrashTool, FsWriteTool
from lilly.tools.llm import LlmWorkTool
from lilly.tools.memory import MemorySearchTool, MemoryWriteTool
from lilly.tools.notes import NotesReadTool, NotesSearchTool, NotesWriteTool
from lilly.tools.result import ResultReadTool
from lilly.tools.system import SystemStatsTool
from lilly.tools.web import WebFetchTool, WebResearchTool, WebSearchTool

__all__ = ["Tool", "build_tools"]


def build_tools(settings: Settings, *, scope: PathScope, db: Database, router: Completer, keys: KeyStore,
                client: httpx.AsyncClient, clock: Clock,
                browser: tuple[BrowserManager, Callable[[], BrowserSettings]] | None = None,
                devbox: DevboxManager | None = None,
                delegate_fn: Callable[[str, str, ToolContext], Awaitable[ToolResult]] | None = None) -> dict[str, Tool]:
    """Every tool the enabled modules provide, keyed by name. Nothing is registered that does not exist,
    and every tool's name must be in DEFAULT_TOOLS, where its risk is pinned."""
    globs = settings.grounding.protected_globs
    web_search = WebSearchTool(client, keys, settings.search)
    web_fetch = WebFetchTool()
    every: list[Tool] = [
        FsListTool(scope), FsReadTool(scope), FsSearchTool(scope),
        FsWriteTool(scope, globs), FsEditTool(scope, db, globs), FsApplyMovesTool(scope, globs), FsTrashTool(scope, globs),
        DataProfileTool(scope),
        web_search, web_fetch, WebResearchTool(web_search, web_fetch),
        MemorySearchTool(db), MemoryWriteTool(db, clock),
        NotesSearchTool(db), NotesReadTool(db), NotesWriteTool(db, clock),
        OpenUrlTool(), OpenAppTool(), ProcessesTool(), StopProcessTool(), NotifyTool(), RunCommandTool(scope),
        SystemStatsTool(), LlmWorkTool(router),
        ResultReadTool(db), AgentPlanTool(db, clock), AgentAskTool(), AgentDelegateTool(delegate_fn),
        SkillLoadTool(db),
        *(browser_tools(*browser) if browser else []),
        *([DevboxRunTool(devbox)] if devbox else []),
    ]
    tools: dict[str, Tool] = {}
    for tool in every:
        spec = DEFAULT_TOOLS.get(tool.name)
        if spec is None:
            raise ConfigurationError(f"tool {tool.name!r} is not in the registry")
        if spec.module is None or spec.module in settings.modules:
            tools[tool.name] = tool
    return tools
