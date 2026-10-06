"""Small text helpers shared by the planner and tools."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser

_FENCE = re.compile(r"^\s*```[a-zA-Z0-9]*\s*|\s*```\s*$")


_FENCE_TAG = re.compile(r"<\s*(/?)\s*untrusted_data\s*>", re.IGNORECASE)

OPEN, CLOSE = "<untrusted_data>", "</untrusted_data>"
	

def neutralise(text: str) -> str:
    """Break any fence-like tag inside the text. It stays readable ('&lt;/untrusted_data>') but cannot close ours."""
    return _FENCE_TAG.sub(lambda m: m.group(0).replace("<", "&lt;", 1), text)


def fence(text: str, limit: int | None = None) -> tuple[str, bool]:
    """Truncate FIRST, neutralise, then wrap. Returns (fenced, was_truncated). The closing tag is always present."""
    cut = limit is not None and len(text) > limit
    body = neutralise(text[:limit] if cut else text)
    return f"{OPEN}\n{body}\n{CLOSE}", cut


def fence_untrusted(text: str) -> str:
    """Wrap text that came from outside so a model reads it as data. A closing tag inside the text is defused,
    so the text cannot end the fence early."""
    return f"<untrusted_data>{_FENCE_TAG.sub(lambda m: f'[{m.group(1)}untrusted_data]', text)}</untrusted_data>"


def extract_json(text: str) -> object:
    """Parse the first JSON object or array in `text`, tolerating Markdown fences and surrounding prose.

    Models often wrap JSON in a code fence or a sentence. Raises ValueError when there is none.
    """
    stripped = _FENCE.sub("", text.strip())
    try:
        return json.loads(stripped)
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(stripped):
        if ch in "{[":
            try:
                value, _ = decoder.raw_decode(stripped, i)
            except ValueError:
                continue
            return value
    raise ValueError("no JSON found")


class _TextExtractor(HTMLParser):
    _SKIP = frozenset({"script", "style", "noscript", "svg", "template", "head"})
    _BLOCK = frozenset({"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article",
                        "ul", "ol", "table", "blockquote", "pre", "header", "footer"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Readable text from HTML: no scripts, styles or markup, whitespace collapsed."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    body = re.sub(r"[ \t\r\f\v]+", " ", "".join(parser.parts))
    body = re.sub(r"\n\s*\n+", "\n\n", re.sub(r" ?\n ?", "\n", body)).strip()
    title = " ".join(parser.title.split())
    return f"{title}\n\n{body}" if title else body
