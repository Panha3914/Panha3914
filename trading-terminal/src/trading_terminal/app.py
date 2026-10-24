"""Textual dashboard for read-only MT5 monitoring and simulated paper trading."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import monotonic

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Label, Static

from trading_terminal.audit.jsonl import JsonlAuditLogger
from trading_terminal.config import Settings
from trading_terminal.execution.engine import PaperOrderEngine, PaperOrderStatus
from trading_terminal.execution.paper_portfolio import PaperPortfolio
from trading_terminal.mt5.adapter import MT5ReadOnlyAdapter
from trading_terminal.notifications.telegram import TelegramNotificationError, TelegramNotifier
from trading_terminal.risk.state_tracker import RiskMetrics, RiskStateTracker
from trading_terminal.strategies.ema_crossover import EMACrossoverStrategy


class TradingTerminalApp(App[None]):
    TITLE = "TUI Trading Terminal | MT5 / XAUUSD"
    SUB_TITLE = "SAFE MODE — MT5 read-only; simulated paper fills only"
    CSS = """
    Screen { background: #10151d; color: #dbe4ee; }
    .panel { border: round #52657a; padding: 1; margin: 1; height: auto; }
    .heading { text-style: bold; color: #72d5ff; }
    #mt5-status { color: #ffcf66; }
    #quote-status, #account-status, #positions-status, #paper-portfolio-status { height: auto; }
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._adapter = (
            MT5ReadOnlyAdapter(
                terminal_path=settings.mt5_path,
                timeout_seconds=settings.mt5_timeout_seconds,
            )
            if settings.mt5_enabled
            else None
        )
        self._connected = False
        self._refresh_in_progress = False
        self._connection_attempt_in_progress = False
        self._last_connection_attempt = 0.0
        self._strategy = EMACrossoverStrategy()
        self._audit = JsonlAuditLogger(settings.audit_log_path)
        self._audited_signal_keys: set[tuple[str, str, str]] = set()
        self._audit_warning: str | None = None
        self._risk_state_tracker = RiskStateTracker(settings.risk_state_db_path)
        self._paper_risk_tracker = RiskStateTracker(settings.risk_state_db_path)
        self._paper_portfolio = PaperPortfolio(
            settings.paper_state_db_path,
            starting_balance=settings.paper_initial_balance,
            slippage_points=settings.paper_slippage_points,
            commission_per_lot_round_turn=settings.paper_commission_per_lot_round_turn,
        )
        self._paper_engine = PaperOrderEngine(
            settings,
            audit=self._audit,
            paper_portfolio=self._paper_portfolio,
        )
        self._notifier: TelegramNotifier | None = None
        self._telegram_status = "Telegram notifications disabled"
        if settings.telegram_enabled:
            try:
                self._notifier = TelegramNotifier(settings)
                self._telegram_status = "Telegram enabled — outbound signal alerts only"
            except TelegramNotificationError as exc:
                self._telegram_status = f"Telegram not configured: {exc}"

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(classes="panel"):
                yield Label("CONNECTION / MARKET", classes="heading")
                initial_connection = (
                    "MT5 enabled; connecting to local terminal..."
                    if self.settings.mt5_enabled
                    else "MT5 disabled by configuration"
                )
                yield Static(initial_connection, id="mt5-status")
                yield Static(f"Symbol: {self.settings.mt5_symbol}")
                yield Static("Bid / Ask / Spread: waiting for quote", id="quote-status")
                yield Static("Broker account: unavailable", id="account-status")
                yield Static("Broker positions: unavailable", id="positions-status")
                yield Static("Paper portfolio: not initialized", id="paper-portfolio-status")
            with Vertical(classes="panel"):
                yield Label("RISK CONTROLS", classes="heading")
                yield Static(f"Trading mode: {self.settings.trading_mode.upper()}")
                yield Static(
                    f"Kill switch: {'ON' if self.settings.kill_switch else 'OFF'}",
                    id="kill-switch-status",
                )
                yield Static(f"Maximum spread: {self.settings.max_spread_points} points")
                yield Static(f"Maximum open positions: {self.settings.max_open_positions}")
                yield Static(f"Maximum position volume: {self.settings.max_position_volume}")
                yield Static(f"Risk per trade: {self.settings.max_risk_per_trade_percent:.2f}%")
        with Horizontal():
            with Vertical(classes="panel"):
                yield Label("STRATEGY", classes="heading")
                yield Static("EMA(9/21) crossover on closed candles; informational signals only.")
                yield Static("Waiting for closed candle history...", id="strategy-status")
                yield Static("Signals can create local simulated fills; no MT5 order is sent.")
            with Vertical(classes="panel"):
                yield Label("PAPER EXECUTION", classes="heading")
                yield Static(
                    "PAPER ONLY — simulated positions are stored locally; no broker orders exist.",
                    id="execution-status",
                )
                yield Static("Waiting for signal and risk checks...", id="paper-order-status")
                yield Static(self._telegram_status, id="telegram-status")
                yield Static(f"Audit log: {self.settings.audit_log_path}", id="audit-status")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(1.0, self._schedule_market_refresh)
        if self._adapter is not None:
            self._start_connection_attempt()

    def _start_connection_attempt(self) -> None:
        self._connection_attempt_in_progress = True
        self._last_connection_attempt = monotonic()
        self.run_worker(
            self._connect_mt5,
            name="mt5-connect",
            group="mt5-connect",
            thread=True,
            exclusive=True,
        )

    def on_unmount(self) -> None:
        if self._adapter is not None:
            self._adapter.disconnect()

    def _connect_mt5(self) -> None:
        assert self._adapter is not None
        try:
            self._adapter.connect()
        except Exception as exc:  # noqa: BLE001 - display adapter failures and fail closed
            self._write_audit("mt5_connection_failed", {"error_type": type(exc).__name__})
            self.call_from_thread(
                self._set_connection_state,
                False,
                f"MT5 connection failed ({type(exc).__name__}): {exc}",
            )
        else:
            self._write_audit(
                "mt5_connected",
                {"symbol": self.settings.mt5_symbol, "timeframe": self.settings.mt5_timeframe},
            )
            self.call_from_thread(
                self._set_connection_state,
                True,
                "CONNECTED — read-only market/account data",
            )
        finally:
            self.call_from_thread(self._finish_connection_attempt)

    def _finish_connection_attempt(self) -> None:
        self._connection_attempt_in_progress = False

    def _set_connection_state(self, connected: bool, message: str) -> None:
        self._connected = connected
        self.query_one("#mt5-status", Static).update(message)

    def _schedule_market_refresh(self) -> None:
        if self._adapter is None:
            return
        if not self._connected:
            retry_due = monotonic() - self._last_connection_attempt >= 10.0
            if not self._connection_attempt_in_progress and retry_due:
                self._start_connection_attempt()
            return
        if self._refresh_in_progress:
            return
        self._refresh_in_progress = True
        self.run_worker(
            self._read_market_snapshot,
            name="mt5-read-snapshot",
            group="mt5-market-data",
            thread=True,
            exclusive=True,
        )

    def _read_market_snapshot(self) -> None:
        assert self._adapter is not None
        try:
            quote = self._adapter.get_quote(self.settings.mt5_symbol)
            symbol_spec = self._adapter.get_symbol_spec(quote.symbol)
            account = self._adapter.get_account_snapshot()
            broker_positions = self._adapter.get_positions()
            bars = self._adapter.get_closed_bars(
                quote.symbol, timeframe=self.settings.mt5_timeframe, count=100
            )
            now = datetime.now(UTC)

            broker_risk = self._risk_state_tracker.observe(
                account_identity=f"{account.login}:{account.currency}",
                equity=account.equity,
                now=now,
            )
            paper_snapshot = self._paper_portfolio.snapshot(
                quote, symbol_spec, currency=account.currency, now=now
            )
            paper_risk: RiskMetrics | None = None
            if paper_snapshot.equity > 0:
                paper_risk = self._paper_risk_tracker.observe(
                    account_identity=f"paper:{account.currency}",
                    equity=paper_snapshot.equity,
                    now=now,
                )

            signal = self._strategy.evaluate(quote.symbol, bars)
            telegram_text = self._telegram_status
            paper_status_text = "No crossover; no paper entry proposal."
            if paper_snapshot.equity <= 0:
                paper_status_text = "PAPER RISK HALT: virtual equity is zero or negative."
            elif signal is not None and paper_risk is not None:
                signal_key = (signal.symbol, signal.side.value, signal.timestamp.isoformat())
                if signal_key not in self._audited_signal_keys:
                    self._audited_signal_keys.add(signal_key)
                    self._write_audit(
                        "strategy_signal",
                        {
                            "symbol": signal.symbol,
                            "side": signal.side.value,
                            "candle_time": signal.timestamp,
                            "stop_loss_reference": signal.stop_loss,
                            "take_profit_reference": signal.take_profit,
                            "rationale": signal.rationale,
                            "action": "informational_signal_only",
                        },
                    )

                if self._notifier is not None:
                    try:
                        sent = asyncio.run(self._notifier.send_signal_once(signal))
                        telegram_text = (
                            "Telegram: signal alert sent"
                            if sent
                            else "Telegram: same candle alert already sent"
                        )
                        self._write_audit(
                            "telegram_signal_alert",
                            {
                                "symbol": signal.symbol,
                                "side": signal.side.value,
                                "candle_time": signal.timestamp,
                                "sent": sent,
                            },
                        )
                    except TelegramNotificationError as exc:
                        self._write_audit(
                            "telegram_alert_failed", {"error_type": type(exc).__name__}
                        )
                        telegram_text = f"Telegram alert failed: {exc}"

                outcome = self._paper_engine.process_signal(
                    signal,
                    quote,
                    symbol_spec,
                    account_equity=paper_snapshot.equity,
                    open_positions=paper_snapshot.open_position_count,
                    daily_loss_percent=paper_risk.daily_loss_percent,
                    drawdown_percent=paper_risk.drawdown_percent,
                    account_state_known=True,
                    currency=account.currency,
                    now=now,
                )
                if outcome.status is PaperOrderStatus.FILLED:
                    paper_status_text = (
                        f"PAPER FILL (SIMULATED): {outcome.order_id} | "
                        f"{outcome.volume} lots @ {outcome.entry_price} | NO BROKER ORDER"
                    )
                    paper_snapshot = self._paper_portfolio.snapshot(
                        quote, symbol_spec, currency=account.currency, now=now
                    )
                    if paper_snapshot.equity > 0:
                        self._paper_risk_tracker.observe(
                            account_identity=f"paper:{account.currency}",
                            equity=paper_snapshot.equity,
                            now=now,
                        )
                elif outcome.status is PaperOrderStatus.PROPOSED:
                    paper_status_text = (
                        f"PAPER PROPOSAL: {outcome.order_id} | {outcome.volume} lots "
                        f"@ {outcome.entry_price} | NOT SENT TO BROKER"
                    )
                elif outcome.status is PaperOrderStatus.REJECTED:
                    paper_status_text = f"PAPER ENTRY REJECTED: {', '.join(outcome.reasons)}"
                else:
                    paper_status_text = f"Signal already evaluated: {outcome.status.value}"

            age = max(0.0, (now - quote.timestamp).total_seconds())
            quote_text = (
                f"Bid {quote.bid:.{symbol_spec.digits}f} | "
                f"Ask {quote.ask:.{symbol_spec.digits}f} | "
                f"Spread {quote.spread_points:.1f} points | Tick age {age:.1f}s"
            )
            account_text = (
                f"Broker balance {account.balance:,.2f} {account.currency} | "
                f"Equity {account.equity:,.2f} | Free margin {account.margin_free:,.2f} | "
                f"Observed loss {broker_risk.daily_loss_percent:.2f}% | "
                f"Observed drawdown {broker_risk.drawdown_percent:.2f}%"
            )
            floating_pnl = sum(position.profit for position in broker_positions)
            positions_text = (
                f"MT5 positions: {len(broker_positions)} | "
                f"Floating P/L {floating_pnl:,.2f} {account.currency}"
            )
            paper_portfolio_text = (
                f"Virtual balance {paper_snapshot.balance:,.2f} {paper_snapshot.currency} | "
                f"Equity {paper_snapshot.equity:,.2f} | "
                f"Paper positions {paper_snapshot.open_position_count} | "
                f"Floating P/L {paper_snapshot.unrealized_pnl:,.2f}"
            )
            if signal is None:
                strategy_text = (
                    f"No EMA({self._strategy.fast_period}/{self._strategy.slow_period}) "
                    f"crossover on latest closed {self.settings.mt5_timeframe} candle."
                )
            else:
                strategy_text = (
                    f"{signal.side.value} SIGNAL ONLY | close "
                    f"{bars[-1].close:.{symbol_spec.digits}f} | "
                    f"SL {signal.stop_loss:.{symbol_spec.digits}f} | "
                    f"TP {signal.take_profit:.{symbol_spec.digits}f} | "
                    f"{signal.timestamp.isoformat()}"
                )
        except Exception as exc:  # noqa: BLE001 - display failures and fail closed
            self._write_audit("market_data_error", {"error_type": type(exc).__name__})
            self.call_from_thread(
                self._apply_market_error,
                f"Market/account read failed ({type(exc).__name__}): {exc}",
            )
        else:
            self.call_from_thread(
                self._apply_market_snapshot,
                quote_text,
                account_text,
                positions_text,
                paper_portfolio_text,
                strategy_text,
                telegram_text,
                paper_status_text,
            )
        finally:
            self.call_from_thread(self._finish_refresh)

    def _apply_market_snapshot(
        self,
        quote_text: str,
        account_text: str,
        positions_text: str,
        paper_portfolio_text: str,
        strategy_text: str,
        telegram_text: str,
        paper_status_text: str,
    ) -> None:
        self.query_one("#quote-status", Static).update(quote_text)
        self.query_one("#account-status", Static).update(account_text)
        self.query_one("#positions-status", Static).update(positions_text)
        self.query_one("#paper-portfolio-status", Static).update(paper_portfolio_text)
        self.query_one("#strategy-status", Static).update(strategy_text)
        self.query_one("#telegram-status", Static).update(telegram_text)
        self.query_one("#paper-order-status", Static).update(paper_status_text)
        self._set_connection_state(True, "CONNECTED — read-only market/account data")

    def _apply_market_error(self, message: str) -> None:
        self.query_one("#quote-status", Static).update(message)
        self._set_connection_state(False, "MT5 read failed; new entries must remain blocked")

    def _finish_refresh(self) -> None:
        self._refresh_in_progress = False

    def _write_audit(self, event_type: str, fields: dict[str, object]) -> None:
        """Keep monitoring alive if local disk logging temporarily fails."""
        try:
            self._audit.write(event_type, fields)
            self._audit_warning = None
        except OSError as exc:
            self._audit_warning = type(exc).__name__


def main() -> None:
    TradingTerminalApp(Settings()).run()


if __name__ == "__main__":
    main()
