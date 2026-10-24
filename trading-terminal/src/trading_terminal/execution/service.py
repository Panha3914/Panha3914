"""Execution boundary. Paper mode only in this scaffold."""

from dataclasses import dataclass

from trading_terminal.domain.models import OrderIntent, RiskDecision


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    accepted: bool
    message: str
    order_id: str | None = None


class PaperExecutionService:
    """Safe placeholder that never contacts a broker."""

    def submit(self, intent: OrderIntent, decision: RiskDecision) -> ExecutionResult:
        if not decision.approved:
            return ExecutionResult(False, f"risk_rejected: {','.join(decision.reasons)}")
        return ExecutionResult(True, "paper_only_not_routed_to_broker",
                               order_id=f"paper:{intent.idempotency_key}")
