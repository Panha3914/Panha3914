"""Persistent paper portfolio with conservative mark-to-market and SL/TP simulation."""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from trading_terminal.domain.models import Quote, Side
from trading_terminal.mt5.adapter import SymbolSpec


class PaperPortfolioError(RuntimeError):
    """Raised when the paper portfolio state or quote metadata is invalid."""


@dataclass(frozen=True, slots=True)
class PaperPositionSnapshot:
    position_id: int
    signal_key: str
    symbol: str
    side: Side
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    opened_at: datetime
    unrealized_pnl: float


@dataclass(frozen=True, slots=True)
class PaperPortfolioSnapshot:
    currency: str
    balance: float
    equity: float
    unrealized_pnl: float
    open_positions: tuple[PaperPositionSnapshot, ...]

    @property
    def open_position_count(self) -> int:
        return len(self.open_positions)


class PaperPortfolio:
    """A local SQLite ledger; it cannot submit broker orders."""

    def __init__(
        self,
        path: str | Path = "logs/paper-portfolio.sqlite3",
        *,
        starting_balance: float = 10_000.0,
        slippage_points: float = 2.0,
        commission_per_lot_round_turn: float = 0.0,
    ) -> None:
        if not math.isfinite(starting_balance) or starting_balance <= 0:
            raise ValueError("starting_balance must be finite and positive")
        if not math.isfinite(slippage_points) or slippage_points < 0:
            raise ValueError("slippage_points must be finite and non-negative")
        if (
            not math.isfinite(commission_per_lot_round_turn)
            or commission_per_lot_round_turn < 0
        ):
            raise ValueError("commission must be finite and non-negative")
        self.path = Path(path)
        self.starting_balance = starting_balance
        self.slippage_points = slippage_points
        self.commission_per_lot_round_turn = commission_per_lot_round_turn
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS paper_account (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        currency TEXT NOT NULL,
                        balance REAL NOT NULL,
                        created_at_utc TEXT NOT NULL,
                        updated_at_utc TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS paper_positions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        signal_key TEXT NOT NULL UNIQUE,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        volume REAL NOT NULL,
                        entry_price REAL NOT NULL,
                        stop_loss REAL NOT NULL,
                        take_profit REAL NOT NULL,
                        opened_at_utc TEXT NOT NULL,
                        point REAL NOT NULL,
                        tick_size REAL NOT NULL,
                        tick_value_profit_per_lot REAL NOT NULL,
                        tick_value_loss_per_lot REAL NOT NULL,
                        status TEXT NOT NULL,
                        closed_at_utc TEXT,
                        exit_price REAL,
                        exit_reason TEXT,
                        gross_pnl REAL
                    )
                    """
                )
        except (OSError, sqlite3.Error) as exc:
            raise PaperPortfolioError(
                f"cannot initialize paper portfolio ({type(exc).__name__})"
            ) from None

    @staticmethod
    def _timestamp(value: datetime | None) -> datetime:
        result = value or datetime.now(UTC)
        if result.tzinfo is None or result.utcoffset() is None:
            raise PaperPortfolioError("paper timestamps must be timezone-aware")
        return result.astimezone(UTC)

    @staticmethod
    def _validate_quote_and_spec(quote: Quote, spec: SymbolSpec) -> None:
        if quote.symbol != spec.symbol:
            raise PaperPortfolioError("quote and symbol metadata do not match")
        if (
            not all(math.isfinite(number) for number in (quote.bid, quote.ask, quote.point))
            or quote.bid <= 0
            or quote.ask < quote.bid
            or quote.point <= 0
        ):
            raise PaperPortfolioError("quote is invalid")
        spec_numbers = (
            spec.tick_size,
            spec.tick_value_profit_per_lot,
            spec.tick_value_loss_per_lot,
            spec.volume_min,
            spec.volume_max,
            spec.volume_step,
        )
        if not all(math.isfinite(number) and number > 0 for number in spec_numbers):
            raise PaperPortfolioError("symbol metadata has invalid sizing values")

    def _ensure_account(
        self,
        connection: sqlite3.Connection,
        currency: str,
        timestamp: datetime,
    ) -> sqlite3.Row:
        account = connection.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        if account is None:
            connection.execute(
                """
                INSERT INTO paper_account (id, currency, balance, created_at_utc, updated_at_utc)
                VALUES (1, ?, ?, ?, ?)
                """,
                (
                    currency,
                    self.starting_balance,
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                ),
            )
            account = connection.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
        if account is None:
            raise PaperPortfolioError("paper account could not be initialized")
        if str(account["currency"]) != currency:
            raise PaperPortfolioError(
                "paper portfolio currency changed; use a separate state file for the new currency"
            )
        return account

    def snapshot(
        self,
        quote: Quote,
        spec: SymbolSpec,
        *,
        currency: str,
        now: datetime | None = None,
    ) -> PaperPortfolioSnapshot:
        """Update SL/TP exits and return current virtual balance, equity and open positions."""
        self._validate_quote_and_spec(quote, spec)
        timestamp = self._timestamp(now)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                account = self._ensure_account(connection, currency, timestamp)
                balance = float(account["balance"])
                rows = connection.execute(
                    "SELECT * FROM paper_positions WHERE status = 'OPEN' AND symbol = ?",
                    (quote.symbol,),
                ).fetchall()
                for row in rows:
                    exit_result = self._exit_price(row, quote)
                    if exit_result is None:
                        continue
                    reason, exit_price = exit_result
                    gross_pnl = self._calculate_pnl(row, exit_price)
                    close_commission = self.commission_per_lot_round_turn * float(row["volume"]) / 2.0
                    balance += gross_pnl - close_commission
                    connection.execute(
                        """
                        UPDATE paper_positions
                        SET status = 'CLOSED', closed_at_utc = ?, exit_price = ?,
                            exit_reason = ?, gross_pnl = ?
                        WHERE id = ? AND status = 'OPEN'
                        """,
                        (timestamp.isoformat(), exit_price, reason, gross_pnl, int(row["id"])),
                    )
                connection.execute(
                    "UPDATE paper_account SET balance = ?, updated_at_utc = ? WHERE id = 1",
                    (balance, timestamp.isoformat()),
                )
                opened = connection.execute(
                    "SELECT * FROM paper_positions WHERE status = 'OPEN'"
                ).fetchall()
                open_snapshots: list[PaperPositionSnapshot] = []
                unrealized_pnl = 0.0
                for row in opened:
                    if str(row["symbol"]) != quote.symbol:
                        # This application currently monitors one symbol; don't invent prices for others.
                        raise PaperPortfolioError(
                            f"cannot value open paper position for unmonitored symbol {row['symbol']}"
                        )
                    side = Side(str(row["side"]))
                    closing_price = (
                        quote.bid - self.slippage_points * quote.point
                        if side is Side.BUY
                        else quote.ask + self.slippage_points * quote.point
                    )
                    position_pnl = self._calculate_pnl(row, closing_price)
                    closing_commission = (
                        self.commission_per_lot_round_turn * float(row["volume"]) / 2.0
                    )
                    net_unrealized = position_pnl - closing_commission
                    unrealized_pnl += net_unrealized
                    open_snapshots.append(
                        PaperPositionSnapshot(
                            position_id=int(row["id"]),
                            signal_key=str(row["signal_key"]),
                            symbol=str(row["symbol"]),
                            side=side,
                            volume=float(row["volume"]),
                            entry_price=float(row["entry_price"]),
                            stop_loss=float(row["stop_loss"]),
                            take_profit=float(row["take_profit"]),
                            opened_at=datetime.fromisoformat(str(row["opened_at_utc"])),
                            unrealized_pnl=net_unrealized,
                        )
                    )
                equity = balance + unrealized_pnl
                if not math.isfinite(equity) or equity <= 0:
                    # State is still recorded, but the caller must fail closed on risk sizing.
                    equity = max(0.0, equity)
                return PaperPortfolioSnapshot(
                    currency=currency,
                    balance=balance,
                    equity=equity,
                    unrealized_pnl=unrealized_pnl,
                    open_positions=tuple(open_snapshots),
                )
        except PaperPortfolioError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise PaperPortfolioError(
                f"cannot read/update paper portfolio ({type(exc).__name__})"
            ) from None

    def open_position(
        self,
        *,
        signal_key: str,
        symbol: str,
        side: Side,
        volume: float,
        stop_loss: float,
        take_profit: float,
        quote: Quote,
        spec: SymbolSpec,
        currency: str,
        now: datetime | None = None,
    ) -> PaperPositionSnapshot | None:
        """Persist a simulated fill with adverse entry slippage; None means duplicate signal."""
        self._validate_quote_and_spec(quote, spec)
        timestamp = self._timestamp(now)
        numbers = (volume, stop_loss, take_profit)
        if not all(math.isfinite(value) for value in numbers) or volume <= 0:
            raise PaperPortfolioError("paper order volume and stops must be finite and valid")
        if symbol != quote.symbol or symbol != spec.symbol:
            raise PaperPortfolioError("paper order, quote and symbol metadata do not match")
        if side is Side.BUY and not (stop_loss < quote.bid and take_profit > quote.ask):
            raise PaperPortfolioError("BUY stop-loss/target must bracket the current market")
        if side is Side.SELL and not (stop_loss > quote.ask and take_profit < quote.bid):
            raise PaperPortfolioError("SELL stop-loss/target must bracket the current market")
        entry_base = quote.ask if side is Side.BUY else quote.bid
        entry_price = (
            entry_base + self.slippage_points * quote.point
            if side is Side.BUY
            else entry_base - self.slippage_points * quote.point
        )
        if entry_price <= 0:
            raise PaperPortfolioError("simulated entry price is not positive")
        open_commission = self.commission_per_lot_round_turn * volume / 2.0

        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                account = self._ensure_account(connection, currency, timestamp)
                existing = connection.execute(
                    "SELECT id FROM paper_positions WHERE signal_key = ?",
                    (signal_key,),
                ).fetchone()
                if existing is not None:
                    return None
                balance = float(account["balance"]) - open_commission
                cursor = connection.execute(
                    """
                    INSERT INTO paper_positions (
                        signal_key, symbol, side, volume, entry_price, stop_loss, take_profit,
                        opened_at_utc, point, tick_size, tick_value_profit_per_lot,
                        tick_value_loss_per_lot, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
                    """,
                    (
                        signal_key, symbol, side.value, volume, entry_price, stop_loss,
                        take_profit, timestamp.isoformat(), spec.point, spec.tick_size,
                        spec.tick_value_profit_per_lot, spec.tick_value_loss_per_lot,
                    ),
                )
                connection.execute(
                    "UPDATE paper_account SET balance = ?, updated_at_utc = ? WHERE id = 1",
                    (balance, timestamp.isoformat()),
                )
                position_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None
        except PaperPortfolioError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise PaperPortfolioError(
                f"cannot persist paper position ({type(exc).__name__})"
            ) from None

        return PaperPositionSnapshot(
            position_id=position_id,
            signal_key=signal_key,
            symbol=symbol,
            side=side,
            volume=volume,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            opened_at=timestamp,
            unrealized_pnl=0.0,
        )

    def closed_positions(self, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT id, signal_key, symbol, side, volume, entry_price, exit_price,
                           stop_loss, take_profit, opened_at_utc, closed_at_utc,
                           exit_reason, gross_pnl
                    FROM paper_positions WHERE status = 'CLOSED'
                    ORDER BY id DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return tuple(dict(row) for row in rows)
        except (OSError, sqlite3.Error) as exc:
            raise PaperPortfolioError(
                f"cannot read closed paper positions ({type(exc).__name__})"
            ) from None

    def _exit_price(self, row: sqlite3.Row, quote: Quote) -> tuple[str, float] | None:
        side = Side(str(row["side"]))
        stop = float(row["stop_loss"])
        target = float(row["take_profit"])
        slip = self.slippage_points * quote.point
        if side is Side.BUY:
            if quote.bid <= stop:
                return "STOP_LOSS", min(stop, quote.bid) - slip
            if quote.bid >= target:
                return "TAKE_PROFIT", target
        else:
            if quote.ask >= stop:
                return "STOP_LOSS", max(stop, quote.ask) + slip
            if quote.ask <= target:
                return "TAKE_PROFIT", target
        return None

    @staticmethod
    def _calculate_pnl(row: sqlite3.Row, exit_price: float) -> float:
        entry = float(row["entry_price"])
        volume = float(row["volume"])
        tick_size = float(row["tick_size"])
        side = Side(str(row["side"]))
        if not all(math.isfinite(value) for value in (entry, exit_price, volume, tick_size)):
            raise PaperPortfolioError("cannot value a paper position with non-finite values")
        if volume <= 0 or tick_size <= 0:
            raise PaperPortfolioError("paper position metadata is invalid")
        price_change = exit_price - entry if side is Side.BUY else entry - exit_price
        tick_value = (
            float(row["tick_value_profit_per_lot"])
            if price_change >= 0
            else float(row["tick_value_loss_per_lot"])
        )
        if tick_value <= 0 or not math.isfinite(tick_value):
            raise PaperPortfolioError("paper position tick value is invalid")
        result = price_change / tick_size * tick_value * volume
        if not math.isfinite(result):
            raise PaperPortfolioError("paper P/L calculation is not finite")
        return result
