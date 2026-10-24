import asyncio
from pathlib import Path

from textual.widgets import Static

from trading_terminal.app import TradingTerminalApp
from trading_terminal.config import Settings


def test_tui_starts_without_mt5_and_keeps_paper_safe_defaults(tmp_path: Path) -> None:
    async def run_app() -> None:
        settings = Settings(
            mt5_enabled=False,
            audit_log_path=str(tmp_path / "audit.jsonl"),
            risk_state_db_path=str(tmp_path / "risk.sqlite3"),
            paper_state_db_path=str(tmp_path / "paper.sqlite3"),
        )
        app = TradingTerminalApp(settings)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#mt5-status", Static).id == "mt5-status"
            assert app.query_one("#execution-status", Static).id == "execution-status"
            assert app.query_one("#kill-switch-status", Static).id == "kill-switch-status"
            assert settings.mt5_enabled is False
            assert settings.kill_switch is True
            assert settings.trading_mode == "paper"

    asyncio.run(run_app())
