from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_terminal.domain.models import Quote, Side
from trading_terminal.execution.paper_portfolio import PaperPortfolio, PaperPortfolioError
from trading_terminal.mt5.adapter import SymbolSpec

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def quote(bid: float = 2700.0, ask: float = 2700.2) -> Quote:
    return Quote("XAUUSD", bid, ask, NOW, 0.01)


def spec() -> SymbolSpec:
    return SymbolSpec(
        symbol="XAUUSD",
        digits=2,
        point=0.01,
        contract_size=100.0,
        tick_size=0.01,
        tick_value_profit_per_lot=1.0,
        tick_value_loss_per_lot=1.0,
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
        trade_stops_level=10,
    )


def open_buy(portfolio: PaperPortfolio, signal_key: str = "sig-1"):
    return portfolio.open_position(
        signal_key=signal_key,
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.01,
        stop_loss=2690.0,
        take_profit=2720.0,
        quote=quote(),
        spec=spec(),
        currency="USD",
        now=NOW,
    )


def test_paper_buy_is_persisted_and_marked_to_market(tmp_path: Path) -> None:
    portfolio = PaperPortfolio(tmp_path / "paper.sqlite3", starting_balance=10000)
    initial = portfolio.snapshot(quote(), spec(), currency="USD", now=NOW)
    assert initial.balance == 10000
    assert initial.open_position_count == 0

    opened = open_buy(portfolio)
    assert opened is not None
    assert opened.entry_price == pytest.approx(2700.22)

    marked = portfolio.snapshot(
        quote(bid=2701.0, ask=2701.2), spec(), currency="USD", now=NOW
    )
    assert marked.open_position_count == 1
    assert marked.open_positions[0].side is Side.BUY
    assert marked.unrealized_pnl > 0
    assert marked.equity == pytest.approx(marked.balance + marked.unrealized_pnl)


def test_take_profit_closes_paper_position_and_updates_balance(tmp_path: Path) -> None:
    portfolio = PaperPortfolio(tmp_path / "paper.sqlite3", starting_balance=10000)
    open_buy(portfolio)
    closed = portfolio.snapshot(
        quote(bid=2720.1, ask=2720.3), spec(), currency="USD",
        now=NOW.replace(minute=5),
    )
    assert closed.open_position_count == 0
    assert closed.balance > 10000
    history = portfolio.closed_positions()
    assert len(history) == 1
    assert history[0]["exit_reason"] == "TAKE_PROFIT"
    assert float(history[0]["exit_price"]) == pytest.approx(2720.0)


def test_stop_loss_closes_with_adverse_slippage(tmp_path: Path) -> None:
    portfolio = PaperPortfolio(tmp_path / "paper.sqlite3", starting_balance=10000)
    open_buy(portfolio)
    closed = portfolio.snapshot(
        quote(bid=2689.0, ask=2689.2), spec(), currency="USD",
        now=NOW.replace(minute=5),
    )
    assert closed.open_position_count == 0
    assert closed.balance < 10000
    history = portfolio.closed_positions()
    assert history[0]["exit_reason"] == "STOP_LOSS"
    assert float(history[0]["exit_price"]) == pytest.approx(2688.98)


def test_signal_key_is_deduplicated_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite3"
    first = PaperPortfolio(path, starting_balance=10000)
    assert open_buy(first) is not None
    restarted = PaperPortfolio(path, starting_balance=50000)
    assert open_buy(restarted) is None
    snapshot = restarted.snapshot(quote(), spec(), currency="USD", now=NOW)
    assert snapshot.equity < 10000
    assert snapshot.open_position_count == 1


def test_sell_take_profit_is_simulated(tmp_path: Path) -> None:
    portfolio = PaperPortfolio(tmp_path / "paper.sqlite3", starting_balance=10000)
    opened = portfolio.open_position(
        signal_key="sell-1", symbol="XAUUSD", side=Side.SELL, volume=0.01,
        stop_loss=2710.0, take_profit=2680.0, quote=quote(), spec=spec(),
        currency="USD", now=NOW,
    )
    assert opened is not None
    assert opened.entry_price == pytest.approx(2699.98)
    closed = portfolio.snapshot(
        quote(bid=2679.7, ask=2679.9), spec(), currency="USD",
        now=NOW.replace(minute=5),
    )
    assert closed.open_position_count == 0
    assert closed.balance > 10000
    assert portfolio.closed_positions()[0]["exit_reason"] == "TAKE_PROFIT"


def test_rejects_currency_change_and_invalid_quote(tmp_path: Path) -> None:
    portfolio = PaperPortfolio(tmp_path / "paper.sqlite3", starting_balance=10000)
    portfolio.snapshot(quote(), spec(), currency="USD", now=NOW)
    with pytest.raises(PaperPortfolioError, match="currency changed"):
        portfolio.snapshot(quote(), spec(), currency="EUR", now=NOW)
    with pytest.raises(PaperPortfolioError, match="quote is invalid"):
        portfolio.snapshot(quote(bid=-1), spec(), currency="USD", now=NOW)
