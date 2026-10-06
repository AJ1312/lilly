"""Quick Actions: fast path for common requests without model calls."""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Any

from lilly.tools.appindex import AppIndex, normalise


@dataclass(frozen=True, slots=True)
class QuickIntents:
    version: int
    verbs: Mapping[str, list[str]]
    polite_prefixes: list[str]
    suffix_words: list[str]
    reject_if_contains: list[str]
    max_words: int
    aliases: Mapping[str, str]
    site_aliases: Mapping[str, str]
    file_extensions: list[str]


@dataclass(frozen=True, slots=True)
class QuickAction:
    tool: str                       # "computer.open_app" | "computer.open_url"
    args: dict[str, str]
    shown: str                      # "Google Chrome" — what the UI and the receipt call it
    confidence: float
    matched_by: Literal["exact","alias","prefix","fuzzy","url","site_alias"]


@dataclass(frozen=True, slots=True)
class Ambiguous:
    query: str
    options: tuple[str, ...]        # up to 5 installed app names


QuickResult = QuickAction | Ambiguous | None


def load_intents(path: Path | None = None) -> QuickIntents:
    """Load quick intents from JSON file. Falls back to built-in defaults."""
    default_path = Path(__file__).parent / "quick_intents.json"
    user_path = Path.home() / ".lilly" / "quick_intents.json"
    
    paths_to_try = []
    if path:
        paths_to_try.append(path)
    if user_path.exists():
        paths_to_try.append(user_path)
    if default_path.exists():
        paths_to_try.append(default_path)
    
    for p in paths_to_try:
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return QuickIntents(**data)
        except (OSError, json.JSONDecodeError):
            continue
    
    # Fallback to hardcoded defaults if no file found
    return QuickIntents(
        version=1,
        verbs={"open_app_or_site": ["open", "launch", "start", "run", "go to", "goto", "visit", "take me to"]},
        polite_prefixes=["please", "can you", "could you", "hey lilly", "lilly"],
        suffix_words=["app", "application", "website", "site", "page"],
        reject_if_contains=[" and ", " then ", " after ", ";", "&", ",", "\n", " also ", " plus "],
        max_words=5,
        aliases={
            "chrome": "Google Chrome", "whatsapp": "WhatsApp", "vscode": "Visual Studio Code",
            "code": "Visual Studio Code", "terminal": "Terminal", "settings": "System Settings"
        },
        site_aliases={"gmail": "https://mail.google.com", "youtube": "https://www.youtube.com"},
        file_extensions=["md", "txt", "py", "js", "ts", "json", "csv", "pdf", "docx", "xlsx", "png", "jpg", "zip", "sh", "html", "css"]
    )


class QuickRouter:
    def __init__(self, intents: QuickIntents, index: AppIndex, settings: Callable[[], Any]) -> None:
        self._intents = intents
        self._index = index
        self._settings = settings
        # Build regex for verb matching
        verb_patterns = self._intents.verbs.get("open_app_or_site", [])
        self._verb_re = re.compile(
            r"\b(" + "|".join(re.escape(v) for v in verb_patterns) + r")\b\s+(.+)",
            re.IGNORECASE
        )

    def match(self, goal: str, allowed_tools: Collection[str] | None = None) -> QuickResult:
        s = self._settings()
        if not s.quick_enabled:
            return None
        
        text = " ".join(goal.strip().split())
        
        # Reject if too long or contains forbidden patterns
        if len(text) > 120 or any(tok in f" {text.casefold()} " for tok in self._intents.reject_if_contains):
            return None
        
        # Strip polite prefixes
        text = self._strip_prefixes(text)
        
        # Match verb pattern
        m = self._verb_re.match(text)
        if m is None:
            return None
        
        target = self._strip_suffix_words(m.group(2)).strip(" .!?\"'")
        if not target or len(target.split()) > self._intents.max_words:
            return None
        
        # Check if it's a site/URL
        site = self._as_site(target)
        if site is not None:
            return self._propose("computer.open_url", {"url": site}, site, 1.0, "url", allowed_tools)
        
        # Check site aliases
        alias = self._intents.site_aliases.get(normalise(target))
        if alias:
            return self._propose("computer.open_url", {"url": alias}, target, 1.0, "site_alias", allowed_tools)
        
        # Check app aliases
        key = normalise(self._intents.aliases.get(normalise(target), target))
        
        # Try exact match with alias or original target
        exact = self._index.find_exact(key)
        if exact:
            return self._propose("computer.open_app", {"name": exact.name}, exact.name, 1.0,
                                "alias" if key != normalise(target) else "exact", allowed_tools)
        
        # If alias didn't work, try the original target as well
        if key != normalise(target):
            exact_orig = self._index.find_exact(normalise(target))
            if exact_orig:
                return self._propose("computer.open_app", {"name": exact_orig.name}, exact_orig.name, 1.0,
                                    "exact", allowed_tools)
        
        # Try fuzzy match
        cands = self._index.candidates(key, 5)
        if not cands:
            # Also try fuzzy match with original target if different from key
            if key != normalise(target):
                cands = self._index.candidates(normalise(target), 5)
            if not cands:
                return None
        
        best, second = cands[0], (cands[1][1] if len(cands) > 1 else 0.0)
        if best[1] >= s.quick_fuzzy_min and best[1] - second >= s.quick_fuzzy_margin:
            return self._propose("computer.open_app", {"name": best[0].name}, best[0].name, best[1], "fuzzy", allowed_tools)
        
        # Ambiguous case
        return Ambiguous(target, tuple(e.name for e, _ in cands))

    def _strip_prefixes(self, text: str) -> str:
        """Remove polite prefixes from the text."""
        for prefix in self._intents.polite_prefixes:
            if text.casefold().startswith(prefix.casefold()):
                text = text[len(prefix):].strip()
        return text

    def _strip_suffix_words(self, text: str) -> str:
        """Remove suffix words from the text."""
        for suffix in self._intents.suffix_words:
            if text.casefold().endswith(suffix.casefold()):
                text = text[:-len(suffix)].strip()
        return text

    def _as_site(self, target: str) -> str | None:
        """Check if target is a URL or looks like a domain name."""
        target = target.strip()
        
        # Check for URL schemes
        if target.lower().startswith(("http://", "https://")):
            return target
        
        # Check if it looks like a domain (dotted hostname)
        if re.match(r"^[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?$", target, re.IGNORECASE):
            # Make sure it's not a file extension
            last_part = target.split('.')[-1]
            if last_part not in self._intents.file_extensions:
                return "https://" + target
        
        return None

    def _propose(self, tool: str, args: dict[str, str], shown: str, conf: float, 
                 by: Literal["exact","alias","prefix","fuzzy","url","site_alias"], 
                 allowed: Collection[str] | None) -> QuickAction | None:
        """Propose a quick action if the tool is allowed."""
        if allowed is not None and tool not in allowed:
            return None
        return QuickAction(tool, args, shown, conf, by)