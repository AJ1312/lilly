"""Who may talk to Lilly, and how a request proves it.

* One access token lives in a private file on this computer. Presenting it signs a browser in.
* A browser session is a signed, expiring cookie (HttpOnly, SameSite=Strict). Nothing is stored server side,
  so "sign out everywhere" is simply replacing the signing secret.
* Every state-changing request must be same-origin and carry a CSRF token derived from the session.
* The Host header must be one Lilly expects, which defeats DNS rebinding.
* The authorisation decision is made inside each endpoint's wrapper (`guarded`), not by middleware that a
  new route could forget to be covered by.
"""
from __future__ import annotations

import functools
import hashlib
import hmac
import ipaddress
import os
import secrets
import tempfile
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from lilly.domain.clock import Clock

MAX_BODY_BYTES = 1_048_576
SESSION_TTL_S = 30 * 86400
CSRF_HEADER = "x-lilly-csrf"
COOKIE_PLAIN = "lilly_session"
COOKIE_SECURE = "__Host-lilly_session"
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")

Handler = Callable[[Request], Awaitable[Response]]


def _write_private(path: Path, data: bytes) -> None:
    """Atomically write a 0600 file."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read_or_create(path: Path, make: Callable[[], bytes]) -> bytes:
    try:
        data = path.read_bytes().strip()
    except FileNotFoundError:
        data = b""
    if not data:
        data = make()
        _write_private(path, data + b"\n")
    return data


class LoginLimiter:
    """At most `limit` failed sign-ins per `window_s`, counted for the whole app (there is one owner)."""

    def __init__(self, limit: int = 8, window_s: float = 60.0, clock: Clock = time.monotonic) -> None:
        self._limit, self._window, self._clock = limit, window_s, clock
        self._fails: deque[float] = deque()

    def _prune(self) -> None:
        cutoff = self._clock() - self._window
        while self._fails and self._fails[0] <= cutoff:
            self._fails.popleft()

    def blocked(self) -> bool:
        self._prune()
        return len(self._fails) >= self._limit

    def failed(self) -> None:
        self._fails.append(self._clock())


class Auth:
    """The access token, the cookie-signing secret, and everything derived from them."""

    def __init__(self, token_path: Path, secret_path: Path, clock: Clock = time.time) -> None:
        self._token_path, self._secret_path, self._clock = token_path, secret_path, clock
        self._token = _read_or_create(token_path, lambda: secrets.token_urlsafe(32).encode())
        self._secret = _read_or_create(secret_path, lambda: secrets.token_hex(32).encode())
        self.limiter = LoginLimiter()

    @property
    def token(self) -> str:
        return self._token.decode()

    def check_token(self, candidate: str) -> bool:
        return hmac.compare_digest(candidate.encode(), self._token)

    def _sign(self, label: bytes, value: str) -> str:
        return hmac.new(self._secret, label + b"|" + value.encode(), hashlib.sha256).hexdigest()

    def issue_session(self) -> str:
        expires = str(int(self._clock()) + SESSION_TTL_S)
        return f"{expires}.{self._sign(b'session', expires)}"

    def valid_session(self, cookie: str | None) -> bool:
        if not cookie or "." not in cookie:
            return False
        expires, _, sig = cookie.partition(".")
        if not expires.isdigit() or not hmac.compare_digest(sig.encode(), self._sign(b"session", expires).encode()):
            return False
        return int(expires) > self._clock()

    def csrf_token(self, cookie: str) -> str:
        return self._sign(b"csrf", cookie)

    def sign_out_everywhere(self) -> None:
        """New signing secret: every existing session cookie stops verifying."""
        self._secret = secrets.token_hex(32).encode()
        _write_private(self._secret_path, self._secret + b"\n")

    def replace_token(self) -> str:
        """New access token, and everyone signed out. Returns the new token."""
        self._token = secrets.token_urlsafe(32).encode()
        _write_private(self._token_path, self._token + b"\n")
        self.sign_out_everywhere()
        return self.token


def is_https(request: Request) -> bool:
    """True when the browser reached us over TLS: directly, or through a proxy on this computer
    (Tailscale Serve) that says so. A remote client cannot set this header for us to believe it."""
    if request.url.scheme == "https":
        return True
    client = request.client.host if request.client else ""
    return client in LOOPBACK and request.headers.get("x-forwarded-proto") == "https"


def session_cookie(request: Request) -> str | None:
    return request.cookies.get(COOKIE_SECURE) or request.cookies.get(COOKIE_PLAIN)


def set_session(response: Response, request: Request, value: str) -> None:
    """Attach the session cookie `value` (from `Auth.issue_session`) to a response."""
    secure = is_https(request)
    response.set_cookie(COOKIE_SECURE if secure else COOKIE_PLAIN, value, max_age=SESSION_TTL_S, path="/",
                        httponly=True, secure=secure, samesite="strict")


def clear_session(response: Response) -> None:
    for name in (COOKIE_SECURE, COOKIE_PLAIN):
        response.delete_cookie(name, path="/")


def same_origin(request: Request) -> bool:
    """Browsers say where a request came from; anything cross-site is refused."""
    site = request.headers.get("sec-fetch-site")
    if site is not None and site not in ("same-origin", "none"):
        return False
    origin = request.headers.get("origin")
    return origin is None or urlsplit(origin).netloc == request.headers.get("host", "")


def guarded(fn: Handler, *, public: bool = False) -> Handler:
    """Wrap an endpoint with its access rule. Signed-in endpoints demand a valid session, and the
    state-changing ones also a same-origin request carrying the session's CSRF token."""

    @functools.wraps(fn)
    async def wrapper(request: Request) -> Response:
        mutating = request.method not in SAFE_METHODS
        if mutating and not same_origin(request):
            return JSONResponse({"error": "cross-site request refused"}, 403)
        if not public:
            auth: Auth = request.app.state.auth
            cookie = session_cookie(request)
            if cookie is None or not auth.valid_session(cookie):
                return JSONResponse({"error": "not signed in"}, 401)
            if mutating and not hmac.compare_digest(request.headers.get(CSRF_HEADER, "").encode(), auth.csrf_token(cookie).encode()):
                return JSONResponse({"error": "missing or wrong CSRF token"}, 403)
        return await fn(request)

    return wrapper


