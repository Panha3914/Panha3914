"""Persist observed equity baselines used by the pre-trade risk manager.

This tracker observes the broker account equity while the terminal is connected.
It cannot reconstruct equity changes before the first observation of a UTC day.
Therefore its daily-loss metric is explicitly based on the first observed equity
of each UTC day, not broker-reported historical daily P/L.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class RiskStateError(RuntimeError):
    """Raised when risk state cannot be validated or persisted."""


@dataclass(frozen=True, slots=True)
class RiskMetrics:
    daily_loss_percent: float
    drawdown_percent: float
    day_start_equity: float
    peak_observed_equity: float
    current_equity: float
    observed_day_utc: str


class RiskStateTracker:
    """SQLite-backed observed-equity baselines scoped to a hashed account identity."""

    def __init__(self, path: str | Path = "logs/risk-state.sqlite3") -> None:
        self.path = Path(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS observed_equity_state (
                    account_key TEXT PRIMARY KEY,
                    observed_day_utc TEXT NOT NULL,
                    day_start_equity REAL NOT NULL,
                    peak_observed_equity REAL NOT NULL,
                    updated_at_utc TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _account_key(identity: str) -> str:
        cleaned = identity.strip()
        if not cleaned:
            raise RiskStateError("account identity must not be blank")
        return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()

    def observe(
        self,
        *,
        account_identity: str,
        equity: float,
        now: datetime | None = None,
    ) -> RiskMetrics:
        timestamp = now or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise RiskStateError("risk tracker timestamp must be timezone-aware")
        if not math.isfinite(equity) or equity <= 0:
            raise RiskStateError("account equity must be finite and positive")

        timestamp = timestamp.astimezone(UTC)
        observed_day = timestamp.date().isoformat()
        account_key = self._account_key(account_identity)

        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                previous = connection.execute(
                    "SELECT * FROM observed_equity_state WHERE account_key = ?",
                    (account_key,),
                ).fetchone()
                if previous is None:
                    day_start_equity = equity
                    peak_equity = equity
                else:
                    day_start_equity = (
                        equity
                        if previous["observed_day_utc"] != observed_day
                        else float(previous["day_start_equity"])
                    )
                    peak_equity = max(float(previous["peak_observed_equity"]), equity)

                connection.execute(
                    """
                    INSERT INTO observed_equity_state (
                        account_key, observed_day_utc, day_start_equity,
                        peak_observed_equity, updated_at_utc
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(account_key) DO UPDATE SET
                        observed_day_utc = excluded.observed_day_utc,
                        day_start_equity = excluded.day_start_equity,
                        peak_observed_equity = excluded.peak_observed_equity,
                        updated_at_utc = excluded.updated_at_utc
                    """,
                    (
                        account_key,
                        observed_day,
                        day_start_equity,
                        peak_equity,
                        timestamp.isoformat(),
                    ),
                )
        except sqlite3.Error as exc:
            raise RiskStateError(f"cannot persist observed equity state ({type(exc).__name__})") from None

        daily_loss_percent = max(0.0, (day_start_equity - equity) / day_start_equity * 100)
        drawdown_percent = max(0.0, (peak_equity - equity) / peak_equity * 100)
        return RiskMetrics(
            daily_loss_percent=daily_loss_percent,
            drawdown_percent=drawdown_percent,
            day_start_equity=day_start_equity,
            peak_observed_equity=peak_equity,
            current_equity=equity,
            observed_day_utc=observed_day,
        )
