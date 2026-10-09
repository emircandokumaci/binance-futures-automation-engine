# From Make.com Prototype to a Self-Hosted Futures Engine

## Background

The project began as a Binance market-analysis and paper-trading automation built around Make.com scenarios, Google Sheets, scheduled scanners, and workflow-level decision logic.

That prototype was useful for validating the workflow concept, but it also exposed several architectural limits: SaaS operation costs, fragmented state, workflow-level complexity, limited observability, and difficulty enforcing deterministic safety rules across the whole system.

## Phase 1 — Make.com prototype

The original automation included four primary Make.com scenarios:

- `MX v5 Volatility-Aware Paper Scanner`
- `MX v5 1m Outcome Monitor`
- `MX v5 Health Auditor`
- `MX v5 Momentum Research Scanner`

It also used Google Sheets-backed historical and operational state, plus supporting status/reporting logic.

The system remained paper-only and did not include real Binance order submission.

## Phase 2 — Self-hosted migration

The next step moved the core workflow to a DigitalOcean Ubuntu server and introduced:

- Python-based deterministic execution logic
- Local state storage
- n8n orchestration experiments
- API bridge patterns
- Explicit health checks
- Idempotent import and replay testing
- Fail-closed behavior when required inputs were missing

The Make workflows were treated as the behavioral reference, not blindly copied. Logic that should be deterministic — risk, exits, validation, scheduling, and safety — was moved into code.

## Phase 3 — Futures Engine

The current architecture evolved into a dedicated FastAPI + PostgreSQL + Docker application.

Major additions include:

- Binance public REST/WebSocket clients
- Liquid USDT perpetual universe selection
- Multi-timeframe shadow strategy
- Market-context scoring derived from the earlier automation research model
- Deterministic position sizing and portfolio risk controls
- Paper execution with fees, slippage, funding, and PnL tracking
- Exchange-rule normalization
- Liquidation readiness checks
- Optional private API reconciliation adapter
- Shadow outcome tracking
- Backtesting endpoint
- Database housekeeping and backup layers
- Automated test suite

## Why the architecture changed

The primary design goal became reliability rather than simply automating more steps.

The server-native design makes it possible to:

1. Keep strategy generation separate from execution.
2. Make risk decisions deterministic and testable.
3. Preserve state in a dedicated database rather than across workflow modules.
4. Reject unsafe or incomplete states explicitly.
5. Test individual components independently.
6. Run the system without depending on a paid automation platform for every execution.
7. Keep live trading disabled until explicit technical validation gates are satisfied.

## Safety model

The published project is intentionally paper-only.

The application refuses to start in a live-trading configuration, and strategy modules can only propose signals. Execution, risk, reconciliation, and readiness are separate layers.

This is a portfolio snapshot of the engineering process and system architecture. It is not financial advice and does not claim profitability.
