"""Canonical payload hashing. An approval is bound to the hash of exactly what will run."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def payload_hash(task_id: str, step_id: str, kind: str, payload: Mapping[str, object]) -> str:
    """SHA-256 over the task, step, kind and payload. Changing any of them changes the hash."""
    return hashlib.sha256(canonical([task_id, step_id, kind, payload]).encode()).hexdigest()
