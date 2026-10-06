"""App index for Quick Actions - indexes installed applications for quick matching."""
from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class AppEntry:
    name: str            # "Google Chrome"
    key: str             # normalised: "google chrome"
    path: str            # "/Applications/Google Chrome.app"  (macOS) or the .desktop file (Linux)
    process: str | None  # executable name used to confirm it is running (macOS: CFBundleExecutable)


def normalise(text: str) -> str:
    t = re.sub(r"[^\w\s]", " ", text.casefold())
    t = re.sub(r"\b(the|app|application)\b", " ", t)
    return " ".join(t.split())


class AppIndex:
    def __init__(self, platform: str = sys.platform, listdir: Callable[..., Any] = os.scandir,
                 read: Callable[..., Any] = Path.read_bytes, clock: Callable[[], float] = time.monotonic,
                 ttl_s: float = 300.0, roots: Callable[[], list[str]] | None = None) -> None:
        self._platform = platform
        self._listdir = listdir
        self._read = read
        self._clock = clock
        self._ttl_s = ttl_s
        self._roots = roots
        self._entries: list[AppEntry] | None = None
        self._last_built = 0.0

    def entries(self) -> list[AppEntry]:
        """Cached for ttl_s; rebuilt when expired or on .refresh()"""
        now = self._clock()
        if self._entries is None or now - self._last_built > self._ttl_s:
            self._entries = self._build_index()
            self._last_built = now
        return self._entries

    def find_exact(self, key: str) -> AppEntry | None:
        """Find an app by exact normalised key match."""
        for entry in self.entries():
            if entry.key == key:
                return entry
        return None

    def candidates(self, key: str, limit: int = 5) -> list[tuple[AppEntry, float]]:
        """Find candidate apps by fuzzy matching, returns (entry, score) tuples."""
        if not self._entries:
            return []
        
        entries = self.entries()
        results = []
        
        for entry in entries:
            score = self._score(key, entry.key)
            if score > 0:
                results.append((entry, score))
        
        # Sort by score descending, then by name ascending
        results.sort(key=lambda x: (-x[1], x[0].name))
        return results[:limit]

    def refresh(self) -> list[AppEntry]:
        """Force rebuild of the index."""
        self._entries = self._build_index()
        self._last_built = self._clock()
        return self._entries

    def _score(self, query: str, key: str) -> float:
        """Score a query against an app key."""
        query_norm = normalise(query)
        key_norm = key
        
        # Exact match
        if query_norm == key_norm:
            return 1.0
        
        # Key starts with query or query starts with key
        if key_norm.startswith(query_norm) or query_norm.startswith(key_norm):
            return 0.95
        
        # All query tokens are in key's tokens
        query_tokens = set(query_norm.split())
        key_tokens = set(key_norm.split())
        if query_tokens and query_tokens.issubset(key_tokens):
            return 0.9
        
        # Fall back to difflib
        import difflib
        return difflib.SequenceMatcher(None, query_norm, key_norm).ratio()

    def _build_index(self) -> list[AppEntry]:
        """Build the app index for the current platform."""
        if self._platform == "win32":
            return []  # Windows not supported yet
        
        if self._platform == "darwin":
            return self._build_mac_index()
        else:
            return self._build_linux_index()

    def _build_mac_index(self) -> list[AppEntry]:
        """Build index for macOS."""
        roots = self._get_mac_roots()
        entries = []
        
        for root in roots:
            if not os.path.isdir(root):
                continue
            
            try:
                for entry in self._listdir(root):
                    if entry.name.endswith('.app') and entry.is_dir():
                        app_entry = self._parse_mac_app(entry.path)
                        if app_entry:
                            entries.append(app_entry)
            except (OSError, PermissionError):
                continue
        
        return entries

    def _get_mac_roots(self) -> list[str]:
        """Get macOS application directories."""
        if self._roots:
            return self._roots()
        
        home = os.path.expanduser("~")
        return [
            "/Applications",
            "/System/Applications",
            "/System/Applications/Utilities",
            f"{home}/Applications"
        ]

    def _parse_mac_app(self, app_path: str) -> AppEntry | None:
        """Parse a macOS .app bundle."""
        try:
            info_plist_path = os.path.join(app_path, "Contents", "Info.plist")
            if not os.path.isfile(info_plist_path):
                return None
            
            plist_data = self._read(Path(info_plist_path))
            import plistlib
            info = plistlib.loads(plist_data)
            
            name = info.get("CFBundleName", "") or os.path.basename(app_path)
            if not name:
                return None
            
            process = info.get("CFBundleExecutable")
            
            return AppEntry(
                name=name,
                key=normalise(name),
                path=app_path,
                process=process
            )
        except Exception:
            return None

    def _build_linux_index(self) -> list[AppEntry]:
        """Build index for Linux."""
        entries = []
        
        # Get XDG data directories
        xdg_data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/share").split(":")
        search_dirs = [os.path.join(d, "applications") for d in xdg_data_dirs]
        search_dirs.append(os.path.join(os.path.expanduser("~"), ".local", "share", "applications"))
        
        for search_dir in search_dirs:
            if not os.path.isdir(search_dir):
                continue
            
            try:
                for entry in self._listdir(search_dir):
                    if entry.name.endswith('.desktop') and entry.is_file():
                        app_entry = self._parse_linux_desktop(entry.path)
                        if app_entry:
                            entries.append(app_entry)
            except (OSError, PermissionError):
                continue
        
        return entries

    def _parse_linux_desktop(self, desktop_path: str) -> AppEntry | None:
        """Parse a Linux .desktop file."""
        try:
            content = self._read(Path(desktop_path))
            lines = content.decode('utf-8', errors='replace').splitlines()
            
            name = ""
            nodisplay = False
            
            for line in lines:
                line = line.strip()
                if line.startswith("Name="):
                    name = line[5:].strip()
                elif line.startswith("NoDisplay="):
                    nodisplay = line[10:].strip().lower() in ("true", "1", "yes")
            
            if not name or nodisplay:
                return None
            
            # For Linux, we don't have a reliable way to get the executable process name
            return AppEntry(
                name=name,
                key=normalise(name),
                path=desktop_path,
                process=None
            )
        except Exception:
            return None
