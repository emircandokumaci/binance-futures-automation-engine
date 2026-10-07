from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "production"
    trading_mode: str = "paper"
    live_trading_enabled: bool = False
    tz: str = "Europe/Istanbul"

    database_url: str
    binance_fapi_base: str = "https://fapi.binance.com"
    binance_ws_base: str = "wss://fstream.binance.com/market"
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_recv_window: int = 5000
    private_reconcile_interval_seconds: int = 15

    no_new_trades_start: str = "08:00"
    no_new_trades_end: str = "09:00"

    default_risk_pct: float = 1.0
    max_risk_pct: float = 2.0
    confidence_risk_scaling_enabled: bool = False
    confidence_leverage_scaling_enabled: bool = False
    normal_max_leverage: int = 5
    absolute_max_leverage: int = 10
    max_portfolio_gross_leverage: float = 3.0
    max_margin_utilization: float = 0.50
    daily_loss_limit_pct: float = 10.0
    hard_drawdown_pct: float = 25.0
    max_concurrent_positions: int = 2
    paper_taker_fee_rate: float = 0.0005
    paper_slippage_bps: float = 5.0
    paper_starting_equity: float = 100.0
    universe_top_n: int = 20
    min_quote_volume_usdt: float = 50_000_000.0
    max_spread_bps: float = 8.0
    min_listing_age_days: int = 30
    shadow_outcome_horizon_hours: int = 24
    require_liquidation_brackets_for_live: bool = True
    min_liquidation_buffer_pct: float = 7.5
    min_liquidation_stop_multiple: float = 2.5
    dynamic_slippage_floor_bps: float = 0.5
    dynamic_slippage_cap_bps: float = 25.0

    model_config = SettingsConfigDict(case_sensitive=False)


settings = Settings()
