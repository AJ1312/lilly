"""Web tools. web.fetch is SSRF-guarded and DNS-pinned; everything it returns is marked untrusted."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
from collections.abc import Callable, Mapping
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

import httpx

from lilly.domain.errors import ToolError, ValidationFailed
from lilly.domain.labels import Label
from lilly.domain.ports import KeyStore, ToolContext, ToolResult
from lilly.domain.settings import SearchSettings
from lilly.domain.text import html_to_text
from lilly.tools.base import Tool, int_arg, str_arg

log = logging.getLogger("lilly.tools.web")

MAX_PAGE_BYTES = 1_500_000
MAX_REDIRECTS = 4
MAX_URLS = 4
PAGE_CHARS = 12_000
USER_AGENT = "Mozilla/5.0 (compatible; Lilly; +local)"
# A bracketed IPv6 host is allowed; a closing bracket anywhere else ends the URL (it is prose or JSON punctuation).
_URL_RE = re.compile(r"https?://(?:\[[0-9A-Fa-f:.]+\]|[^\s\"'<>\\)\[\]/?#]+)[^\s\"'<>\\)\]]*")
_TEXT_TYPES = ("text/", "application/json", "application/xml", "application/xhtml+xml", "application/rss+xml",
               "application/atom+xml")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")

Resolver = Callable[[str, int], list[str]]


# ---- SSRF guard -------------------------------------------------------------------------
def ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for anything that is not an ordinary public address, including forms that hide a private
    IPv4 address inside an IPv6 one (mapped, NAT64, 6to4, Teredo) and the carrier-grade NAT range
    that Tailscale uses."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip_is_blocked(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            return ip_is_blocked(ip.sixtofour)
        if ip.teredo is not None:
            return any(ip_is_blocked(part) for part in ip.teredo)
        if ip in _NAT64:
            return ip_is_blocked(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return not ip.is_global or ip.is_multicast


def _resolve(host: str, port: int) -> list[str]:
    try:
        return list(dict.fromkeys(str(i[4][0]) for i in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    except socket.gaierror as exc:
        raise ToolError(f"could not look up {host}") from exc


async def guarded_target(url: str, resolver: Resolver) -> tuple[httpx.URL, list[str]]:
    """Validate `url` and return it with the addresses it may be fetched from. Every address the
    name resolves to must be public, and the caller connects to those addresses directly, so a
    second DNS answer cannot swap in an internal one."""
    try:
        parsed = urlparse(url)
        port_given = parsed.port
    except ValueError:
        raise ToolError("that is not a valid URL") from None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ToolError("only http and https URLs can be fetched")
    host = parsed.hostname
    port = port_given or (443 if parsed.scheme == "https" else 80)
    try:
        literal = ipaddress.ip_address(host)
        addresses = [str(literal)]
    except ValueError:
        addresses = await asyncio.to_thread(resolver, host, port)
    if not addresses:
        raise ToolError(f"could not look up {host}")
    for addr in addresses:
        try:
            blocked = ip_is_blocked(ipaddress.ip_address(addr))
        except ValueError:
            blocked = True
        if blocked:
            raise ToolError("that address is not on the public internet")
    return httpx.URL(url), addresses


# ---- HTTP helpers -------------------------------------------------------------------------
async def read_capped(resp: httpx.Response, max_bytes: int) -> bytes:
    """Read a streamed response, stopping at `max_bytes` rather than buffering the whole thing."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in resp.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            chunks.append(chunk[: max_bytes - (total - len(chunk))])
            break
        chunks.append(chunk)
    return b"".join(chunks)


