from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trading_terminal.audit.jsonl import JsonlAuditLogger
from trading_terminal.config import Settings
from trading_terminal.domain.models import Quote, Side, TradeSignal
from trading_terminal.execution.engine import PaperOrderEngine, PaperOrderStatus
from trading_terminal.execution.paper_portfolio import PaperPortfolio
from trading_terminal.mt5.adapter import SymbolSpec

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def sample_quote(**overrides: object) -> Quote:
    values: dict[str, object] = {
        "symbol": "XAUUSD",
        "bid": 2700.0,
        "ask": 2700.2,
        "timestamp": NOW,
        "point": 0.01,
    }
    values.update(overrides)
    return Quote(**values)  # type: ignore[arg-type]


def sample_spec(**overrides: object) -> SymbolSpec:
    values: dict[str, object] = {
        "symbol": "XAUUSD",
        "digits": 2,
        "point": 0.01,
        "contract_size": 100.0,
        "tick_size": 0.01,
        "tick_value_profit_per_lot": 1.0,
        "tick_value_loss_per_lot": 1.0,
        "volume_min": 0.01,
        "volume_max": 50.0,
        "volume_step": 0.01,
        "trade_stops_level": 10,
    }
    values.update(overrides)
    return SymbolSpec(**values)  # type: ignore[arg-type]


def sample_signal(**overrides: object) -> TradeSignal:
    values: dict[str, object] = {
        "symbol": "XAUUSD",
        "side": Side.BUY,
        "timestamp": NOW,
        "rationale": "test signal",
        "stop_loss": 2690.0,
        "take_profit": 2720.0,
    }
    values.update(overrides)
    return TradeSignal(**values)  # type: ignore[arg-type]


def engine(tmp_path: Path, **setting_overrides: object) -> PaperOrderEngine:
    settings_values: dict[str, object] = {
        "kill_switch": False,
        "max_risk_per_trade_percent": 0.25,
        "max_position_volume": 0.05,
    }
    settings_values.update(setting_overrides)
    settings = Settings(**settings_values)  # type: ignore[arg-type]
    return PaperOrderEngine(
        settings,
        audit=JsonlAuditLogger(tmp_path / "audit.jsonl"),
    )


def process(bot: PaperOrderEngine, signal: TradeSignal | None = None, **kwargs: object):
    args: dict[str, object] = {
        "account_equity": 10000.0,
        "open_positions": 0,
        "daily_loss_percent": 0.0,
        "drawdown_percent": 0.0,
        "account_state_known": True,
        "now": NOW,
    }
    args.update(kwargs)
    return bot.process_signal(
        signal or sample_signal(), sample_quote(), sample_spec(), **args  # type: ignore[arg-type]
    )


def test_proposes_paper_order_after_risk_checks_without_broker_submission(tmp_path: Path) -> None:
    result = process(engine(tmp_path))
    assert result.status is PaperOrderStatus.PROPOSED
    assert result.volume == pytest.approx(0.02)
    assert result.entry_price == pytest.approx(2700.22)
    assert result.order_id is not None
    assert "no broker order was sent" in result.message


def test_kill_switch_rejects_paper_proposal(tmp_path: Path) -> None:
    result = process(engine(tmp_path, kill_switch=True))
    assert result.status is PaperOrderStatus.REJECTED
    assert "kill_switch_enabled" in result.reasons


def test_unknown_daily_risk_state_fails_closed(tmp_path: Path) -> None:
    result = process(engine(tmp_path), daily_loss_percent=None)
    assert result.status is PaperOrderStatus.REJECTED
    assert "daily_loss_state_unknown" in result.reasons


def test_symbol_mismatch_rejects_proposal(tmp_path: Path) -> None:
    result = engine(tmp_path).process_signal(
        sample_signal(symbol="GOLD"), sample_quote(), sample_spec(),
        account_equity=10000, open_positions=0, daily_loss_percent=0,
        drawdown_percent=0, account_state_known=True, now=NOW,
    )
    assert result.status is PaperOrderStatus.REJECTED
    assert "symbol_mismatch" in result.reasons


def test_duplicate_signal_is_not_proposed_twice(tmp_path: Path) -> None:
    bot = engine(tmp_path)
    first = process(bot)
    second = process(bot)
    assert first.status is PaperOrderStatus.PROPOSED
    assert second.status is PaperOrderStatus.DUPLICATE
    assert second.order_id == first.order_id


def test_stale_quote_is_rejected(tmp_path: Path) -> None:
    bot = engine(tmp_path)
    stale_signal = sample_signal(timestamp=NOW - timedelta(minutes=10))
    result = bot.process_signal(
        stale_signal, sample_quote(timestamp=NOW - timedelta(minutes=10)), sample_spec(),
        account_equity=10000, open_positions=0, daily_loss_percent=0,
        drawdown_percent=0, account_state_known=True, now=NOW,
    )
    assert result.status is PaperOrderStatus.REJECTED
    assert "stale_quote" in result.reasons


def test_non_paper_mode_is_not_supported(tmp_path: Path) -> None:
    result = process(engine(tmp_path, trading_mode="demo"))
    assert result.status is PaperOrderStatus.REJECTED
    assert "paper_mode_required" in result.reasons


def test_tp_wrong_side_is_rejected(tmp_path: Path) -> None:
    result = process(engine(tmp_path), signal=sample_signal(take_profit=2700.0))
    assert result.status is PaperOrderStatus.REJECTED
    assert "buy_take_profit_must_be_above_ask" in result.reasons



def test_paper_portfolio_records_simulated_fill(tmp_path: Path) -> None:
    settings = Settings(
        kill_switch=False,
        max_risk_per_trade_percent=0.25,
        max_position_volume=0.05,
        paper_state_db_path=str(tmp_path / "portfolio.sqlite3"),
    )
    portfolio = PaperPortfolio(
        tmp_path / "portfolio.sqlite3",
        starting_balance=10000.0,
        slippage_points=2.0,
    )
    bot = PaperOrderEngine(
        settings,
        audit=JsonlAuditLogger(tmp_path / "audit.jsonl"),
        paper_portfolio=portfolio,
    )
    args: dict[str, object] = {
        "account_equity": 10000.0,
        "open_positions": 0,
        "daily_loss_percent": 0.0,
        "drawdown_percent": 0.0,
        "account_state_known": True,
        "currency": "USD",
        "now": NOW,
    }
    result = bot.process_signal(sample_signal(), sample_quote(), sample_spec(), **args)  # type: ignore[arg-type]
    assert result.status is PaperOrderStatus.FILLED
    assert "no broker order was sent" in result.message
    snapshot = portfolio.snapshot(sample_quote(), sample_spec(), currency="USD", now=NOW)
    assert snapshot.open_position_count == 1
    assert snapshot.open_positions[0].signal_key == result.signal_key
