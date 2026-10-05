"""system.stats: CPU, memory, disk and the heaviest processes."""
from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import psutil

from lilly.domain.labels import Label
from lilly.domain.ports import ToolContext, ToolResult
from lilly.tools.base import Tool, int_arg


def collect_stats(top: int = 8) -> dict[str, Any]:
    """A snapshot of the machine. Shared by the system.stats tool and the Settings → About screen."""
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(str(Path.home()))
    procs: list[dict[str, Any]] = []
    for p in psutil.process_iter(["pid", "name", "memory_percent"]):
        with contextlib.suppress(psutil.Error):
            procs.append({"pid": p.info["pid"], "name": p.info["name"] or "unknown",
                          "memory_percent": round(p.info["memory_percent"] or 0.0, 1)})
    procs.sort(key=lambda x: x["memory_percent"], reverse=True)
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "memory": {"total": vm.total, "available": vm.available, "percent": vm.percent},
        "disk": {"total": disk.total, "free": disk.free, "percent": disk.percent},
        "top_processes": procs[:top],
    }


class SystemStatsTool(Tool):
    name = "system.stats"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        top = int_arg(args, "limit", 8, lo=1, hi=30)
        stats = await asyncio.to_thread(collect_stats, top)
        return ToolResult(json.dumps(stats, indent=1), Label.PUBLIC, False)
