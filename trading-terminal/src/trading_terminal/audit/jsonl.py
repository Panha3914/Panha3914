"""Append-only JSONL audit writer with recursive sensitive-field redaction."""

from __future__ import annotations

import json
import math
import threading
from collections.abc import Mapping
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "token",
    "secret",
    "authorization",
    "credential",
    "api_key",
    "apikey",
    "access_key",
    "cookie",
    "account_login",
    "account_number",
)


class JsonlAuditLogger:
    """Write small structured events for diagnostics and trade-decision review."""

    def __init__(self, path: str | Path = "logs/trading-terminal.jsonl") -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, event_type: str, fields: Mapping[str, Any] | None = None) -> None:
        event_name = event_type.strip()
        if not event_name:
            raise ValueError("event_type must not be blank")
        safe_fields = self._sanitize(dict(fields or {}))
        record = {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "event_type": event_name[:100],
            "fields": safe_fields,
        }
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.write("\n")

    @classmethod
    def _sanitize(cls, value: Any, key: str = "") -> Any:
        normalized_key = key.casefold().replace("-", "_")
        if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
            return "[REDACTED]"
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                return value.isoformat() + " [naive]"
            return value.astimezone(UTC).isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Enum):
            return cls._sanitize(value.value)
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, Mapping):
            return {str(child_key): cls._sanitize(child_value, str(child_key))
                    for child_key, child_value in value.items()}
        if isinstance(value, (list, tuple, set, frozenset)):
            return [cls._sanitize(item) for item in value]
        return f"<{type(value).__name__}>"
