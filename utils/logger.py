"""Logging with secret redaction.

- Console + rotating file + (optional) SQLite `logs` table.
- Anything registered with register_secret(), and anything that looks like
  `access_token=...`, `api_secret: ...`, `password=...`, is masked before it is written.
- setup_logging() is idempotent (Streamlit re-runs the script often).
"""
from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

LOGGER_NAME = "trading_app"
MASK = "***"
_MIN_SECRET_LEN = 6  # avoid masking every occurrence of a short string like "abc"

_secrets: set[str] = set()
_secrets_lock = threading.Lock()

_KV_PATTERN = re.compile(
    r"""(\b(?:api[_-]?key|api[_-]?secret|access[_-]?token|secret|token|password|passwd)\b["']?\s*[=:]\s*["']?)([^\s,;"'}]+)""",
    re.IGNORECASE,
)


def register_secret(value: Optional[str]) -> None:
    """Remember a secret so it is masked if it ever reaches a log line."""
    if value and len(value) >= _MIN_SECRET_LEN:
        with _secrets_lock:
            _secrets.add(value)


def clear_secrets() -> None:
    with _secrets_lock:
        _secrets.clear()


def redact(text: str) -> str:
    with _secrets_lock:
        known = sorted(_secrets, key=len, reverse=True)
    for secret in known:
        text = text.replace(secret, MASK)
    return _KV_PATTERN.sub(lambda m: m.group(1) + MASK, text)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class DBLogHandler(logging.Handler):
    """Writes log records to db.insert_log(). Never raises into the caller."""

    _trading_app_handler = True

    def __init__(self, db: Any, level: int = logging.INFO):
        super().__init__(level)
        self._db = db

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info:
                message += "\n" + self.formatException(record.exc_info)
            self._db.insert_log(
                level=record.levelname,
                logger_name=record.name,
                message=redact(message),
                timestamp=datetime.fromtimestamp(record.created, tz=timezone.utc),
            )
        except Exception:  # noqa: BLE001 - a logging failure must not crash trading logic
            self.handleError(record)


def get_logger(name: str = "app") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def setup_logging(
    log_dir: Optional[str] = "logs",
    level: int = logging.INFO,
    db: Any = None,
    console: bool = True,
) -> logging.Logger:
    """Configure the 'trading_app' logger. Safe to call repeatedly."""
    root = logging.getLogger(LOGGER_NAME)
    root.setLevel(level)
    root.propagate = False

    for handler in list(root.handlers):
        if getattr(handler, "_trading_app_handler", False):
            root.removeHandler(handler)
            handler.close()

    fmt = RedactingFormatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    new_handlers: list[logging.Handler] = []
    if console:
        new_handlers.append(logging.StreamHandler())
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        new_handlers.append(
            RotatingFileHandler(Path(log_dir) / "app.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        )
    for handler in new_handlers:
        handler.setFormatter(fmt)
        handler._trading_app_handler = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    if db is not None:
        root.addHandler(DBLogHandler(db, level=level))
    return root
