"""What the browser may fetch. Every request the page makes passes through here before it leaves the computer:
only http(s) (and inline data for images and the like), only public addresses, never downloads."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from collections import OrderedDict
from collections.abc import Callable
from urllib.parse import urlparse

from lilly.tools.web import ip_is_blocked

Resolver = Callable[[str], list[str]]
CACHE_SECONDS = 60.0
CACHE_ENTRIES = 256


def system_resolver(host: str) -> list[str]:
    try:
        return sorted({str(info[4][0]) for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})
    except OSError:
        return []


class NetworkGuard:
    """Allows a request only if its address is on the public internet. `allow_private` exists for tests that serve
    pages from this computer; Lilly itself never sets it."""

    def __init__(self, resolver: Resolver = system_resolver, *, allow_private: bool = False) -> None:
        self._resolve, self._allow_private = resolver, allow_private
        self._seen: OrderedDict[str, tuple[float, bool]] = OrderedDict()

    async def refusal(self, url: str, resource: str) -> str | None:
        """Why this request must not go out, or None."""
        try:
            parts = urlparse(url)
            host = parts.hostname
        except ValueError:
            return "that address is not valid"
        if parts.scheme in ("data", "blob") and resource != "Document":
            return None
        if url == "about:blank":
            return None
        if parts.scheme not in ("http", "https") or not host:
            return "only http and https pages can be opened"
        if self._allow_private:
            return None
        if not await self._public(host):
            return "that address is not on the public internet"
        return None

    async def _public(self, host: str) -> bool:
        now = time.monotonic()
        hit = self._seen.get(host)
        if hit is not None and now - hit[0] < CACHE_SECONDS:
            return hit[1]
        try:
            addresses = [str(ipaddress.ip_address(host))]
        except ValueError:
            addresses = await asyncio.to_thread(self._resolve, host)
        ok = bool(addresses)
        for addr in addresses:
            try:
                ok = ok and not ip_is_blocked(ipaddress.ip_address(addr.split("%")[0]))
            except ValueError:
                ok = False
        self._seen[host] = (now, ok)
        while len(self._seen) > CACHE_ENTRIES:
            self._seen.popitem(last=False)
        return ok
