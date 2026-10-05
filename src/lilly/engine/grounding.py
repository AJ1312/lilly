"""Grounding verifier: ensures URLs and file paths in answers come from tool results or the user."""
from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lilly.engine.messages import GROUNDING_REMOVED_NOTE, GROUNDING_REPAIR

URL_REGEX = re.compile(r"https?://[^\s<>'\"`()\[\]{}]+[^\s<>'\"`()\[\]{}.,;:?!]")
# Absolute paths starting with /, at least two components e.g. /foo/bar.txt
PATH_REGEX = re.compile(r"(?<![a-zA-Z0-9_:/])(/[-a-zA-Z0-9_.~+]+(?:/[-a-zA-Z0-9_.~+]*)+)")


def extract_urls(text: str) -> list[str]:
    """Extract unique HTTP/HTTPS URLs from text."""
    seen: list[str] = []
    for match in URL_REGEX.finditer(text):
        url = match.group(0).rstrip(".,;:!?)'\"`")
        if url and url not in seen:
            seen.append(url)
    return seen


def extract_paths(text: str) -> list[str]:
    """Extract unique absolute filesystem paths from text."""
    seen: list[str] = []
    for match in PATH_REGEX.finditer(text):
        p = match.group(1).rstrip(".,;:!?)'\"`")
        # Ignore common non-paths or root-only
        if p and p != "/" and p not in seen:
            seen.append(p)
    return seen


def normalize_url(url: str) -> str:
    return url.rstrip("/")


def normalize_path(path: str) -> str:
    try:
        return str(Path(path).resolve())
    except Exception:
        return path


class GroundingVerifier:
    """Verifies that links and file paths in candidate answers are grounded in evidence."""

    def __init__(
        self,
        file_roots: tuple[str, ...] = (),
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self._file_roots = tuple(normalize_path(r) for r in file_roots)
        self.seen_urls: set[str] = set()
        self.seen_paths: set[str] = set(self._file_roots)

    def record_user_message(self, text: str) -> None:
        """Collect URLs and paths mentioned by the user."""
        for u in extract_urls(text):
            self.seen_urls.add(normalize_url(u))
            self.seen_urls.add(u)
        for p in extract_paths(text):
            self.seen_paths.add(normalize_path(p))
            self.seen_paths.add(p)

    def record_step(self, tool: str, args: Mapping[str, Any], output: str) -> None:
        """Collect URLs and paths from tool arguments and successful outputs."""
        # Check tool args
        for k in ("url", "urls", "path", "root", "from", "to"):
            val = args.get(k)
            if isinstance(val, str):
                if val.startswith("http://") or val.startswith("https://"):
                    self.seen_urls.add(normalize_url(val))
                    self.seen_urls.add(val)
                elif val.startswith("/"):
                    self.seen_paths.add(normalize_path(val))
                    self.seen_paths.add(val)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        if item.startswith("http://") or item.startswith("https://"):
                            self.seen_urls.add(normalize_url(item))
                            self.seen_urls.add(item)
                        elif item.startswith("/"):
                            self.seen_paths.add(normalize_path(item))
                            self.seen_paths.add(item)

        # Check tool output
        for u in extract_urls(output):
            self.seen_urls.add(normalize_url(u))
            self.seen_urls.add(u)

        if tool.startswith("fs.") or tool.startswith("data."):
            for p in extract_paths(output):
                self.seen_paths.add(normalize_path(p))
                self.seen_paths.add(p)
            # If JSON output with path/hits keys
            with contextlib.suppress(Exception):
                data = json.loads(output)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "path" in item and isinstance(item["path"], str):
                            p = item["path"]
                            self.seen_paths.add(normalize_path(p))
                            self.seen_paths.add(p)
                elif isinstance(data, dict):
                    if "hits" in data and isinstance(data["hits"], list):
                        for h in data["hits"]:
                            if isinstance(h, dict) and "path" in h and isinstance(h["path"], str):
                                p = h["path"]
                                self.seen_paths.add(normalize_path(p))
                                self.seen_paths.add(p)

    def is_path_seen(self, path: str) -> bool:
        """Check if a path was seen directly or is inside a seen directory or shared folder."""
        norm = normalize_path(path)
        if path in self.seen_paths or norm in self.seen_paths:
            return True
        p_obj = Path(norm)
        for seen in self.seen_paths:
            try:
                if p_obj.is_relative_to(Path(seen)):
                    return True
            except (ValueError, TypeError):
                continue
        for root in self._file_roots:
            try:
                if p_obj.is_relative_to(Path(root)):
                    return True
            except (ValueError, TypeError):
                continue
        return False

    def is_url_seen(self, url: str) -> bool:
        """Check if a URL was seen directly or under normalized form."""
        norm = normalize_url(url)
        return url in self.seen_urls or norm in self.seen_urls

    def verify(self, answer: str) -> tuple[bool, list[str]]:
        """Verify candidate answer. Returns (is_grounded, unseen_references)."""
        if not self.enabled:
            return True, []

        unseen: list[str] = []
        urls = extract_urls(answer)
        for u in urls:
            if not self.is_url_seen(u):
                unseen.append(u)

        paths = extract_paths(answer)
        for p in paths:
            if not self.is_path_seen(p):
                unseen.append(p)

        return (len(unseen) == 0, unseen)

    def repair_prompt(self, unseen: list[str]) -> str:
        """Generate the exact Phase 4A.6 repair prompt."""
        return GROUNDING_REPAIR.format(list=", ".join(unseen))

    def remove_unseen(self, answer: str, unseen: list[str]) -> str:
        """Remove ungrounded references and append the exact Phase 4A.6 note."""
        cleaned = answer
        for ref in unseen:
            cleaned = cleaned.replace(ref, "")
        note = GROUNDING_REMOVED_NOTE.format(n=len(unseen))
        cleaned = cleaned.rstrip() + f"\n\n{note}"
        return cleaned
