# Jarvis Futures Engine

Phase 1 production skeleton for Binance Global USDⓈ-M Futures research and paper execution.

Safety invariants:
- PAPER_ONLY hard guard. No signed Binance endpoints and no real order submission code.
- 08:00-09:00 Europe/Istanbul: NO_NEW_TRADES.
- Strategy output must pass deterministic Risk Engine.
- Position sizing is stop-distance based; leverage is a margin/exposure control, not the definition of trade risk.
- Existing n8n/YouTube stack is isolated from this project.

Current services:
- `jarvis-futures-engine`: FastAPI + public Binance REST/WebSocket + risk preview.
- `jarvis-futures-postgres`: dedicated PostgreSQL journal database.

Local API is bound to `127.0.0.1:8091` only.

Next phases: exchange filters/universe, strategy engine, paper execution/state machine, exact Binance margin/liquidation brackets, reconciliation, private API adapter, exchange-side protective orders, mobile dashboard/alerts. Live trading remains disabled until explicit validation gates are passed.
