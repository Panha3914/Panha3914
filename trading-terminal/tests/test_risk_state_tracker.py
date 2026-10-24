from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trading_terminal.risk.state_tracker import RiskStateError, RiskStateTracker


def test_tracks_daily_loss_and_drawdown_across_restart(tmp_path: Path) -> None:
    database = tmp_path / "risk.sqlite3"
    first = RiskStateTracker(database)
    t0 = datetime(2026, 10, 24, 0, 1, tzinfo=UTC)
    start = first.observe(account_identity="account-1:USD", equity=10000.0, now=t0)
    assert start.daily_loss_percent == 0.0
    assert start.drawdown_percent == 0.0

    restarted = RiskStateTracker(database)
    lower = restarted.observe(
        account_identity="account-1:USD", equity=9800.0, now=t0 + timedelta(hours=1)
    )
    assert lower.daily_loss_percent == pytest.approx(2.0)
    assert lower.drawdown_percent == pytest.approx(2.0)
    assert lower.day_start_equity == 10000.0


def test_resets_daily_baseline_on_new_utc_day_keeps_peak(tmp_path: Path) -> None:
    tracker = RiskStateTracker(tmp_path / "risk.sqlite3")
    t0 = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    tracker.observe(account_identity="account-1:USD", equity=10000.0, now=t0)
    tracker.observe(account_identity="account-1:USD", equity=10500.0, now=t0 + timedelta(hours=1))

    next_day = tracker.observe(
        account_identity="account-1:USD",
        equity=10200.0,
        now=datetime(2026, 10, 25, 0, 1, tzinfo=UTC),
    )
    assert next_day.day_start_equity == 10200.0
    assert next_day.daily_loss_percent == 0.0
    assert next_day.peak_observed_equity == 10500.0
    assert next_day.drawdown_percent == pytest.approx((10500 - 10200) / 10500 * 100)


def test_accounts_have_separate_state(tmp_path: Path) -> None:
    tracker = RiskStateTracker(tmp_path / "risk.sqlite3")
    now = datetime(2026, 10, 24, tzinfo=UTC)
    tracker.observe(account_identity="first:USD", equity=10000, now=now)
    other = tracker.observe(account_identity="second:USD", equity=5000, now=now)
    assert other.day_start_equity == 5000
    assert other.peak_observed_equity == 5000


def test_rejects_invalid_equity_and_naive_timestamp(tmp_path: Path) -> None:
    tracker = RiskStateTracker(tmp_path / "risk.sqlite3")
    with pytest.raises(RiskStateError, match="finite and positive"):
        tracker.observe(account_identity="account:USD", equity=float("nan"))
    with pytest.raises(RiskStateError, match="timezone-aware"):
        tracker.observe(
            account_identity="account:USD",
            equity=1000,
            now=datetime(2026, 10, 24),
        )


def test_does_not_store_raw_account_identity(tmp_path: Path) -> None:
    database = tmp_path / "risk.sqlite3"
    tracker = RiskStateTracker(database)
    tracker.observe(
        account_identity="private-login-112233:USD",
        equity=1000,
        now=datetime(2026, 10, 24, tzinfo=UTC),
    )
    import sqlite3

    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT account_key FROM observed_equity_state").fetchone()
    assert row is not None
    assert "112233" not in row[0]
