# Instructions for Codex / Coding Agents

1. Inspect the repository, architecture and existing tests before editing.
2. Work in small, reviewable steps; do not overwrite unrelated files.
3. Keep strategy, risk, execution, UI, MT5, Telegram and audit logic separate.
4. Default to paper mode. Never enable live trading implicitly or use real credentials in tests.
5. Never hardcode or log credentials. Do not commit `.env` files.
6. Fail closed on stale quotes, missing account state, invalid symbol metadata, disconnects, or risk errors.
7. Signals are not orders. Only explicitly risk-approved OrderIntent objects reach execution.
8. Do not implement martingale, grid recovery or loss-chasing. Do not claim profitability.
9. Provide deterministic tests for normal, boundary and failure cases; use fake adapters in CI.
10. Run relevant tests/lint/type checks and report actual commands and results without inventing success.
11. Avoid swallowing exceptions; log redacted actionable errors and fail safely.
12. Document broker-specific assumptions and keep execution disabled until verified on demo.
13. Each PR should state summary, changed paths, tests, limitations and next steps.
14. Do not merge pull requests automatically; leave review/merge to the repository owner.
