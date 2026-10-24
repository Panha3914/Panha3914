"""Signal-to-paper-order proposal orchestration.

There is deliberately no live or demo broker execution path. This coordinator
sizes a paper proposal, runs centralized risk checks, audits the decision and
then hands an approved proposal to the paper-only execution boundary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock

from trading_terminal.audit.jsonl import JsonlAuditLogger
from trading_terminal.config import Settings
from trading_terminal.domain.models import (
    OrderIntent,
    Quote,
    RiskDecision,
    Side,
    TradeSignal,
)
from trading_terminal.execution.paper_portfolio import PaperPortfolio, PaperPortfolioError
from trading_terminal.execution.service import ExecutionResult, PaperExecutionService
from trading_terminal.mt5.adapter import SymbolSpec
from trading_terminal.risk.manager import RiskManager
from trading_terminal.risk.sizing import RiskSizingError, calculate_position_volume


class PaperOrderStatus(StrEnum):
    PROPOSED = "PROPOSED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    DUPLICATE = "DUPLICATE"


@dataclass(frozen=True, slots=True)
class PaperOrderOutcome:
    status: PaperOrderStatus
    signal_key: str
    message: str
    reasons: tuple[str, ...] = ()
    volume: float | None = None
    entry_price: float | None = None
    order_id: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status in (PaperOrderStatus.PROPOSED, PaperOrderStatus.FILLED)


class PaperOrderEngine:
    """Evaluate each signal once per process and propose paper orders only."""

    def __init__(
        self,
        settings: Settings,
        *,
        audit: JsonlAuditLogger | None = None,
        paper_execution: PaperExecutionService | None = None,
        paper_portfolio: PaperPortfolio | None = None,
    ) -> None:
        self.settings = settings
        self._risk_manager = RiskManager(settings)
        self._paper_execution = paper_execution or PaperExecutionService()
        self._paper_portfolio = paper_portfolio
        self._audit = audit or JsonlAuditLogger(settings.audit_log_path)
        self._lock = Lock()
        self._processed: dict[str, PaperOrderOutcome] = {}

    @staticmethod
    def _signal_key(signal: TradeSignal) -> str:
        return f"{signal.symbol}:{signal.side.value}:{signal.timestamp.isoformat()}"

    def _record(self, event_type: str, fields: dict[str, object]) -> bool:
        try:
            self._audit.write(event_type, fields)
        except OSError:
            return False
        return True

    def process_signal(
        self,
        signal: TradeSignal,
        quote: Quote,
        symbol_spec: SymbolSpec,
        *,
        account_equity: float,
        open_positions: int,
        daily_loss_percent: float | None,
        drawdown_percent: float | None,
        account_state_known: bool,
        currency: str | None = None,
        now: datetime | None = None,
    ) -> PaperOrderOutcome:
        """Return a paper proposal or an explicit rejection; never sends to MT5."""
        key = self._signal_key(signal)
        with self._lock:
            previous = self._processed.get(key)
            if previous is not None:
                return PaperOrderOutcome(
                    status=PaperOrderStatus.DUPLICATE,
                    signal_key=key,
                    message="Signal was already evaluated; duplicate proposal suppressed.",
                    reasons=previous.reasons,
                    volume=previous.volume,
                    entry_price=previous.entry_price,
                    order_id=previous.order_id,
                )

        checked_at = now or datetime.now(UTC)

        def finish(outcome: PaperOrderOutcome, event_type: str) -> PaperOrderOutcome:
            audit_fields: dict[str, object] = {
                "signal_key": key,
                "symbol": signal.symbol,
                "side": signal.side.value,
                "signal_time": signal.timestamp,
                "status": outcome.status.value,
                "reasons": list(outcome.reasons),
                "volume": outcome.volume,
                "entry_price": outcome.entry_price,
                "order_id": outcome.order_id,
            }
            if not self._record(event_type, audit_fields):
                if outcome.status is PaperOrderStatus.FILLED:
                    outcome = PaperOrderOutcome(
                        status=PaperOrderStatus.FILLED,
                        signal_key=key,
                        message=(
                            "Paper fill is stored locally, but the final audit event failed; "
                            "no broker order was sent."
                        ),
                        reasons=(*outcome.reasons, "final_audit_write_failed"),
                        volume=outcome.volume,
                        entry_price=outcome.entry_price,
                        order_id=outcome.order_id,
                    )
                else:
                    outcome = PaperOrderOutcome(
                        status=PaperOrderStatus.REJECTED,
                        signal_key=key,
                        message="Audit log write failed; paper proposal was not accepted.",
                        reasons=("audit_write_failed",),
                        volume=outcome.volume,
                        entry_price=outcome.entry_price,
                    )
            with self._lock:
                self._processed[key] = outcome
            return outcome

        if self.settings.trading_mode != "paper":
            return finish(
                PaperOrderOutcome(
                    PaperOrderStatus.REJECTED,
                    key,
                    "This build supports paper mode only; broker order submission is unavailable.",
                    ("paper_mode_required",),
                ),
                "paper_order_rejected",
            )

        if (
            signal.stop_loss is None
            or signal.take_profit is None
            or signal.timestamp.tzinfo is None
            or signal.timestamp.utcoffset() is None
        ):
            return finish(
                PaperOrderOutcome(
                    PaperOrderStatus.REJECTED,
                    key,
                    "Signal is missing valid stop/target references or a timezone-aware candle time.",
                    ("invalid_signal",),
                ),
                "paper_order_rejected",
            )

        if signal.symbol != quote.symbol or signal.symbol != symbol_spec.symbol:
            return finish(
                PaperOrderOutcome(
                    PaperOrderStatus.REJECTED,
                    key,
                    "Signal, quote and symbol metadata do not match.",
                    ("symbol_mismatch",),
                ),
                "paper_order_rejected",
            )

        if not math.isfinite(account_equity) or account_equity <= 0:
            return finish(
                PaperOrderOutcome(
                    PaperOrderStatus.REJECTED,
                    key,
                    "Account equity is not valid for position sizing.",
                    ("invalid_account_equity",),
                ),
                "paper_order_rejected",
            )

        entry_price = (
            quote.ask + self.settings.paper_slippage_points * quote.point
            if signal.side is Side.BUY
            else quote.bid - self.settings.paper_slippage_points * quote.point
        )
        if not math.isfinite(entry_price) or entry_price <= 0:
            return finish(
                PaperOrderOutcome(
                    PaperOrderStatus.REJECTED,
                    key,
                    "Slippage-adjusted entry reference is invalid.",
                    ("invalid_entry_price",),
                ),
                "paper_order_rejected",
            )
        try:
            volume = calculate_position_volume(
                settings=self.settings,
                side=signal.side,
                equity=account_equity,
                entry_price=entry_price,
                stop_loss=signal.stop_loss,
                tick_size=symbol_spec.tick_size,
                tick_value_loss_per_lot=symbol_spec.tick_value_loss_per_lot,
                volume_min=symbol_spec.volume_min,
                volume_max=symbol_spec.volume_max,
                volume_step=symbol_spec.volume_step,
            )
        except RiskSizingError as exc:
            return finish(
                PaperOrderOutcome(
                    PaperOrderStatus.REJECTED,
                    key,
                    f"Position sizing rejected: {exc}",
                    ("position_sizing_rejected",),
                    entry_price=entry_price,
                ),
                "paper_order_rejected",
            )

        intent = OrderIntent(
            symbol=signal.symbol,
            side=signal.side,
            volume=volume,
            stop_loss=signal.stop_loss,
            created_at=checked_at,
            idempotency_key=key,
            take_profit=signal.take_profit,
        )
        risk_decision: RiskDecision = self._risk_manager.validate(
            intent,
            quote,
            open_positions=open_positions,
            daily_loss_percent=daily_loss_percent,
            drawdown_percent=drawdown_percent,
            account_state_known=account_state_known,
            now=checked_at,
        )
        if not risk_decision.approved:
            outcome = PaperOrderOutcome(
                PaperOrderStatus.REJECTED,
                key,
                "Risk controls rejected the paper order proposal.",
                risk_decision.reasons,
                volume=volume,
                entry_price=entry_price,
            )
            return finish(outcome, "paper_order_rejected")

        # Audit first. If the audit sink is unavailable, do not even create a paper proposal.
        if not self._record(
            "paper_order_risk_approved",
            {
                "signal_key": key,
                "symbol": signal.symbol,
                "side": signal.side.value,
                "volume": volume,
                "entry_price_reference": entry_price,
                "stop_loss_reference": signal.stop_loss,
                "take_profit_reference": signal.take_profit,
                "risk_decision": list(risk_decision.reasons),
            },
        ):
            return finish(
                PaperOrderOutcome(
                    PaperOrderStatus.REJECTED,
                    key,
                    "Audit log write failed; paper proposal was not accepted.",
                    ("audit_write_failed",),
                    volume=volume,
                    entry_price=entry_price,
                ),
                "paper_order_rejected",
            )

        result: ExecutionResult = self._paper_execution.submit(intent, risk_decision)
        if not result.accepted:
            return finish(
                PaperOrderOutcome(
                    PaperOrderStatus.REJECTED,
                    key,
                    result.message,
                    ("paper_execution_rejected",),
                    volume=volume,
                    entry_price=entry_price,
                ),
                "paper_order_rejected",
            )

        if self._paper_portfolio is not None:
            if not currency:
                return finish(
                    PaperOrderOutcome(
                        PaperOrderStatus.REJECTED,
                        key,
                        "Paper portfolio currency is unknown; simulated fill was blocked.",
                        ("paper_currency_unknown",),
                        volume=volume,
                        entry_price=entry_price,
                    ),
                    "paper_order_rejected",
                )
            try:
                position = self._paper_portfolio.open_position(
                    signal_key=key,
                    symbol=signal.symbol,
                    side=signal.side,
                    volume=volume,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    quote=quote,
                    spec=symbol_spec,
                    currency=currency,
                    now=checked_at,
                )
            except PaperPortfolioError as exc:
                return finish(
                    PaperOrderOutcome(
                        PaperOrderStatus.REJECTED,
                        key,
                        f"Paper portfolio rejected the simulated fill: {exc}",
                        ("paper_portfolio_rejected",),
                        volume=volume,
                        entry_price=entry_price,
                    ),
                    "paper_order_rejected",
                )
            if position is None:
                return finish(
                    PaperOrderOutcome(
                        PaperOrderStatus.DUPLICATE,
                        key,
                        "Persistent paper ledger already contains this signal; fill suppressed.",
                        ("duplicate_signal_key",),
                        volume=volume,
                        entry_price=entry_price,
                        order_id=f"paper-position:{key}",
                    ),
                    "paper_order_duplicate",
                )
            return finish(
                PaperOrderOutcome(
                    PaperOrderStatus.FILLED,
                    key,
                    "Paper fill recorded locally; no broker order was sent.",
                    ("risk_checks_passed", "simulated_fill_only"),
                    volume=volume,
                    entry_price=position.entry_price,
                    order_id=f"paper-position:{position.position_id}",
                ),
                "paper_position_opened",
            )

        return finish(
            PaperOrderOutcome(
                PaperOrderStatus.PROPOSED,
                key,
                "Paper proposal accepted; it is not filled and no broker order was sent.",
                ("risk_checks_passed", "paper_only_not_routed_to_broker"),
                volume=volume,
                entry_price=entry_price,
                order_id=result.order_id,
            ),
            "paper_order_proposed",
        )
