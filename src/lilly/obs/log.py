"""JSON-lines logging with redaction filter and file rotation."""
from __future__ import annotations

import json
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from lilly.domain.reasoning import redact

MAX_LOG_BYTES = 5 * 1024 * 1024   # 5 MB per file
BACKUP_COUNT = 5                   # 5 backups = 25 MB total cap


class RedactingFormatter(logging.Formatter):
    """Formats log records as JSON lines after applying the redaction filter."""

    def format(self, record: logging.LogRecord) -> str:
        raw_msg = record.getMessage()
        safe_msg = redact(raw_msg)

        data: dict[str, Any] = {
            "timestamp": time.time(),
            "level": record.levelname,
            "logger": record.name,
            "message": safe_msg,
        }
        if record.exc_info:
            data["exception"] = redact(self.formatException(record.exc_info))

        # Include custom extra fields if present
        if hasattr(record, "task_id"):
            data["task_id"] = record.task_id
        if hasattr(record, "step_id"):
            data["step_id"] = record.step_id

        return json.dumps(data)


def setup_logging(
    log_dir: Path | str,
    level: int = logging.INFO,
    max_bytes: int = MAX_LOG_BYTES,
    backup_count: int = BACKUP_COUNT,
) -> logging.Logger:
    """Configure the root lilly logger with rotating JSON-lines output and redaction."""
    p = Path(log_dir)
    p.mkdir(parents=True, exist_ok=True)
    log_file = p / "lilly.jsonl"

    logger = logging.getLogger("lilly")
    logger.setLevel(level)

    # Avoid duplicate handlers on re-initialization
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = RotatingFileHandler(
        str(log_file),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(RedactingFormatter())
    logger.addHandler(handler)
    logger.propagate = False

    return logger
