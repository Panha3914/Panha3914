# TUI Trading Terminal — MT5 / XAUUSD

A Windows-friendly Python Textual terminal for MT5 **read-only** market/account monitoring, closed-candle EMA signals, centralized risk checks, risk-based volume sizing, a persistent simulated paper portfolio, redacted audit events, and optional outbound Telegram alerts.

> **Safety status:** This build has no MT5 order-submission implementation. It can create simulated paper fills in a local SQLite database; those fills are not broker trades. Defaults are `TRADING_MODE=paper`, `MT5_ENABLED=false`, and `KILL_SWITCH=true`.

## Current features

- **MT5 read-only adapter:** connection status, quotes, account snapshot, symbol contract metadata, live broker positions, and closed OHLC candles. The forming candle is excluded from strategy input. Connection retries are throttled.
- **Strategy:** EMA(9/21) cross on closed candles with ATR-based stop/target references. Signals are informational and do not imply profitability.
- **Centralized risk manager:** kill switch, quote freshness, spread, account state, symbol match, maximum volume/positions, daily-loss/drawdown limits, timestamp checks, and protective stop/target placement.
- **Position sizing:** calculates lot size from equity risk budget, stop distance, broker tick size/loss value, and broker volume steps. Rounds down; rejects if broker minimum volume would exceed the risk budget. Paper entry sizing includes configured adverse slippage.
- **Persistent paper portfolio:** a local SQLite ledger stores simulated positions, starting balance, entry and exit references, and close reasons. Marks positions to market and simulates stop-loss/take-profit exits. It supports configurable slippage and commission. It never contacts MT5's order API.
- **Risk state:** SQLite stores observed-equity baselines under hashed identities. Daily loss is calculated from the first equity observation of each UTC day; it cannot infer losses before the app's first observation that day.
- **Audit:** append-only JSONL events with recursive redaction of sensitive field names.
- **Telegram:** optional outbound-only signal notifications, deduplicated by symbol/side/candle time. No Telegram trade commands.
- **Windows scripts:** `INSTALL_WINDOWS.bat` creates the virtual environment and local `.env`; `RUN_WINDOWS.bat` starts the terminal.
- **CI:** GitHub Actions runs pytest and Ruff without MT5, broker credentials or Telegram credentials.

## Windows setup

Prerequisites: Windows 10/11 or Windows Server, Python 3.12 x64, and network access for package installation.

1. Open the `trading-terminal` directory in this repository.
2. Run `INSTALL_WINDOWS.bat` once.
3. Run `RUN_WINDOWS.bat`.

The installer copies `.env.example` to a local `.env` if one does not exist. It does not add credentials. Keep `.env` private and do not commit it.

### MT5 read-only connection

Install MetaTrader 5 on the same Windows host and log in through its terminal. Set `MT5_ENABLED=true` in local `.env`; set `MT5_PATH=C:\\Path\\To\\terminal64.exe` only if auto-discovery is insufficient. Check the broker's exact gold symbol (some accounts use `XAUUSD.a`, `GOLD`, or another suffix).

This integration reads account/market data only. The code intentionally has no `order_send` path.

### Telegram alerts (optional)

Set `TELEGRAM_ENABLED=true`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID` in local `.env`. The bot token is a secret; do not commit or paste it into source files. Alerts are informational only.

## Paper portfolio configuration

Local `.env` settings:
- `PAPER_STATE_DB_PATH=logs/paper-portfolio.sqlite3`
- `PAPER_INITIAL_BALANCE=10000`
- `PAPER_SLIPPAGE_POINTS=2`
- `PAPER_COMMISSION_PER_LOT_ROUND_TURN=0`

The starting balance is recorded the first time the paper database is initialized. Changing `PAPER_INITIAL_BALANCE` later does not reset an existing database. Use a separate state file if you intentionally want a fresh paper account or a different account currency. Back up or delete paper state only when the terminal is stopped and you understand that it resets simulated history.

Paper results are only as reliable as the assumptions used for slippage, commission, tick values and intrabar price data. Candle-only strategy inputs cannot reproduce exact market execution. The paper portfolio's stop/target simulation is not equivalent to a broker fill model.

## Development / tests

From the `trading-terminal` directory:
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
pytest
ruff check src tests
python -m trading_terminal.app
```

For optional Windows integrations:
```powershell
pip install -e ".[dev,mt5,telegram]"
```

## Limitations and next steps

- **No live or demo broker execution.** The current app is a read-only MT5 monitor plus a simulated paper portfolio.
- The paper engine simulates fills; it is not a full historical backtester and does not establish strategy profitability.
- The daily risk baseline is based on observed equity, not broker historical daily P/L.
- Broker-specific contract/stop rules need verification on the exact account before any future execution adapter is considered.
- Before introducing real order submission, add independently reviewed execution safeguards, idempotent broker reconciliation, demo-account integration testing, robust day-loss persistence, operator confirmations, and explicit opt-in gates. Keep real trading disabled until those checks pass.
