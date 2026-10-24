from datetime import UTC, datetime

from trading_terminal.domain.models import OrderIntent, RiskDecision, RiskStatus, Side
from trading_terminal.execution.service import PaperExecutionService


def sample_intent() -> OrderIntent:
    return OrderIntent(symbol="XAUUSD", side=Side.BUY, volume=0.01, stop_loss=2300.0,
        created_at=datetime.now(UTC), idempotency_key="paper-test")


def test_execution_rejects_risk_rejected_intent() -> None:
    result = PaperExecutionService().submit(sample_intent(), RiskDecision(RiskStatus.REJECTED, ("kill_switch_enabled",)))
    assert result.accepted is False
    assert "risk_rejected" in result.message


def test_execution_is_paper_only_when_approved() -> None:
    result = PaperExecutionService().submit(sample_intent(), RiskDecision(RiskStatus.APPROVED, ("all_checks_passed",)))
    assert result.accepted is True
    assert result.order_id == "paper:paper-test"
    assert "not_routed_to_broker" in result.message
