import json
from datetime import UTC, datetime
from pathlib import Path

from trading_terminal.audit.jsonl import JsonlAuditLogger


def test_writes_valid_jsonl_and_utc_timestamp(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "events.jsonl"
    audit = JsonlAuditLogger(path)
    audit.write("signal_detected", {"symbol": "XAUUSD", "price": 2700.2})
    audit.write("risk_rejected", {"reasons": ["stale_quote"]})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["event_type"] == "signal_detected"
    parsed_time = datetime.fromisoformat(first["timestamp_utc"])
    assert parsed_time.tzinfo == UTC
    assert first["fields"]["symbol"] == "XAUUSD"


def test_redacts_sensitive_fields_recursively(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    JsonlAuditLogger(path).write("diagnostic", {
        "bot_token": "must-not-leak",
        "nested": {"password": "also-secret", "safe_value": 5},
        "account_login": 123456,
    })
    rendered = path.read_text(encoding="utf-8")
    assert "must-not-leak" not in rendered
    assert "also-secret" not in rendered
    assert '"123456"' not in rendered
    row = json.loads(rendered)
    assert row["fields"]["bot_token"] == "[REDACTED]"
    assert row["fields"]["nested"]["password"] == "[REDACTED]"


def test_non_finite_numbers_are_serialized_as_null(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    JsonlAuditLogger(path).write("quote_warning", {"spread": float("nan")})
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["fields"]["spread"] is None


def test_blank_event_type_is_rejected(tmp_path: Path) -> None:
    try:
        JsonlAuditLogger(tmp_path / "events.jsonl").write(" ", {})
    except ValueError as exc:
        assert "event_type" in str(exc)
    else:
        raise AssertionError("Expected blank event name to be rejected")
