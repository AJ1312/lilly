"""Standing approvals: persistent grants for specific tool+target combinations."""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from lilly.store.db import Database


@dataclass(frozen=True, slots=True)
class StandingGrant:
    id: int
    tool: str
    target: str
    created_at: float
    revoked_at: float | None
    uses: int
    last_used_at: float | None


class StandingStore:
    """CRUD for standing grants."""
    
    def __init__(self, db: Database) -> None:
        self._db = db
    
    def add(self, tool: str, target: str, now: float | None = None) -> int:
        """Add a new standing grant. Returns the grant id."""
        if now is None:
            now = time.time()
        
        def _add(con: sqlite3.Connection) -> int:
            cursor = con.cursor()
            cursor.execute(
                "INSERT INTO standing_grants (tool, target, created_at, revoked_at, uses, last_used_at) VALUES (?, ?, ?, NULL, 0, NULL)",
                (tool, target, now)
            )
            return cursor.lastrowid
        
        return self._db.write(_add)
    
    def find(self, tool: str, target: str) -> StandingGrant | None:
        """Find a standing grant by tool and target. Returns None if not found or revoked."""
        def _find(reader: sqlite3.Connection) -> StandingGrant | None:
            cursor = reader.cursor()
            cursor.execute(
                "SELECT id, tool, target, created_at, revoked_at, uses, last_used_at FROM standing_grants WHERE tool = ? AND target = ? AND revoked_at IS NULL",
                (tool, target)
            )
            row = cursor.fetchone()
            if row:
                return StandingGrant(
                    id=row[0], tool=row[1], target=row[2], 
                    created_at=row[3], revoked_at=row[4], 
                    uses=row[5], last_used_at=row[6]
                )
            return None
        
        return self._db.read(_find)
    
    def revoke(self, grant_id: int, now: float | None = None) -> bool:
        """Revoke a standing grant. Returns True if grant was found and revoked."""
        if now is None:
            now = time.time()
        
        def _revoke(con: sqlite3.Connection) -> bool:
            cursor = con.cursor()
            cursor.execute(
                "UPDATE standing_grants SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (now, grant_id)
            )
            return cursor.rowcount > 0
        
        return self._db.write(_revoke)
    
    def touch(self, grant_id: int, now: float | None = None) -> bool:
        """Update last_used_at and increment uses for a grant. Returns True if grant was found."""
        if now is None:
            now = time.time()
        
        def _touch(con: sqlite3.Connection) -> bool:
            cursor = con.cursor()
            cursor.execute(
                "UPDATE standing_grants SET last_used_at = ?, uses = uses + 1 WHERE id = ? AND revoked_at IS NULL",
                (now, grant_id)
            )
            return cursor.rowcount > 0
        
        return self._db.write(_touch)
    
    def list_all(self) -> list[StandingGrant]:
        """List all active (non-revoked) standing grants."""
        def _list(reader: sqlite3.Connection) -> list[StandingGrant]:
            cursor = reader.cursor()
            cursor.execute(
                "SELECT id, tool, target, created_at, revoked_at, uses, last_used_at FROM standing_grants WHERE revoked_at IS NULL ORDER BY tool, target"
            )
            return [
                StandingGrant(
                    id=row[0], tool=row[1], target=row[2], 
                    created_at=row[3], revoked_at=row[4], 
                    uses=row[5], last_used_at=row[6]
                )
                for row in cursor.fetchall()
            ]
        
        return self._db.read(_list)