"""Conservative stop-distance-based volume sizing.

This calculates a proposed volume only. It does not place orders and deliberately
rejects cases where broker minimum volume would exceed the configured risk budget.
"""

import math
from decimal import ROUND_DOWN, Decimal

from trading_terminal.config import Settings
from trading_terminal.domain.models import Side


class RiskSizingError(ValueError):
    """Raised when inputs cannot support a conservative position-size estimate."""


def calculate_position_volume(
    *,
    settings: Settings,
    side: Side,
    equity: float,
    entry_price: float,
    stop_loss: float,
    tick_size: float,
    tick_value_loss_per_lot: float,
    volume_min: float,
    volume_max: float,
    volume_step: float,
) -> float:
    """Return a step-aligned lot size within configured risk and volume limits.

    The tick-value argument must be the broker's loss-side tick value for one lot
    in the account currency. If that metadata is unavailable or uncertain, the
    caller must not guess; this function will reject non-positive values.
    """
    values = (
        equity, entry_price, stop_loss, tick_size, tick_value_loss_per_lot,
        volume_min, volume_max, volume_step,
    )
    if not all(math.isfinite(value) for value in values):
        raise RiskSizingError("all sizing inputs must be finite numbers")
    if equity <= 0 or entry_price <= 0 or stop_loss <= 0:
        raise RiskSizingError("equity and prices must be positive")
    if tick_size <= 0 or tick_value_loss_per_lot <= 0:
        raise RiskSizingError("valid positive tick size and loss tick value are required")
    if volume_min <= 0 or volume_max < volume_min or volume_step <= 0:
        raise RiskSizingError("invalid broker volume constraints")
    if settings.max_position_volume < volume_min:
        raise RiskSizingError("configured maximum volume is below broker minimum")

    if side is Side.BUY and stop_loss >= entry_price:
        raise RiskSizingError("BUY stop-loss must be below entry price")
    if side is Side.SELL and stop_loss <= entry_price:
        raise RiskSizingError("SELL stop-loss must be above entry price")

    risk_budget = (
        Decimal(str(equity))
        * Decimal(str(settings.max_risk_per_trade_percent))
        / Decimal(100)
    )
    price_distance = abs(Decimal(str(entry_price)) - Decimal(str(stop_loss)))
    loss_per_lot = (
        price_distance
        / Decimal(str(tick_size))
        * Decimal(str(tick_value_loss_per_lot))
    )
    if loss_per_lot <= 0:
        raise RiskSizingError("calculated loss per lot must be positive")

    raw_volume = risk_budget / loss_per_lot
    cap = min(
        Decimal(str(volume_max)),
        Decimal(str(settings.max_position_volume)),
    )
    capped_volume = min(raw_volume, cap)
    step = Decimal(str(volume_step))
    stepped_volume = (capped_volume / step).to_integral_value(rounding=ROUND_DOWN) * step

    if stepped_volume < Decimal(str(volume_min)):
        raise RiskSizingError(
            "minimum broker volume would exceed the configured risk budget"
        )
    if stepped_volume <= 0:
        raise RiskSizingError("calculated position volume is not tradable")
    return float(stepped_volume)
