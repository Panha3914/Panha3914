import math
from datetime import UTC, datetime, timedelta

from trading_terminal.config import Settings
from trading_terminal.domain.models import OrderIntent, Quote, RiskStatus, Side
from trading_terminal.risk.manager import RiskManager

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def make_intent(**overrides: object) -> OrderIntent:
    values: dict[str, object] = {"symbol": "XAUUSD", "side": Side.BUY, "volume": 0.01,
        "stop_loss": 2300.0, "created_at": NOW, "idempotency_key": "test-1"}
    values.update(overrides)
    return OrderIntent(**values)  # type: ignore[arg-type]


def make_quote(**overrides: object) -> Quote:
    values: dict[str, object] = {"symbol": "XAUUSD", "bid": 2400.0, "ask": 2400.2,
        "timestamp": NOW, "point": 0.01}
    values.update(overrides)
    return Quote(**values)  # type: ignore[arg-type]


def make_manager(**overrides: object) -> RiskManager:
    return RiskManager(Settings(**overrides))


def check(risk: RiskManager, order: OrderIntent | None = None, market: Quote | None = None):
    return risk.validate(order or make_intent(), market or make_quote(), open_positions=0,
        daily_loss_percent=0.0, drawdown_percent=0.0, account_state_known=True, now=NOW)


def test_defaults_fail_closed_with_kill_switch() -> None:
    decision = check(make_manager())
    assert decision.status is RiskStatus.REJECTED
    assert "kill_switch_enabled" in decision.reasons


def test_approves_valid_proposal_when_kill_switch_disabled() -> None:
    assert check(make_manager(kill_switch=False)).status is RiskStatus.APPROVED


def test_rejects_stale_quote() -> None:
    stale = make_quote(timestamp=NOW - timedelta(seconds=20))
    decision = check(make_manager(kill_switch=False), market=stale)
    assert "stale_quote" in decision.reasons


def test_rejects_excessive_spread() -> None:
    wide = make_quote(ask=2401.0)
    decision = check(make_manager(kill_switch=False, max_spread_points=5), market=wide)
    assert "spread_limit_exceeded" in decision.reasons


def test_rejects_unknown_account_state() -> None:
    decision = make_manager(kill_switch=False).validate(
        make_intent(), make_quote(), open_positions=0, daily_loss_percent=0,
        drawdown_percent=0, account_state_known=False, now=NOW)
    assert "account_state_unknown" in decision.reasons


def test_rejects_volume_above_limit() -> None:
    decision = check(make_manager(kill_switch=False), order=make_intent(volume=0.02))
    assert "volume_out_of_bounds" in decision.reasons


def test_rejects_position_and_loss_limits() -> None:
    risk = make_manager(kill_switch=False, max_open_positions=1)
    decision = risk.validate(make_intent(), make_quote(), open_positions=1, daily_loss_percent=2.0,
        drawdown_percent=0.0, account_state_known=True, now=NOW)
    assert "open_position_limit_reached" in decision.reasons
    assert "daily_loss_limit_reached" in decision.reasons


def test_rejects_future_quote_timestamp() -> None:
    future = make_quote(timestamp=NOW + timedelta(seconds=1))
    decision = check(make_manager(kill_switch=False), market=future)
    assert "quote_timestamp_in_future" in decision.reasons


def test_rejects_buy_stop_loss_at_or_above_bid() -> None:
    decision = check(make_manager(kill_switch=False), order=make_intent(stop_loss=2400.0))
    assert "buy_stop_loss_must_be_below_bid" in decision.reasons


def test_rejects_sell_stop_loss_at_or_below_ask() -> None:
    order = make_intent(side=Side.SELL, stop_loss=2400.0)
    decision = check(make_manager(kill_switch=False), order=order)
    assert "sell_stop_loss_must_be_above_ask" in decision.reasons


def test_rejects_nan_quote_and_volume() -> None:
    market = make_quote(bid=math.nan)
    order = make_intent(volume=math.nan)
    decision = check(make_manager(kill_switch=False), order=order, market=market)
    assert "invalid_quote" in decision.reasons
    assert "volume_out_of_bounds" in decision.reasons


def test_rejects_naive_quote_timestamp() -> None:
    naive = make_quote(timestamp=datetime(2026, 1, 1, 12, 0))
    decision = check(make_manager(kill_switch=False), market=naive)
    assert "quote_timestamp_must_be_timezone_aware" in decision.reasons


def test_rejects_unknown_daily_and_drawdown_baselines() -> None:
    decision = make_manager(kill_switch=False).validate(
        make_intent(), make_quote(), open_positions=0,
        daily_loss_percent=None, drawdown_percent=None,
        account_state_known=True, now=NOW,
    )
    assert "daily_loss_state_unknown" in decision.reasons
    assert "drawdown_state_unknown" in decision.reasons
