"""EMA crossover signal generator using only closed market bars.

Signals are informational. This module does not create or submit orders.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from trading_terminal.domain.models import MarketBar, Side, TradeSignal


class EMACrossoverStrategy:
    """Generate a signal only when fast/slow EMAs cross on the latest closed bar."""

    name = "EMA crossover"

    def __init__(
        self,
        *,
        fast_period: int = 9,
        slow_period: int = 21,
        atr_period: int = 14,
        stop_atr_multiple: float = 1.5,
        target_atr_multiple: float = 2.0,
    ) -> None:
        if fast_period < 2 or slow_period <= fast_period:
            raise ValueError("periods must satisfy 2 <= fast_period < slow_period")
        if atr_period < 2:
            raise ValueError("atr_period must be at least 2")
        if (
            not math.isfinite(stop_atr_multiple)
            or not math.isfinite(target_atr_multiple)
            or stop_atr_multiple <= 0
            or target_atr_multiple <= 0
        ):
            raise ValueError("ATR multiples must be finite and positive")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.atr_period = atr_period
        self.stop_atr_multiple = stop_atr_multiple
        self.target_atr_multiple = target_atr_multiple

    def evaluate(self, symbol: str, bars: Sequence[MarketBar]) -> TradeSignal | None:
        """Evaluate chronological, closed candles and return the newest crossover."""
        if len(bars) < max(self.slow_period + 1, self.atr_period + 1):
            return None

        ordered = sorted(bars, key=lambda bar: bar.timestamp)
        for bar in ordered:
            values = (bar.open, bar.high, bar.low, bar.close)
            if not all(math.isfinite(value) and value > 0 for value in values):
                return None
            if bar.high < max(bar.open, bar.close, bar.low):
                return None
            if bar.low > min(bar.open, bar.close, bar.high):
                return None
            if bar.timestamp.tzinfo is None or bar.timestamp.utcoffset() is None:
                return None

        closes = [bar.close for bar in ordered]
        fast_values = self._ema(closes, self.fast_period)
        slow_values = self._ema(closes, self.slow_period)
        previous_fast, current_fast = fast_values[-2], fast_values[-1]
        previous_slow, current_slow = slow_values[-2], slow_values[-1]

        side: Side | None = None
        if previous_fast <= previous_slow and current_fast > current_slow:
            side = Side.BUY
        elif previous_fast >= previous_slow and current_fast < current_slow:
            side = Side.SELL
        if side is None:
            return None

        atr = self._atr(ordered, self.atr_period)
        if not math.isfinite(atr) or atr <= 0:
            return None

        close = ordered[-1].close
        stop_distance = atr * self.stop_atr_multiple
        target_distance = atr * self.target_atr_multiple
        if side is Side.BUY:
            stop_loss = close - stop_distance
            take_profit = close + target_distance
        else:
            stop_loss = close + stop_distance
            take_profit = close - target_distance
        if stop_loss <= 0 or take_profit <= 0:
            return None

        return TradeSignal(
            symbol=symbol,
            side=side,
            timestamp=ordered[-1].timestamp,
            rationale=(
                f"Closed-candle EMA({self.fast_period})/EMA({self.slow_period}) crossover; "
                f"ATR({self.atr_period})={atr:.5f}; signal only, not an order"
            ),
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    @staticmethod
    def _ema(values: Sequence[float], period: int) -> list[float]:
        alpha = 2.0 / (period + 1.0)
        result = [values[0]]
        for value in values[1:]:
            result.append(alpha * value + (1.0 - alpha) * result[-1])
        return result

    @staticmethod
    def _atr(bars: Sequence[MarketBar], period: int) -> float:
        ranges: list[float] = []
        for index in range(1, len(bars)):
            current = bars[index]
            previous_close = bars[index - 1].close
            ranges.append(
                max(
                    current.high - current.low,
                    abs(current.high - previous_close),
                    abs(current.low - previous_close),
                )
            )
        relevant = ranges[-period:]
        if len(relevant) < period:
            return 0.0
        return sum(relevant) / period