def host_of(header: str) -> str:
    """The host name of a Host header, without the port."""
    if header.startswith("["):  # [::1]:8787
        return header[1:].split("]", 1)[0]
    return header.rsplit(":", 1)[0] if header.count(":") == 1 else header


class Shield:
    """Pure ASGI middleware for what must hold for every request: a known Host, a bounded body, and the
    security headers. It makes no authorisation decisions."""

    def __init__(self, app: ASGIApp, extra_hosts: Callable[[], Iterable[str]]) -> None:
        self.app, self._extra_hosts = app, extra_hosts

    def _host_ok(self, header: str) -> bool:
        host = host_of(header.lower())
        if host in LOOPBACK:
            return True
        try:
            if ipaddress.ip_address(host).is_loopback:
                return True
        except ValueError:
            pass
        return host in {h.lower() for h in self._extra_hosts()}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        secure = scope.get("scheme") == "https" or (
            (scope.get("client") or ("", 0))[0] in LOOPBACK and headers.get("x-forwarded-proto") == "https")
        path = scope["path"]

        def decorate(message: Message) -> Message:
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                h["X-Content-Type-Options"] = "nosniff"
                h["Referrer-Policy"] = "no-referrer"
                h["Cross-Origin-Opener-Policy"] = "same-origin"
                h["Cross-Origin-Resource-Policy"] = "same-origin"
                h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
                h["Content-Security-Policy"] = CSP
                h["X-Frame-Options"] = "DENY"
                if path.startswith(("/api/", "/login", "/healthz")):
                    h["Cache-Control"] = "no-store"
                if secure:
                    h["Strict-Transport-Security"] = "max-age=31536000"
            return message

        async def reply(status: int, text: str) -> None:
            response = JSONResponse({"error": text}, status)
            await response(scope, receive, lambda m: send(decorate(m)))

        if not self._host_ok(headers.get("host", "")):
            await reply(400, "unrecognised host")
            return
        declared = headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            await reply(413, "request too large")
            return
        received = 0

        async def limited() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES:  # chunked uploads carry no Content-Length to check up front
                    raise HTTPException(413, "request too large")
            return message

        await self.app(scope, limited, lambda m: send(decorate(m)))