# ---- web.fetch ---------------------------------------------------------------------------
class WebFetchTool(Tool):
    name = "web.fetch"

    def __init__(self, resolver: Resolver = _resolve, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._resolver, self._transport = resolver, transport

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        urls = self._urls(args.get("urls", args.get("url")))
        if not urls:
            raise ValidationFailed("no http(s) URL given")
        results = await asyncio.gather(*(self._fetch_one(u, ctx.deadline_s) for u in urls), return_exceptions=True)
        sections, failures = [], 0
        for url, res in zip(urls, results, strict=True):
            if isinstance(res, ToolError):
                failures += 1
                sections.append(f"## {url}\n[could not fetch: {res}]")
            elif isinstance(res, BaseException):
                raise res
            else:
                sections.append(f"## {url}\n{res}")
        if failures == len(urls):
            raise ToolError("; ".join(s.split("\n", 1)[1] for s in sections))
        return ToolResult("\n\n".join(sections), Label.PUBLIC, True)

    @staticmethod
    def _urls(raw: object) -> list[str]:
        found: list[str] = []
        items = raw if isinstance(raw, list) else [raw]
        for item in items:
            if isinstance(item, str):
                found += _URL_RE.findall(item)
            elif isinstance(item, dict) and isinstance(item.get("url"), str):
                found.append(item["url"])
        return list(dict.fromkeys(u.rstrip(".,;") for u in found))[:MAX_URLS]

    async def _fetch_one(self, url: str, deadline_s: float) -> str:
        try:
            async with asyncio.timeout(min(deadline_s, 30.0)):
                return await self._get(url)
        except TimeoutError as exc:
            raise ToolError("timed out") from exc
        except httpx.HTTPError as exc:  # a dropped connection or a read timeout must not abort the other URLs
            raise ToolError("the connection failed") from exc

    async def _get(self, url: str) -> str:
        async with httpx.AsyncClient(transport=self._transport, follow_redirects=False, trust_env=False,
                                     timeout=httpx.Timeout(10.0)) as client:
            for _ in range(MAX_REDIRECTS + 1):
                target, addresses = await guarded_target(url, self._resolver)
                resp = await self._request_pinned(client, target, addresses)
                try:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            raise ToolError("redirect without a destination")
                        url = urljoin(url, location)
                        continue
                    if resp.status_code >= 400:
                        raise ToolError(f"the site answered HTTP {resp.status_code}")
                    ctype = resp.headers.get("content-type", "text/plain").split(";")[0].strip().lower()
                    if not ctype.startswith(_TEXT_TYPES):
                        raise ToolError(f"not a text page ({ctype})")
                    raw = await read_capped(resp, MAX_PAGE_BYTES)
                    text = raw.decode(resp.encoding or "utf-8", errors="replace")
                    if "html" in ctype or "xml" in ctype:
                        text = html_to_text(text)
                    return text[:PAGE_CHARS] + ("\n[page truncated]" if len(text) > PAGE_CHARS else "")
                finally:
                    await resp.aclose()
        raise ToolError("too many redirects")

    @staticmethod
    async def _request_pinned(client: httpx.AsyncClient, target: httpx.URL, addresses: list[str]) -> httpx.Response:
        """Connect to a validated address, keeping the original Host header and TLS name."""
        last: Exception | None = None
        for addr in addresses:
            literal = f"[{addr}]" if ":" in addr else addr
            pinned = target.copy_with(host=literal)
            headers = {"Host": target.netloc.decode(), "User-Agent": USER_AGENT,
                       "Accept": "text/html,text/plain,application/json;q=0.9,*/*;q=0.1"}
            request = client.build_request("GET", pinned, headers=headers,
                                           extensions={"sni_hostname": target.host})
            try:
                return await client.send(request, stream=True)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last = exc
        raise ToolError("could not connect") from last


# ---- web.search --------------------------------------------------------------------------
class _DuckParser(HTMLParser):
    """Pull result links and snippets out of DuckDuckGo's HTML endpoint."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._cur: str | None = None  # 'a' title or 's' snippet
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "a" and "result__a" in cls:
            href = a.get("href") or ""
            if href.startswith("//"):
                href = "https:" + href
            target = parse_qs(urlparse(href).query).get("uddg")
            url = target[0] if target else href
            if url.startswith(("http://", "https://")):
                self.results.append({"title": "", "url": url, "snippet": ""})
                self._cur, self._buf = "a", []
        elif tag in ("a", "div") and "result__snippet" in cls and self.results:
            self._cur, self._buf = "s", []

    def handle_endtag(self, tag: str) -> None:
        if self._cur and tag in ("a", "div") and self.results:
            text = " ".join("".join(self._buf).split())
            self.results[-1]["title" if self._cur == "a" else "snippet"] = text
            self._cur = None

    def handle_data(self, data: str) -> None:
        if self._cur:
            self._buf.append(data)


def _json_object(body: bytes, who: str) -> dict[str, Any]:
    """The JSON object a search engine returned, or a ToolError saying it did not return one."""
    try:
        data = json.loads(body)
    except ValueError:
        raise ToolError(f"{who} did not return JSON") from None
    if not isinstance(data, dict):
        raise ToolError(f"{who} returned an unexpected answer")
    return data


class WebSearchTool(Tool):
    name = "web.search"

    def __init__(self, client: httpx.AsyncClient, keys: KeyStore, config: SearchSettings) -> None:
        self._client, self._keys, self._config = client, keys, config

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        query = str_arg(args, "query", max_len=300).strip()
        limit = int_arg(args, "max_results", 6, lo=1, hi=10)
        engine = self._config.engine
        try:
            async with asyncio.timeout(min(ctx.deadline_s, 25.0)):
                if engine == "brave":
                    results = await self._brave(query, limit)
                elif engine == "searxng":
                    results = await self._searxng(query, limit)
                else:
                    results = await self._duckduckgo(query, limit)
        except TimeoutError as exc:
            raise ToolError("the search engine timed out") from exc
        except httpx.HTTPError as exc:
            raise ToolError("could not reach the search engine") from exc
        if not results:
            raise ToolError("no results (the search engine may be rate limiting; "
                            "set a different engine in Settings → Privacy & access)")
        return ToolResult(json.dumps(results[:limit], indent=1), Label.PUBLIC, True)

    async def _get(self, url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
        async with self._client.stream("GET", url, headers={"User-Agent": USER_AGENT, **headers},
                                       timeout=15.0) as resp:
            return resp.status_code, await read_capped(resp, MAX_PAGE_BYTES)

    async def _duckduckgo(self, query: str, limit: int) -> list[dict[str, str]]:
        status, body = await self._get(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}", {})
        if status != 200:
            raise ToolError(f"DuckDuckGo answered HTTP {status}")
        parser = _DuckParser()
        parser.feed(body.decode("utf-8", errors="replace"))
        return [r for r in parser.results if r["title"]][:limit]

    async def _searxng(self, query: str, limit: int) -> list[dict[str, str]]:
        base = (self._config.searxng_url or "").rstrip("/")
        status, body = await self._get(f"{base}/search?q={quote_plus(query)}&format=json", {})
        if status != 200:
            raise ToolError(f"SearXNG answered HTTP {status} (is JSON output enabled on that instance?)")
        rows = _json_object(body, "SearXNG").get("results", [])
        return [{"title": str(r.get("title", "")), "url": str(r.get("url", "")), "snippet": str(r.get("content", ""))}
                for r in rows if isinstance(r, dict) and r.get("url")][:limit]

    async def _brave(self, query: str, limit: int) -> list[dict[str, str]]:
        key = await asyncio.to_thread(self._keys.get, "brave")
        if key is None:
            raise ToolError("no Brave Search key saved (Settings → Models & keys)")
        status, body = await self._get(
            f"https://api.search.brave.com/res/v1/web/search?q={quote_plus(query)}&count={limit}",
            {"X-Subscription-Token": key.reveal(), "Accept": "application/json"})
        if status != 200:
            raise ToolError(f"Brave Search answered HTTP {status}")
        web = _json_object(body, "Brave Search").get("web", {})
        rows = web.get("results", []) if isinstance(web, dict) else []
        return [{"title": str(r.get("title", "")), "url": str(r.get("url", "")), "snippet": str(r.get("description", ""))}
                for r in rows if isinstance(r, dict) and r.get("url")][:limit]


class WebResearchTool(Tool):
    """Search the web and read the top results in one step."""

    name = "web.research"

    def __init__(self, search_tool: WebSearchTool, fetch_tool: WebFetchTool) -> None:
        self._search = search_tool
        self._fetch = fetch_tool

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        query = str_arg(args, "query", max_len=300).strip()
        max_sources = int_arg(args, "max_sources", 3, lo=1, hi=5)

        # 1. Search web
        search_res = await self._search.run({"query": query, "max_results": max_sources}, ctx)
        try:
            items = json.loads(search_res.output)
            if not isinstance(items, list):
                items = []
        except Exception:
            items = []

        if not items:
            return ToolResult("No research results found for query.", Label.PUBLIC, True)

        sources_to_fetch = items[:max_sources]
        out_sections: list[str] = []
        for item in sources_to_fetch:
            title = item.get("title", "Untitled")
            url = item.get("url", "")
            snippet = item.get("snippet", "")
            excerpt = snippet
            if url:
                try:
                    fetch_res = await self._fetch.run({"urls": [url]}, ctx)
                    fetched_text = fetch_res.output
                    if fetched_text.startswith(f"## {url}\n"):
                        fetched_text = fetched_text[len(f"## {url}\n"):].strip()
                    if fetched_text and not fetched_text.startswith("[could not fetch"):
                        excerpt = fetched_text[:1200]
                except (ToolError, httpx.HTTPError, TimeoutError) as exc:
                    log.debug("could not fetch research source %s: %s", url, exc)
            out_sections.append(f"### {title}\nURL: {url}\nExcerpt:\n{excerpt}")

        body = "\n\n---\n\n".join(out_sections)
        return ToolResult(body, Label.PUBLIC, True)
