# Implementation Roadmap

## Current scaffold — implemented
- [x] Typed settings, domain models and safe defaults.
- [x] Textual terminal dashboard with connection, quote, broker account/positions, risk state, strategy signal, paper portfolio, Telegram and audit status.
- [x] Read-only MT5 adapter for quotes, account, symbol metadata, open positions and closed candles.
- [x] EMA crossover signal strategy and ATR-based stop/target references using closed bars.
- [x] Centralized pre-trade risk checks and conservative risk-budget position sizing.
- [x] SQLite-based observed-equity baselines and persistent paper portfolio.
- [x] Simulated fills, adverse slippage, optional commission, mark-to-market and simulated SL/TP exits.
- [x] Outbound-only Telegram notifier; no trade commands.
- [x] Redacted JSONL audit log, Windows setup/launch scripts and GitHub Actions tests.

## Phase 2 — verify read-only integration on the user's Windows host
- [ ] Confirm MT5 install/path, account login and broker-specific XAUUSD symbol.
- [ ] Check actual symbol tick size/value, volume step/min/max and stop-distance metadata.
- [ ] Run read-only soak test and confirm reconnection behavior over terminal/network interruptions.
- [ ] Confirm local SQLite/JSONL permissions, backup and disk-full handling.

## Phase 3 — strengthen strategy validation
- [ ] Build historical candle backtester with spread, commission, slippage, stop/target ordering and closed-candle safeguards.
- [ ] Add out-of-sample and walk-forward evaluation with documented assumptions.
- [ ] Assess symbol/timeframe sensitivity; do not infer profitability from indicator crossovers or a short sample.

## Phase 4 — risk state and paper fidelity
- [ ] Persist broker-reported daily P/L/equity baselines where supported and reconcile after app downtime.
- [ ] Add test coverage for market gaps, stop/target collisions, currency changes, costs and persistent restart behavior.
- [ ] Add configurable maximum paper portfolio loss and an explicit paper-only circuit breaker.
- [ ] Validate simulated fills against recorded tick data where possible.

## Phase 5 — operations and quality
- [ ] Add mypy/type checks, dependency review and security scanning to CI.
- [ ] Add log rotation and application health diagnostics.
- [ ] Add screen-level UI tests for disconnection, stale data, risk rejection and depleted paper equity.
- [ ] Verify Windows setup on a clean Windows Server environment.

## Future live execution — intentionally out of scope
Real order submission must not be enabled without independent review, demo-account integration tests, broker-state reconciliation, duplicate-order prevention, operator confirmations, and explicit fail-closed gates. The current implementation intentionally contains no MT5 order-send path.

## Acceptance criteria for current paper build
- Unit tests run without a local MT5 terminal or broker credentials.
- GitHub Actions test and lint jobs pass on the reviewed commit.
- MT5 calls are read-only.
- Signal-to-paper-fill flow applies risk checks, sizes with broker metadata and records simulated entries/exits.
- Stale/disconnected data, unknown risk state, invalid contract metadata or risk-limit violations prevent new paper entries.
