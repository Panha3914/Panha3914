from datetime import UTC, datetime, timedelta

from trading_terminal.domain.models import MarketBar, Side
from trading_terminal.strategies.ema_crossover import EMACrossoverStrategy


def bars_from_closes(closes: list[float]) -> list[MarketBar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        MarketBar(
            timestamp=start + timedelta(minutes=5 * index),
            open=close,
            high=close + 0.5,
            low=close - 0.5,
            close=close,
            tick_volume=100,
        )
        for index, close in enumerate(closes)
    ]


def test_emits_buy_only_on_latest_closed_bar_cross() -> None:
    strategy = EMACrossoverStrategy(fast_period=3, slow_period=5, atr_period=3)
    signal = strategy.evaluate("XAUUSD", bars_from_closes([10, 9, 8, 7, 6, 7, 8, 9]))
    assert signal is not None
    assert signal.side is Side.BUY
    assert signal.stop_loss is not None and signal.stop_loss < 9
    assert signal.take_profit is not None and signal.take_profit > 9
    assert "signal only, not an order" in signal.rationale


def test_emits_sell_on_downward_cross() -> None:
    strategy = EMACrossoverStrategy(fast_period=3, slow_period=5, atr_period=3)
    signal = strategy.evaluate("XAUUSD", bars_from_closes([6, 7, 8, 9, 10, 9, 8, 7]))
    assert signal is not None
    assert signal.side is Side.SELL
    assert signal.stop_loss is not None and signal.stop_loss > 7
    assert signal.take_profit is not None and signal.take_profit < 7


def test_needs_enough_closed_bars() -> None:
    strategy = EMACrossoverStrategy(fast_period=3, slow_period=5, atr_period=3)
    assert strategy.evaluate("XAUUSD", bars_from_closes([10, 9, 8, 7])) is None


def test_no_signal_when_no_ema_cross_occurs_on_latest_bar() -> None:
    strategy = EMACrossoverStrategy(fast_period=3, slow_period=5, atr_period=3)
    assert strategy.evaluate("XAUUSD", bars_from_closes([6, 7, 8, 9, 10, 11, 12, 13])) is None


def test_rejects_invalid_strategy_periods() -> None:
    try:
        EMACrossoverStrategy(fast_period=9, slow_period=5)
    except ValueError as exc:
        assert "fast_period" in str(exc)
    else:
        raise AssertionError("Expected invalid EMA periods to be rejected")
