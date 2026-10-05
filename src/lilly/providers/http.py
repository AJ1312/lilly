"""Shared HTTP client configuration for model providers."""
from __future__ import annotations

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
DEFAULT_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)


def create_http_client(
    limits: httpx.Limits | None = None,
    timeout: httpx.Timeout | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """Create a configured AsyncClient with redirects off, TLS verification on, and strict limits."""
    return httpx.AsyncClient(
        limits=limits or DEFAULT_LIMITS,
        timeout=timeout or DEFAULT_TIMEOUT,
        follow_redirects=False,
        verify=True,
        transport=transport,
    )


LOCAL_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=10.0, pool=10.0)   # read = silence between chunks
LOCAL_LIMITS = httpx.Limits(max_connections=4, max_keepalive_connections=2)


def create_local_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """A client for servers on this computer or private network (Ollama). It ignores proxy environment
    variables on purpose: a system proxy would otherwise be asked to reach 127.0.0.1 and answer 502/403."""
    return httpx.AsyncClient(limits=LOCAL_LIMITS, timeout=LOCAL_TIMEOUT, follow_redirects=False, trust_env=False,
                             transport=transport)
