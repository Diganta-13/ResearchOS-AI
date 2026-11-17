"""ResearchOS AI — Structured Logging & Secret Redaction Engine."""

import json
import logging
import re
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from researchos.core.config import get_settings

# Sensitive keys and patterns that must be redacted from all log streams
SENSITIVE_KEY_PATTERNS = [
    re.compile(r"api[-_]?key", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"authorization", re.IGNORECASE),
    re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]+", re.IGNORECASE),
]

REDACTED_STR = "[REDACTED]"


def redact_sensitive_data(data: Any) -> Any:
    """Recursively traverses dictionaries, lists, and strings to redact credentials."""
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            if any(p.search(str(k)) for p in SENSITIVE_KEY_PATTERNS):
                cleaned[k] = REDACTED_STR
            else:
                cleaned[k] = redact_sensitive_data(v)
        return cleaned
    if isinstance(data, list):
        return [redact_sensitive_data(item) for item in data]
    if isinstance(data, str):
        result = data
        for pattern in SENSITIVE_KEY_PATTERNS:
            if pattern.search(result):
                # Avoid redacting plain words like 'token' if part of prose, but catch assignments
                result = re.sub(
                    r"(api[-_]?key|secret|password|token)\s*[:=]\s*['\"]?[^\s,'\"]+['\"]?",
                    r"\1=" + REDACTED_STR,
                    result,
                    flags=re.IGNORECASE,
                )
                result = re.sub(
                    r"Bearer\s+[a-zA-Z0-9_\-\.]+",
                    f"Bearer {REDACTED_STR}",
                    result,
                    flags=re.IGNORECASE,
                )
        return result
    return data


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as JSON lines with timestamp, level, and redacted metadata."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_data(record.getMessage()),
            "source": f"{record.filename}:{record.lineno}",
        }

        # Include structured extra fields if attached to the record
        if hasattr(record, "details") and isinstance(record.details, dict):
            log_payload["details"] = redact_sensitive_data(record.details)

        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_payload)


class HumanReadableFormatter(logging.Formatter):
    """Standard console log formatter for local development."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = redact_sensitive_data(record.getMessage())
        base = f"[{ts}] [{record.levelname:<8}] [{record.name}] {msg}"
        if hasattr(record, "details") and record.details:
            base += f" | {redact_sensitive_data(record.details)}"
        if record.exc_info:
            base += f"\n{self.formatException(record.exc_info)}"
        return base


def setup_logging(log_level: int = logging.INFO) -> None:
    """Configures structured console and rotating JSON file log handlers on Drive D:."""
    settings = get_settings()
    log_dir = Path(settings.paths.logs)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "researchos.log"

    root_logger = logging.getLogger("researchos")
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    # 1. Console Stream Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(HumanReadableFormatter())
    root_logger.addHandler(console_handler)

    # 2. Rotating JSON File Handler (Max 10 MB per file, 5 historical rotations)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(StructuredJsonFormatter())
    root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Returns a namespaced logger prefixed with 'researchos'."""
    if not name.startswith("researchos"):
        name = f"researchos.{name}"
    return logging.getLogger(name)
