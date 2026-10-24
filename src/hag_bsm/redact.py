"""Keep secret values out of logs.

Secrets are not supposed to be logged at all; this filter is a second line of defence that
replaces any registered secret value with [REDACTED] before a log record is written.
"""

import logging
import threading

_lock = threading.Lock()
_secrets = set()


def register_secret(value: str) -> None:
    if value and len(value) >= 4:
        with _lock:
            _secrets.add(value)


def redact(text: str) -> str:
    with _lock:
        values = sorted(_secrets, key=len, reverse=True)
    for v in values:
        if v in text:
            text = text.replace(v, "[REDACTED]")
    return text


class RedactingFormatter(logging.Formatter):
    """Redacts the fully formatted record, including any traceback text."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging(logs_dir) -> None:
    from logging.handlers import RotatingFileHandler
    logs_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(logs_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
