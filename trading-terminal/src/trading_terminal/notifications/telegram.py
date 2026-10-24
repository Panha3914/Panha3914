"""Optional Telegram alerts for informational signals only."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from trading_terminal.config import Settings
from trading_terminal.domain.models import TradeSignal

logger = logging.getLogger(__name__)


class TelegramNotificationError(RuntimeError):
    """Raised for invalid notification setup or send failures."""


class TelegramNotifier:
    """Send outbound-only, deduplicated signal alerts; no command handlers."""

    def __init__(self, settings: Settings, *, bot: Any | None = None) -> None:
        if not settings.telegram_enabled:
            raise TelegramNotificationError("Telegram notifications are disabled")
        token = (
            settings.telegram_bot_token.get_secret_value()
            if settings.telegram_bot_token is not None
            else ""
        )
        chat_id = (settings.telegram_chat_id or "").strip()
        if not token or not chat_id:
            raise TelegramNotificationError(
                "Telegram is enabled but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing"
            )
        if bot is None:
            try:
                from telegram import Bot
            except ImportError as exc:
                raise TelegramNotificationError(
                    "python-telegram-bot is not installed; install the optional 'telegram' extra"
                ) from exc
            bot = Bot(token=token)
        self._bot = bot
        self._chat_id = chat_id
        self._sent_signal_keys: set[tuple[str, str, str]] = set()
        self._pending_signal_keys: set[tuple[str, str, str]] = set()
        self._lock = threading.Lock()

    async def send_text(self, message: str) -> None:
        """Send plain text and never include credentials in the payload."""
        clean_message = message.strip()
        if not clean_message:
            raise TelegramNotificationError("Cannot send an empty Telegram message")
        clean_message = clean_message[:4000]

        initialized_here = False
        initialize = getattr(self._bot, "initialize", None)
        shutdown = getattr(self._bot, "shutdown", None)
        try:
            if callable(initialize):
                await initialize()
                initialized_here = True
            result = self._bot.send_message(chat_id=self._chat_id, text=clean_message)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # noqa: BLE001 - notification boundary normalizes client failures
            raise TelegramNotificationError(
                f"Telegram send failed ({type(exc).__name__})"
            ) from None
        finally:
            if initialized_here and callable(shutdown):
                try:
                    await shutdown()
                except Exception as exc:  # noqa: BLE001 - cleanup must not hide send result
                    logger.debug("Telegram client cleanup failed (%s)", type(exc).__name__)

    async def send_signal_once(self, signal: TradeSignal) -> bool:
        """Send a signal at most once per symbol/side/candle timestamp in this process."""
        key = (signal.symbol, signal.side.value, signal.timestamp.isoformat())
        with self._lock:
            if key in self._sent_signal_keys or key in self._pending_signal_keys:
                return False
            self._pending_signal_keys.add(key)

        message = (
            f"XAUUSD / {signal.symbol} — {signal.side.value} SIGNAL (not an order)\n"
            f"Closed candle: {signal.timestamp.isoformat()}\n"
            f"Stop-loss reference: {signal.stop_loss}\n"
            f"Take-profit reference: {signal.take_profit}\n"
            f"Rationale: {signal.rationale}"
        )
        try:
            await self.send_text(message)
        except TelegramNotificationError:
            with self._lock:
                self._pending_signal_keys.discard(key)
            raise
        with self._lock:
            self._pending_signal_keys.discard(key)
            self._sent_signal_keys.add(key)
        return True
