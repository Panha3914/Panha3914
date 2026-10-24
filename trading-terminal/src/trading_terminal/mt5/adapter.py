"""Read-only MetaTrader 5 adapter.

This module intentionally exposes no order-submission methods. The MT5 Python
package is imported lazily so unit tests work without a terminal installed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from trading_terminal.domain.models import MarketBar, Quote


class MT5AdapterError(RuntimeError):
    """Raised when MT5 is unavailable or returns incomplete/invalid data."""


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    login: int
    currency: str
    balance: float
    equity: float
    margin: float
    margin_free: float
    leverage: int


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    ticket: int
    symbol: str
    side: str
    volume: float
    price_open: float
    stop_loss: float
    take_profit: float
    profit: float
    time: datetime


@dataclass(frozen=True, slots=True)
class SymbolSpec:
    symbol: str
    digits: int
    point: float
    contract_size: float
    tick_size: float
    tick_value_profit_per_lot: float
    tick_value_loss_per_lot: float
    volume_min: float
    volume_max: float
    volume_step: float
    trade_stops_level: int


class MT5ReadOnlyAdapter:
    """Thin, injectable adapter for read-only MT5 terminal calls.

    MT5 must already be installed and logged in through the local terminal.
    No trading functions are wrapped or exposed here.
    """

    def __init__(
        self,
        *,
        terminal_path: str | None = None,
        timeout_seconds: int = 10,
        mt5_module: Any | None = None,
    ) -> None:
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        self.terminal_path = terminal_path
        self.timeout_seconds = timeout_seconds
        self._mt5 = mt5_module
        self._owns_session = False

    def _module(self) -> Any:
        if self._mt5 is None:
            try:
                import MetaTrader5 as mt5  # type: ignore[import-not-found]
            except ImportError as exc:
                raise MT5AdapterError(
                    "MetaTrader5 package is not installed; install the optional 'mt5' extra"
                ) from exc
            self._mt5 = mt5
        return self._mt5

    def connect(self) -> None:
        mt5 = self._module()
        if mt5.terminal_info() is not None and mt5.account_info() is not None:
            return
        kwargs: dict[str, object] = {"timeout": self.timeout_seconds * 1000}
        if self.terminal_path:
            kwargs["path"] = self.terminal_path
        if not mt5.initialize(**kwargs):
            raise MT5AdapterError(f"MT5 initialize failed: {mt5.last_error()}")
        self._owns_session = True
        if mt5.account_info() is None:
            error = mt5.last_error()
            mt5.shutdown()
            self._owns_session = False
            raise MT5AdapterError(f"MT5 account is not available after initialization: {error}")

    def disconnect(self) -> None:
        if self._owns_session and self._mt5 is not None:
            self._mt5.shutdown()
            self._owns_session = False

    def is_connected(self) -> bool:
        mt5 = self._module()
        return mt5.terminal_info() is not None and mt5.account_info() is not None

    def get_quote(self, symbol: str) -> Quote:
        """Return a validated Quote or raise; never return fabricated market data."""
        mt5 = self._module()
        self._require_connected(mt5)
        info = mt5.symbol_info(symbol)
        if info is None:
            raise MT5AdapterError(f"Unknown MT5 symbol: {symbol}")
        if not info.visible and not mt5.symbol_select(symbol, True):
            raise MT5AdapterError(f"Cannot select symbol {symbol}: {mt5.last_error()}")
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5AdapterError(f"No tick available for {symbol}: {mt5.last_error()}")
        if not tick.time or tick.bid <= 0 or tick.ask <= 0 or tick.ask < tick.bid:
            raise MT5AdapterError(f"Invalid tick received for {symbol}")
        if info.point <= 0:
            raise MT5AdapterError(f"Invalid point metadata for {symbol}")
        return Quote(
            symbol=symbol,
            bid=float(tick.bid),
            ask=float(tick.ask),
            timestamp=datetime.fromtimestamp(int(tick.time), tz=UTC),
            point=float(info.point),
        )

    def get_account_snapshot(self) -> AccountSnapshot:
        mt5 = self._module()
        self._require_connected(mt5)
        account = mt5.account_info()
        if account is None:
            raise MT5AdapterError(f"Account information unavailable: {mt5.last_error()}")
        required = ("login", "currency", "balance", "equity", "margin", "margin_free", "leverage")
        if any(not hasattr(account, name) for name in required):
            raise MT5AdapterError("MT5 account response is missing required fields")
        return AccountSnapshot(
            login=int(account.login),
            currency=str(account.currency),
            balance=float(account.balance),
            equity=float(account.equity),
            margin=float(account.margin),
            margin_free=float(account.margin_free),
            leverage=int(account.leverage),
        )

    def get_symbol_spec(self, symbol: str) -> SymbolSpec:
        mt5 = self._module()
        self._require_connected(mt5)
        info = mt5.symbol_info(symbol)
        if info is None:
            raise MT5AdapterError(f"Unknown MT5 symbol: {symbol}")
        required = (
            "digits", "point", "trade_contract_size", "trade_tick_size",
            "trade_tick_value_profit", "trade_tick_value_loss", "volume_min", "volume_max", "volume_step",
            "trade_stops_level",
        )
        if any(not hasattr(info, name) for name in required):
            raise MT5AdapterError(f"Symbol metadata is incomplete for {symbol}")
        spec = SymbolSpec(
            symbol=symbol,
            digits=int(info.digits),
            point=float(info.point),
            contract_size=float(info.trade_contract_size),
            tick_size=float(info.trade_tick_size),
            tick_value_profit_per_lot=float(info.trade_tick_value_profit),
            tick_value_loss_per_lot=float(info.trade_tick_value_loss),
            volume_min=float(info.volume_min),
            volume_max=float(info.volume_max),
            volume_step=float(info.volume_step),
            trade_stops_level=int(info.trade_stops_level),
        )
        if (
            spec.point <= 0
            or spec.contract_size <= 0
            or spec.tick_size <= 0
            or spec.tick_value_profit_per_lot <= 0
            or spec.tick_value_loss_per_lot <= 0
            or spec.volume_min <= 0
            or spec.volume_max < spec.volume_min
            or spec.volume_step <= 0
        ):
            raise MT5AdapterError(f"Symbol metadata has invalid bounds for {symbol}")
        return spec

    def get_closed_bars(
        self,
        symbol: str,
        *,
        timeframe: str = "M5",
        count: int = 100,
    ) -> tuple[MarketBar, ...]:
        """Read historical candles, starting at position 1 to exclude the forming bar."""
        if count < 2 or count > 5000:
            raise ValueError("count must be between 2 and 5000")
        timeframe_name = timeframe.upper()
        if timeframe_name not in {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}:
            raise ValueError("unsupported timeframe; choose M1, M5, M15, M30, H1, H4, or D1")

        mt5 = self._module()
        self._require_connected(mt5)
        info = mt5.symbol_info(symbol)
        if info is None:
            raise MT5AdapterError(f"Unknown MT5 symbol: {symbol}")
        if not info.visible and not mt5.symbol_select(symbol, True):
            raise MT5AdapterError(f"Cannot select symbol {symbol}: {mt5.last_error()}")

        timeframe_value = getattr(mt5, f"TIMEFRAME_{timeframe_name}", None)
        if timeframe_value is None:
            raise MT5AdapterError(f"MT5 terminal does not expose timeframe {timeframe_name}")
        rates = mt5.copy_rates_from_pos(symbol, timeframe_value, 1, count)
        if rates is None:
            raise MT5AdapterError(f"Cannot read closed candles for {symbol}: {mt5.last_error()}")

        bars: list[MarketBar] = []
        for row in rates:
            timestamp = int(self._rate_field(row, "time"))
            open_price = float(self._rate_field(row, "open"))
            high_price = float(self._rate_field(row, "high"))
            low_price = float(self._rate_field(row, "low"))
            close_price = float(self._rate_field(row, "close"))
            tick_volume = int(self._rate_field(row, "tick_volume"))
            prices = (open_price, high_price, low_price, close_price)
            if timestamp <= 0 or not all(math.isfinite(value) and value > 0 for value in prices):
                raise MT5AdapterError(f"Invalid candle data received for {symbol}")
            if high_price < max(open_price, close_price, low_price):
                raise MT5AdapterError(f"Invalid candle high received for {symbol}")
            if low_price > min(open_price, close_price, high_price) or tick_volume < 0:
                raise MT5AdapterError(f"Invalid candle low/volume received for {symbol}")
            bars.append(
                MarketBar(
                    timestamp=datetime.fromtimestamp(timestamp, tz=UTC),
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    tick_volume=tick_volume,
                )
            )
        return tuple(sorted(bars, key=lambda bar: bar.timestamp))

    @staticmethod
    def _rate_field(row: Any, name: str) -> Any:
        try:
            return row[name]
        except (IndexError, KeyError, TypeError):
            try:
                return getattr(row, name)
            except AttributeError as exc:
                raise MT5AdapterError(f"MT5 candle is missing field {name}") from exc

    def get_positions(self) -> tuple[PositionSnapshot, ...]:
        mt5 = self._module()
        self._require_connected(mt5)
        raw_positions = mt5.positions_get()
        if raw_positions is None:
            raise MT5AdapterError(f"Cannot read open positions: {mt5.last_error()}")
        result: list[PositionSnapshot] = []
        for position in raw_positions:
            side_code = int(position.type)
            if side_code == int(mt5.POSITION_TYPE_BUY):
                side = "BUY"
            elif side_code == int(mt5.POSITION_TYPE_SELL):
                side = "SELL"
            else:
                raise MT5AdapterError(f"Unknown position side code: {side_code}")
            result.append(
                PositionSnapshot(
                    ticket=int(position.ticket),
                    symbol=str(position.symbol),
                    side=side,
                    volume=float(position.volume),
                    price_open=float(position.price_open),
                    stop_loss=float(position.sl),
                    take_profit=float(position.tp),
                    profit=float(position.profit),
                    time=datetime.fromtimestamp(int(position.time), tz=UTC),
                )
            )
        return tuple(result)

    @staticmethod
    def _require_connected(mt5: Any) -> None:
        if mt5.terminal_info() is None or mt5.account_info() is None:
            raise MT5AdapterError("MT5 terminal/account is disconnected")
