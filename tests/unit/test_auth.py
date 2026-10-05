"""Access token, signed sessions and CSRF tokens."""
from __future__ import annotations

from pathlib import Path

from lilly.ui.security import SESSION_TTL_S, Auth, LoginLimiter
from tests.helpers import Clock


def make(tmp_path: Path, clock: Clock | None = None) -> Auth:
    return Auth(tmp_path / "token", tmp_path / "secret", clock or Clock())


def test_token_and_secret_are_private_files_that_persist(tmp_path: Path) -> None:
    a = make(tmp_path)
    assert (tmp_path / "token").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "secret").stat().st_mode & 0o777 == 0o600
    assert make(tmp_path).token == a.token
    assert a.check_token(a.token) and not a.check_token("wrong") and not a.check_token("")


def test_session_cookie_verifies_expires_and_resists_tampering(tmp_path: Path) -> None:
    clock = Clock()
    a = make(tmp_path, clock)
    cookie = a.issue_session()
    assert a.valid_session(cookie)
    assert not a.valid_session(None) and not a.valid_session("garbage") and not a.valid_session("9999999999.00")
    expires, _, sig = cookie.partition(".")
    assert not a.valid_session(f"{int(expires) + 1000}.{sig}")
    clock.advance(SESSION_TTL_S + 1)
    assert not a.valid_session(cookie)


def test_csrf_token_is_bound_to_the_session(tmp_path: Path) -> None:
    clock = Clock()
    a = make(tmp_path, clock)
    c1 = a.issue_session()
    clock.advance(1)
    c2 = a.issue_session()
    assert a.csrf_token(c1) == a.csrf_token(c1) != a.csrf_token(c2)


def test_sign_out_everywhere_and_token_replacement_invalidate_sessions(tmp_path: Path) -> None:
    a = make(tmp_path)
    cookie, old = a.issue_session(), a.token
    a.sign_out_everywhere()
    assert not a.valid_session(cookie) and a.token == old
    cookie = a.issue_session()
    new = a.replace_token()
    assert new != old and a.check_token(new) and not a.check_token(old) and not a.valid_session(cookie)
    assert make(tmp_path).token == new


def test_login_limiter_blocks_after_repeated_failures_then_recovers() -> None:
    clock = Clock()
    lim = LoginLimiter(3, 60.0, clock)
    for _ in range(3):
        assert not lim.blocked()
        lim.failed()
    assert lim.blocked()
    clock.advance(61)
    assert not lim.blocked()
