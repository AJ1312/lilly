"""The SSRF guard: nothing but ordinary public addresses may be fetched."""
from __future__ import annotations

import ipaddress

import pytest

from lilly.domain.errors import ToolError
from lilly.tools.web import guarded_target, ip_is_blocked


@pytest.mark.parametrize("addr", [
    "127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "224.0.0.1",
    "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "64:ff9b::7f00:1", "2002:7f00:1::1",
])
def test_internal_addresses_are_blocked(addr: str) -> None:
    assert ip_is_blocked(ipaddress.ip_address(addr))


@pytest.mark.parametrize("addr", ["1.1.1.1", "93.184.216.34", "2606:4700:4700::1111"])
def test_public_addresses_pass(addr: str) -> None:
    assert not ip_is_blocked(ipaddress.ip_address(addr))


async def test_hostnames_are_resolved_and_every_answer_must_be_public() -> None:
    url, addrs = await guarded_target("https://example.test/x", lambda host, port: ["93.184.216.34"])
    assert addrs == ["93.184.216.34"] and url.host == "example.test"
    with pytest.raises(ToolError, match="public internet"):
        await guarded_target("https://example.test/", lambda host, port: ["93.184.216.34", "10.0.0.5"])


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://[::1]:8787/", "http://169.254.169.254/latest/meta-data"])
async def test_literal_internal_urls_are_blocked(url: str) -> None:
    with pytest.raises(ToolError):
        await guarded_target(url, lambda host, port: [])


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/", "http:///nohost"])
async def test_only_http_and_https_are_fetched(url: str) -> None:
    with pytest.raises(ToolError):
        await guarded_target(url, lambda host, port: ["93.184.216.34"])
