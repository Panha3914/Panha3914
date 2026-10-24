# Architecture

```text
TUI (Textual)
  ├── App / State Controller
  ├── Quote & Account Read Model <── MT5 Adapter (read-only first)
  ├── Strategy Engine ───────────────> Signal (not an order)
  ├── Risk Manager <───────────────── Signal + account/position context
  ├── Order Service <──────────────── Approved OrderIntent
  │     ├── Paper Broker (default)
  │     └── MT5 execution adapter (disabled until explicitly enabled)
  ├── Audit/Event Log
  └── Telegram Notifier (outbound alerts only)
```

## Boundaries
- `config.py`: typed environment settings and safe defaults.
- `domain/models.py`: quote, signal, order intent and risk decision models.
- `mt5/adapter.py`: terminal health, symbol metadata, quotes and positions; isolate vendor calls.
- `strategies/base.py`: signal protocol and rationale.
- `risk/manager.py`: centralized pre-trade validation.
- `execution/service.py`: accepts only approved intents; paper broker by default.
- `ui/`: Textual screens and keyboard navigation.
- `notifications/telegram.py`: redacted outbound alerts.
- `audit/`: structured risk decisions and order lifecycle events.

## Order lifecycle
1. Strategy emits a timestamped signal with rationale; it cannot place orders.
2. Convert a signal into an order proposal only after symbol and market checks.
3. Risk manager independently validates connection, quote age, spread, session, volume/price increments, stop-loss, margin, exposure, daily loss, drawdown and position limits.
4. Rejections are audited with machine-readable reasons.
5. Approved intents go to paper execution by default. A separate explicit runtime gate is required for any future live adapter.
6. Record request/response values, retcodes, timestamps and resulting state. Reconcile broker state after uncertain timeouts to avoid duplicates.

## Failure handling
Fail closed on missing account state, stale quotes, API errors, unknown order outcomes, invalid metadata, or risk-manager exceptions. Never retry order submission blindly after a timeout. Kill switch blocks new orders. Use UTC internally and configured local time in UI. Never log secrets.

## Testing
Unit tests for risk boundaries, contract tests against fake adapters, UI tests for stale/disconnected/kill-switch states, and demo-only integration tests behind explicit opt-in. CI must not require MT5, broker credentials, or network access.
