"""Core domain models, independent of MT5 and the UI."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class RiskStatus(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    bid: float
    ask: float
    timestamp: datetime
    point: float

    @property
    def spread_points(self) -> float:
        if self.point <= 0:
            raise ValueError("point must be positive")
        return (self.ask - self.bid) / self.point


@dataclass(frozen=True, slots=True)
class MarketBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int


@dataclass(frozen=True, slots=True)
class TradeSignal:
    symbol: str
    side: Side
    timestamp: datetime
    rationale: str
    stop_loss: float | None = None
    take_profit: float | None = None


@dataclass(frozen=True, slots=True)
class OrderIntent:
    symbol: str
    side: Side
    volume: float
    stop_loss: float
    created_at: datetime
    idempotency_key: str
    take_profit: float | None = None


@dataclass(frozen=True, slots=True)
class RiskDecision:
    status: RiskStatus
    reasons: tuple[str, ...]

    @property
    def approved(self) -> bool:
        return self.status is RiskStatus.APPROVED
