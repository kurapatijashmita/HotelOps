"""Structured logging configuration for HotelOps.

Configures Python standard-library logging to output human-readable messages to console
and machine-readable JSON lines to `logs/app.log`.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
DEFAULT_LOG_FILE = LOGS_DIR / "app.log"
LOG_FILE_PATH = Path(os.environ.get("HOTELOPS_LOG_PATH", str(DEFAULT_LOG_FILE)))


class JsonFormatter(logging.Formatter):
    """Format log records as structured JSON strings."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Include custom structured attributes if provided in record.__dict__
        for key in ("event", "method", "path", "status_code", "duration_ms", "client_ip", "error"):
            if hasattr(record, key):
                log_payload[key] = getattr(record, key)

        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_payload)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Initialize and configure console and file loggers."""
    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    logger = logging.getLogger("hotelops")
    logger.setLevel(level)
    logger.propagate = False

    # Prevent duplicate handlers on reload
    if logger.handlers:
        return logger

    # 1. Console Handler (developer friendly)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 2. File Handler (JSON structured for SRE observability & log parsers)
    file_handler = logging.FileHandler(str(LOG_FILE_PATH), encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(JsonFormatter())
    logger.addHandler(file_handler)

    return logger


# Global logger instance
logger = setup_logging()


def log_http_transaction(
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    client_ip: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Log an HTTP request/response transaction with structured metadata."""
    level = logging.INFO
    if 400 <= status_code < 500:
        level = logging.WARNING
    elif status_code >= 500:
        level = logging.ERROR

    msg = f"HTTP {method} {path} -> {status_code} ({duration_ms:.2f}ms)"
    if error:
        msg += f" - Error: {error}"

    logger.log(
        level,
        msg,
        extra={
            "event": "http_request",
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 2),
            "client_ip": client_ip or "unknown",
            "error": error,
        },
    )
