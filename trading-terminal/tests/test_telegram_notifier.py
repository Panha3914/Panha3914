import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from trading_terminal.config import Settings
from trading_terminal.domain.models import Side, TradeSignal
from trading_terminal.notifications.telegram import (
    TelegramNotificationError,
    TelegramNotifier,
)


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def send_message(self, *, chat_id: str, text: str) -> None:
        self.messages.append((chat_id, text))


def test_disabled_telegram_is_rejected() -> None:
    with pytest.raises(TelegramNotificationError, match="disabled"):
        TelegramNotifier(Settings())


def test_missing_telegram_credentials_are_rejected() -> None:
    settings = Settings(telegram_enabled=True)
    with pytest.raises(TelegramNotificationError, match="missing"):
        TelegramNotifier(settings)


def test_signal_notification_is_sent_once_per_closed_candle() -> None:
    bot = FakeBot()
    settings = Settings(
        telegram_enabled=True,
        telegram_bot_token=SecretStr("test-token"),
        telegram_chat_id="12345",
    )
    notifier = TelegramNotifier(settings, bot=bot)
    signal = TradeSignal(
        symbol="XAUUSD", side=Side.BUY, timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        rationale="test crossover only", stop_loss=2690.0, take_profit=2720.0,
    )

    assert asyncio.run(notifier.send_signal_once(signal)) is True
    assert asyncio.run(notifier.send_signal_once(signal)) is False
    assert len(bot.messages) == 1
    assert bot.messages[0][0] == "12345"
    assert "not an order" in bot.messages[0][1]
    assert "test-token" not in bot.messages[0][1]


def test_empty_message_is_not_sent() -> None:
    settings = Settings(
        telegram_enabled=True,
        telegram_bot_token=SecretStr("test-token"),
        telegram_chat_id="12345",
    )
    with pytest.raises(TelegramNotificationError, match="empty"):
        asyncio.run(TelegramNotifier(settings, bot=FakeBot()).send_text("  "))
