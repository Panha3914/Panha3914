import pytest

from trading_terminal.config import Settings
from trading_terminal.domain.models import Side
from trading_terminal.risk.sizing import RiskSizingError, calculate_position_volume


def size(**overrides: object) -> float:
    values: dict[str, object] = {
        "settings": Settings(kill_switch=False, max_risk_per_trade_percent=0.25,
                             max_position_volume=0.5),
        "side": Side.BUY,
        "equity": 10000.0,
        "entry_price": 2700.0,
        "stop_loss": 2690.0,
        "tick_size": 1.0,
        "tick_value_loss_per_lot": 100.0,
        "volume_min": 0.01,
        "volume_max": 1.0,
        "volume_step": 0.01,
    }
    values.update(overrides)
    return calculate_position_volume(**values)  # type: ignore[arg-type]


def test_volume_rounds_down_to_broker_step() -> None:
    # Risk budget $25; loss is $1,000 per lot; exact size 0.025 rounds down to 0.02.
    assert size() == pytest.approx(0.02)


def test_volume_never_exceeds_configured_cap() -> None:
    settings = Settings(kill_switch=False, max_risk_per_trade_percent=0.25,
                        max_position_volume=0.03)
    result = calculate_position_volume(
        settings=settings, side=Side.BUY, equity=100000.0, entry_price=2700.0,
        stop_loss=2690.0, tick_size=1.0, tick_value_loss_per_lot=100.0,
        volume_min=0.01, volume_max=1.0, volume_step=0.01,
    )
    assert result == pytest.approx(0.03)


def test_rejects_when_minimum_lot_would_exceed_risk_budget() -> None:
    with pytest.raises(RiskSizingError, match="minimum broker volume"):
        size(equity=100.0)


def test_rejects_stop_loss_on_wrong_side() -> None:
    with pytest.raises(RiskSizingError, match="BUY stop-loss"):
        size(stop_loss=2701.0)


def test_rejects_non_finite_values() -> None:
    with pytest.raises(RiskSizingError, match="finite"):
        size(equity=float("nan"))


def test_rejects_missing_tick_value() -> None:
    with pytest.raises(RiskSizingError, match="tick size and loss tick value"):
        size(tick_value_loss_per_lot=0.0)
