import json
import psycopg

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS system_events (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS signals (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    entry DOUBLE PRECISION NOT NULL,
    stop DOUBLE PRECISION NOT NULL,
    target DOUBLE PRECISION NOT NULL,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS risk_decisions (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol TEXT NOT NULL,
    approved BOOLEAN NOT NULL,
    reason TEXT NOT NULL,
    payload JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_account (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    starting_equity DOUBLE PRECISION NOT NULL,
    cash_balance DOUBLE PRECISION NOT NULL,
    peak_equity DOUBLE PRECISION NOT NULL,
    daily_start_equity DOUBLE PRECISION NOT NULL,
    daily_start_date DATE NOT NULL DEFAULT CURRENT_DATE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS paper_positions (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('LONG','SHORT')),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','CLOSED')),
    entry_price DOUBLE PRECISION NOT NULL,
    current_price DOUBLE PRECISION NOT NULL,
    stop_price DOUBLE PRECISION NOT NULL,
    target_price DOUBLE PRECISION NOT NULL,
    exit_price DOUBLE PRECISION,
    qty DOUBLE PRECISION NOT NULL,
    notional DOUBLE PRECISION NOT NULL,
    leverage INTEGER NOT NULL,
    margin_used DOUBLE PRECISION NOT NULL,
    risk_usdt DOUBLE PRECISION NOT NULL,
    entry_fee DOUBLE PRECISION NOT NULL DEFAULT 0,
    exit_fee DOUBLE PRECISION NOT NULL DEFAULT 0,
    realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
    exit_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_paper_positions_active ON paper_positions(status, symbol);
CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_active_symbol ON paper_positions(symbol) WHERE status='ACTIVE';
CREATE TABLE IF NOT EXISTS paper_orders (
    id TEXT PRIMARY KEY,
    position_id TEXT NOT NULL REFERENCES paper_positions(id),
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    role TEXT NOT NULL,
    order_type TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_price DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS paper_fills (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES paper_orders(id),
    position_id TEXT NOT NULL REFERENCES paper_positions(id),
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty DOUBLE PRECISION NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    fee DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS shadow_signals (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bar_open_time TIMESTAMPTZ NOT NULL,
    strategy_name TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('LONG','SHORT')),
    confidence DOUBLE PRECISION NOT NULL,
    entry DOUBLE PRECISION NOT NULL,
    stop DOUBLE PRECISION NOT NULL,
    target DOUBLE PRECISION NOT NULL,
    volatility_pct DOUBLE PRECISION NOT NULL,
    reason JSONB NOT NULL,
    UNIQUE(strategy_name,strategy_version,symbol,side,bar_open_time)
);
CREATE INDEX IF NOT EXISTS idx_shadow_signals_ts ON shadow_signals(ts DESC);
CREATE TABLE IF NOT EXISTS shadow_candidates (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bar_open_time TIMESTAMPTZ NOT NULL,
    strategy_name TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('LONG','SHORT')),
    entry DOUBLE PRECISION NOT NULL,
    stop DOUBLE PRECISION NOT NULL,
    target DOUBLE PRECISION NOT NULL,
    volatility_pct DOUBLE PRECISION NOT NULL,
    opportunity_score DOUBLE PRECISION,
    opportunity_approved BOOLEAN NOT NULL DEFAULT FALSE,
    reason JSONB NOT NULL,
    outcome_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (outcome_status IN ('PENDING','TP_FIRST','SL_FIRST','AMBIGUOUS','TIMEOUT')),
    mfe_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    mae_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    mfe_r DOUBLE PRECISION NOT NULL DEFAULT 0,
    mae_r DOUBLE PRECISION NOT NULL DEFAULT 0,
    bars_observed INTEGER NOT NULL DEFAULT 0,
    resolved_at TIMESTAMPTZ,
    UNIQUE(strategy_name,strategy_version,symbol,side,bar_open_time)
);
CREATE INDEX IF NOT EXISTS idx_shadow_candidates_pending ON shadow_candidates(outcome_status, ts);
CREATE TABLE IF NOT EXISTS paper_funding_events (
    id BIGSERIAL PRIMARY KEY,
    position_id TEXT NOT NULL REFERENCES paper_positions(id),
    funding_time BIGINT NOT NULL,
    symbol TEXT NOT NULL,
    rate DOUBLE PRECISION NOT NULL,
    mark_price DOUBLE PRECISION NOT NULL,
    payment DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(position_id, funding_time)
);
CREATE TABLE IF NOT EXISTS reconciliation_snapshots (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ok BOOLEAN NOT NULL,
    payload JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS live_position_registry (
    symbol TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'CLOSED',
    side TEXT,
    qty DOUBLE PRECISION,
    entry_order_client_id TEXT,
    stop_order_client_id TEXT,
    tp_order_client_id TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS legacy_calibration_records (
    source_id TEXT PRIMARY KEY,
    source_sheet TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol TEXT,
    side TEXT,
    decision TEXT,
    outcome TEXT,
    entry DOUBLE PRECISION,
    stop DOUBLE PRECISION,
    target DOUBLE PRECISION,
    leverage INTEGER,
    liquidation_price DOUBLE PRECISION,
    payload JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS position_events (
    id BIGSERIAL PRIMARY KEY,
    position_id TEXT NOT NULL REFERENCES paper_positions(id),
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);
"""


def init_db(database_url: str, paper_starting_equity: float = 100.0) -> None:
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(SCHEMA_SQL)
        conn.execute("ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS funding_pnl DOUBLE PRECISION NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS entry_slippage_bps DOUBLE PRECISION NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS exit_slippage_bps DOUBLE PRECISION NOT NULL DEFAULT 0")
        conn.execute(
            """INSERT INTO paper_account
            (id,starting_equity,cash_balance,peak_equity,daily_start_equity)
            VALUES(1,%s,%s,%s,%s)
            ON CONFLICT (id) DO NOTHING""",
            (paper_starting_equity, paper_starting_equity, paper_starting_equity, paper_starting_equity),
        )


def log_event(database_url: str, event_type: str, payload: dict | None = None) -> None:
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO system_events(event_type,payload) VALUES(%s,%s::jsonb)",
            (event_type, json.dumps(payload or {})),
        )


def log_risk_decision(database_url: str, symbol: str, approved: bool, reason: str, payload: dict) -> None:
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO risk_decisions(symbol,approved,reason,payload) VALUES(%s,%s,%s,%s::jsonb)",
            (symbol, approved, reason, json.dumps(payload)),
        )
