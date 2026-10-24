"""Typed settings with conservative, fail-safe defaults."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)

    trading_mode: Literal["paper", "demo", "live"] = "paper"
    mt5_enabled: bool = False
    mt5_path: str | None = None
    mt5_symbol: str = "XAUUSD"
    mt5_timeframe: Literal["M1", "M5", "M15", "M30", "H1", "H4", "D1"] = "M5"
    audit_log_path: str = "logs/trading-terminal.jsonl"
    risk_state_db_path: str = "logs/risk-state.sqlite3"
    paper_state_db_path: str = "logs/paper-portfolio.sqlite3"
    paper_initial_balance: float = Field(default=10_000.0, gt=0, allow_inf_nan=False)
    paper_slippage_points: float = Field(default=2.0, ge=0, allow_inf_nan=False)
    paper_commission_per_lot_round_turn: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    mt5_timeout_seconds: int = Field(default=10, ge=1, le=120)
    quote_max_age_seconds: int = Field(default=5, ge=1, le=300)
    max_spread_points: float = Field(default=50, gt=0)
    max_risk_per_trade_percent: float = Field(default=0.25, gt=0, le=1.0)
    max_daily_loss_percent: float = Field(default=2.0, gt=0, le=10.0)
    max_drawdown_percent: float = Field(default=5.0, gt=0, le=20.0)
    max_open_positions: int = Field(default=1, ge=1, le=10)
    max_position_volume: float = Field(default=0.01, gt=0)
    kill_switch: bool = True
    telegram_enabled: bool = False
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    @field_validator("mt5_symbol")
    @classmethod
    def symbol_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("MT5_SYMBOL must not be blank")
        return value

    def live_execution_permitted_by_config(self) -> bool:
        """Conservative config gate; execution still needs explicit checks elsewhere."""
        return self.trading_mode == "live" and self.mt5_enabled and not self.kill_switch
