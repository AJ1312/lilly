"""Identifier generation."""
from __future__ import annotations

import secrets


def new_id() -> str:
    """A 16-hex-character random identifier. Unguessable, URL-safe, short enough to read."""
    return secrets.token_hex(8)
