"""Optional in-memory read cache for idempotent R0 tools."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from lilly.domain.labels import Label
from lilly.domain.payload import canonical

IDEMPOTENT_TOOLS = frozenset({
    "web.fetch",
    "fs.read",
    "fs.list",
    "fs.search",
    "notes.read",
    "notes.search",
    "memory.search",
    "result.read",
})


@dataclass(frozen=True, slots=True)
class CachedRead:
    output: str
    label: Label
    untrusted: bool
    created_at: float


class ReadCache:
    """Caches results of idempotent read tools within a configured TTL."""

    def __init__(self) -> None:
        self._entries: dict[str, CachedRead] = {}

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def key(self, tool: str, args: Mapping[str, Any]) -> str:
        return f"{tool}:{canonical(args)}"

    def get(self, tool: str, args: Mapping[str, Any], now: float, ttl_s: int) -> CachedRead | None:
        if ttl_s <= 0 or tool not in IDEMPOTENT_TOOLS:
            return None
        k = self.key(tool, args)
        entry = self._entries.get(k)
        if entry is None:
            return None
        if now - entry.created_at > ttl_s:
            self._entries.pop(k, None)
            return None
        return entry

    def put(self, tool: str, args: Mapping[str, Any], output: str, label: Label, untrusted: bool,
            now: float, ttl_s: int) -> None:
        if ttl_s <= 0 or tool not in IDEMPOTENT_TOOLS:
            return
        k = self.key(tool, args)
        self._entries[k] = CachedRead(output=output, label=label, untrusted=untrusted, created_at=now)

    def invalidate_prefix(self, prefix: str) -> int:
        """Invalidate all cached entries starting with prefix (e.g. 'fs.', 'notes.')."""
        to_delete = [k for k in self._entries if k.startswith(prefix)]
        for k in to_delete:
            self._entries.pop(k, None)
        return len(to_delete)

    def invalidate_tool(self, tool: str) -> int:
        return self.invalidate_prefix(f"{tool}:")

    def invalidate_fs(self) -> int:
        return self.invalidate_prefix("fs.")

    def invalidate_notes(self) -> int:
        return self.invalidate_prefix("notes.")

    def invalidate_memory(self) -> int:
        return self.invalidate_prefix("memory.")

    def clear(self) -> None:
        self._entries.clear()
