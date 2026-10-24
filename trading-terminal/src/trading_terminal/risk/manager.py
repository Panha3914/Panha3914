"""Conservative, fail-closed pre-trade validation."""

import math
from datetime import UTC, datetime

from trading_terminal.config import Settings
from trading_terminal.domain.models import (
    OrderIntent,
    Quote,
    RiskDecision,
    RiskStatus,
    Side,
)


class RiskManager:
    """Validate a proposed intent; never submits orders."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def validate(
        self,
        intent: OrderIntent,
        quote: Quote | None,
        *,
        open_positions: int,
        daily_loss_percent: float | None,
        drawdown_percent: float | None,
        account_state_known: bool,
        now: datetime | None = None,
    ) -> RiskDecision:
        reasons: list[str] = []
        current_time = now or datetime.now(UTC)

        if self.settings.kill_switch:
            reasons.append("kill_switch_enabled")
        if not account_state_known:
            reasons.append("account_state_unknown")
        if intent.side not in (Side.BUY, Side.SELL):
            reasons.append("invalid_order_side")
        if intent.created_at.tzinfo is None or intent.created_at.utcoffset() is None:
            reasons.append("intent_timestamp_must_be_timezone_aware")
        if current_time.tzinfo is None or current_time.utcoffset() is None:
            reasons.append("current_timestamp_must_be_timezone_aware")

        if not math.isfinite(intent.volume) or (
            intent.volume <= 0 or intent.volume > self.settings.max_position_volume
        ):
            reasons.append("volume_out_of_bounds")
        if not math.isfinite(intent.stop_loss) or intent.stop_loss <= 0:
            reasons.append("stop_loss_required")

        if open_positions < 0:
            reasons.append("invalid_open_position_count")
        elif open_positions >= self.settings.max_open_positions:
            reasons.append("open_position_limit_reached")

        if daily_loss_percent is None:
            reasons.append("daily_loss_state_unknown")
        elif not math.isfinite(daily_loss_percent) or daily_loss_percent < 0:
            reasons.append("invalid_daily_loss_value")
        elif daily_loss_percent >= self.settings.max_daily_loss_percent:
            reasons.append("daily_loss_limit_reached")
        if drawdown_percent is None:
            reasons.append("drawdown_state_unknown")
        elif not math.isfinite(drawdown_percent) or drawdown_percent < 0:
            reasons.append("invalid_drawdown_value")
        elif drawdown_percent >= self.settings.max_drawdown_percent:
            reasons.append("drawdown_limit_reached")

        if quote is None:
            reasons.append("quote_unavailable")
        else:
            quote_values_finite = all(
                math.isfinite(value) for value in (quote.bid, quote.ask, quote.point)
            )
            quote_prices_valid = (
                quote_values_finite
                and quote.bid > 0
                and quote.ask > 0
                and quote.ask >= quote.bid
            )
            if quote.symbol != intent.symbol:
                reasons.append("symbol_mismatch")
            if not quote_prices_valid:
                reasons.append("invalid_quote")
            if not math.isfinite(quote.point) or quote.point <= 0:
                reasons.append("invalid_symbol_point")
            elif quote_prices_valid and quote.spread_points > self.settings.max_spread_points:
                reasons.append("spread_limit_exceeded")

            if quote.timestamp.tzinfo is None or quote.timestamp.utcoffset() is None:
                reasons.append("quote_timestamp_must_be_timezone_aware")
            elif current_time.tzinfo is not None and current_time.utcoffset() is not None:
                age_seconds = (current_time - quote.timestamp).total_seconds()
                if age_seconds < 0:
                    reasons.append("quote_timestamp_in_future")
                elif age_seconds > self.settings.quote_max_age_seconds:
                    reasons.append("stale_quote")

            # Stops must sit on the protective side of the current market.
            if quote_prices_valid and math.isfinite(intent.stop_loss) and intent.stop_loss > 0:
                if intent.side == Side.BUY and intent.stop_loss >= quote.bid:
                    reasons.append("buy_stop_loss_must_be_below_bid")
                elif intent.side == Side.SELL and intent.stop_loss <= quote.ask:
                    reasons.append("sell_stop_loss_must_be_above_ask")
            if intent.take_profit is not None:
                if not math.isfinite(intent.take_profit) or intent.take_profit <= 0:
                    reasons.append("invalid_take_profit")
                elif quote_prices_valid and intent.side == Side.BUY and intent.take_profit <= quote.ask:
                    reasons.append("buy_take_profit_must_be_above_ask")
                elif quote_prices_valid and intent.side == Side.SELL and intent.take_profit >= quote.bid:
                    reasons.append("sell_take_profit_must_be_below_bid")

        return RiskDecision(
            status=RiskStatus.REJECTED if reasons else RiskStatus.APPROVED,
            reasons=tuple(reasons) if reasons else ("all_checks_passed",),
        )
