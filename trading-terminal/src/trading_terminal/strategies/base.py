"""Strategy protocol: signals are suggestions, not orders."""

from collections.abc import Sequence
from typing import Protocol

from trading_terminal.domain.models import MarketBar, TradeSignal


class Strategy(Protocol):
    name: str

    def evaluate(self, symbol: str, bars: Sequence[MarketBar]) -> TradeSignal | None:
        """Evaluate closed candles and return a signal or None."""
        ...
