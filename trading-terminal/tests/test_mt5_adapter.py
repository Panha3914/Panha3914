from datetime import UTC
from types import SimpleNamespace

import pytest

from trading_terminal.mt5.adapter import MT5AdapterError, MT5ReadOnlyAdapter


class FakeMT5:
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    TIMEFRAME_M5 = 5

    def __init__(self) -> None:
        self.connected = True
        self.initialize_result = True
        self.shutdown_called = False
        self.symbol_visible = True
        self.rates_request: tuple[str, int, int, int] | None = None

    def terminal_info(self):
        return object() if self.connected else None

    def account_info(self):
        if not self.connected:
            return None
        return SimpleNamespace(
            login=12345, currency="USD", balance=1000.0, equity=995.0,
            margin=10.0, margin_free=985.0, leverage=100,
        )

    def initialize(self, **kwargs):
        self.connected = self.initialize_result
        return self.initialize_result

    def shutdown(self):
        self.shutdown_called = True
        self.connected = False

    def last_error(self):
        return (1, "fake MT5 error")

    def symbol_info(self, symbol):
        if symbol not in ("XAUUSD", "XAUUSD.a"):
            return None
        return SimpleNamespace(
            visible=self.symbol_visible, digits=2, point=0.01,
            trade_contract_size=100.0, trade_tick_size=0.01, trade_tick_value_profit=1.0,
            trade_tick_value_loss=1.0,
            volume_min=0.01, volume_max=50.0,
            volume_step=0.01, trade_stops_level=10,
        )

    def symbol_select(self, symbol, selected):
        self.symbol_visible = selected
        return selected

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(time=1792843200, bid=2700.0, ask=2700.2)

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        self.rates_request = (symbol, timeframe, start_pos, count)
        return [
            {"time": 1792840000, "open": 2698.0, "high": 2701.0,
             "low": 2697.0, "close": 2700.0, "tick_volume": 120},
            {"time": 1792841000, "open": 2700.0, "high": 2702.0,
             "low": 2699.0, "close": 2701.0, "tick_volume": 135},
        ]

    def positions_get(self):
        return (
            SimpleNamespace(ticket=1, symbol="XAUUSD", type=0, volume=0.01,
                price_open=2690.0, sl=2680.0, tp=2720.0, profit=1.0, time=1792843000),
        )


def test_quote_uses_adapter_values_and_utc_timestamp() -> None:
    quote = MT5ReadOnlyAdapter(mt5_module=FakeMT5()).get_quote("XAUUSD")
    assert quote.symbol == "XAUUSD"
    assert quote.bid == 2700.0
    assert quote.ask == 2700.2
    assert quote.timestamp.tzinfo == UTC


def test_unknown_symbol_fails_closed() -> None:
    adapter = MT5ReadOnlyAdapter(mt5_module=FakeMT5())
    with pytest.raises(MT5AdapterError, match="Unknown MT5 symbol"):
        adapter.get_quote("GOLD_UNKNOWN")


def test_disconnected_terminal_blocks_market_data() -> None:
    fake = FakeMT5()
    fake.connected = False
    adapter = MT5ReadOnlyAdapter(mt5_module=fake)
    with pytest.raises(MT5AdapterError, match="disconnected"):
        adapter.get_quote("XAUUSD")


def test_account_snapshot_is_read_only() -> None:
    account = MT5ReadOnlyAdapter(mt5_module=FakeMT5()).get_account_snapshot()
    assert account.currency == "USD"
    assert account.balance == 1000.0
    assert account.equity == 995.0


def test_symbol_spec_validates_contract_bounds() -> None:
    spec = MT5ReadOnlyAdapter(mt5_module=FakeMT5()).get_symbol_spec("XAUUSD")
    assert spec.volume_min == 0.01
    assert spec.volume_step == 0.01
    assert spec.trade_stops_level == 10
    assert spec.tick_size == 0.01
    assert spec.tick_value_profit_per_lot == 1.0
    assert spec.tick_value_loss_per_lot == 1.0


def test_positions_are_returned_as_immutable_snapshots() -> None:
    positions = MT5ReadOnlyAdapter(mt5_module=FakeMT5()).get_positions()
    assert len(positions) == 1
    assert positions[0].side == "BUY"
    assert positions[0].symbol == "XAUUSD"


def test_connect_shuts_down_session_if_account_is_unavailable() -> None:
    fake = FakeMT5()
    fake.account_info = lambda: None
    adapter = MT5ReadOnlyAdapter(mt5_module=fake)
    with pytest.raises(MT5AdapterError, match="account is not available"):
        adapter.connect()
    assert fake.shutdown_called

def test_closed_bars_exclude_the_forming_candle() -> None:
    fake = FakeMT5()
    bars = MT5ReadOnlyAdapter(mt5_module=fake).get_closed_bars("XAUUSD", timeframe="M5", count=50)
    assert len(bars) == 2
    assert bars[0].timestamp < bars[1].timestamp
    assert bars[1].close == 2701.0
    assert fake.rates_request == ("XAUUSD", FakeMT5.TIMEFRAME_M5, 1, 50)


def test_closed_bars_reject_unsupported_timeframe() -> None:
    adapter = MT5ReadOnlyAdapter(mt5_module=FakeMT5())
    with pytest.raises(ValueError, match="unsupported timeframe"):
        adapter.get_closed_bars("XAUUSD", timeframe="M7", count=20)



def test_terminal_path_strips_wrapping_quotes() -> None:
    adapter = MT5ReadOnlyAdapter(
        terminal_path='"C:\\\\Program Files\\\\MetaTrader 5\\\\terminal64.exe"',
        mt5_module=FakeMT5(),
    )
    assert adapter.terminal_path == "C:\\\\Program Files\\\\MetaTrader 5\\\\terminal64.exe"


def test_blank_terminal_path_enables_auto_discovery() -> None:
    adapter = MT5ReadOnlyAdapter(terminal_path='  ""  ', mt5_module=FakeMT5())
    assert adapter.terminal_path is None


def test_missing_terminal_path_gets_actionable_error(tmp_path) -> None:
    fake = FakeMT5()
    fake.connected = False
    adapter = MT5ReadOnlyAdapter(terminal_path=str(tmp_path / "missing-terminal64.exe"), mt5_module=fake)
    with pytest.raises(MT5AdapterError, match="Set MT5_PATH blank"):
        adapter.connect()
