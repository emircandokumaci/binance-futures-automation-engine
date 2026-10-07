from .settings import Settings


def enforce_phase_one_safety(cfg: Settings) -> None:
    """Hard guard: phase one cannot submit real Binance orders."""
    if cfg.trading_mode.lower() != "paper":
        raise RuntimeError("Phase 1 is PAPER_ONLY; trading_mode must remain 'paper'.")
    if cfg.live_trading_enabled:
        raise RuntimeError("Phase 1 is PAPER_ONLY; LIVE_TRADING_ENABLED must be false.")
