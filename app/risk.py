import math
from datetime import datetime

from .models import AccountState, RiskAssessment, Side, Signal
from .schedule import no_new_trades_window
from .settings import Settings


FRICTION_RATE = 0.001
MIN_REWARD_RISK = 2.0


def _valid_levels(signal: Signal) -> bool:
    if signal.side == Side.LONG:
        return signal.stop < signal.entry < signal.target
    return signal.target < signal.entry < signal.stop


def _reward_risk(signal: Signal) -> float:
    risk = abs(signal.entry - signal.stop)
    reward = abs(signal.target - signal.entry)
    return reward / risk if risk > 0 else 0.0


def _select_leverage(signal: Signal, account: AccountState, cfg: Settings) -> int:
    lev = 3
    rr = _reward_risk(signal)
    if signal.volatility_pct > 6:
        lev = 2
    elif cfg.confidence_leverage_scaling_enabled and signal.confidence >= 0.80 and signal.volatility_pct <= 3.5 and rr >= 2.0:
        lev = min(5, cfg.normal_max_leverage)
    if (
        cfg.confidence_leverage_scaling_enabled
        and signal.confidence >= 0.92
        and signal.volatility_pct <= 2.0
        and rr >= 2.5
        and account.drawdown_pct < 5.0
    ):
        lev = min(5, cfg.normal_max_leverage)
    if account.drawdown_pct >= 10.0:
        lev = min(lev, 3)
    return max(1, min(lev, cfg.absolute_max_leverage))


def assess_signal(
    signal: Signal,
    account: AccountState,
    cfg: Settings,
    now: datetime | None = None,
) -> RiskAssessment:
    blocked, schedule_reason = no_new_trades_window(
        now, cfg.tz, cfg.no_new_trades_start, cfg.no_new_trades_end
    )
    if blocked:
        return RiskAssessment(approved=False, reason=schedule_reason)
    if not _valid_levels(signal):
        return RiskAssessment(approved=False, reason="INVALID_ENTRY_STOP_TARGET")
    if account.daily_pnl_pct <= -cfg.daily_loss_limit_pct:
        return RiskAssessment(approved=False, reason="DAILY_LOSS_LIMIT")
    if account.drawdown_pct >= cfg.hard_drawdown_pct:
        return RiskAssessment(approved=False, reason="HARD_DRAWDOWN_LIMIT")

    if account.current_open_positions >= cfg.max_concurrent_positions:
        return RiskAssessment(approved=False, reason="MAX_CONCURRENT_POSITIONS")

    rr = _reward_risk(signal)
    if rr < MIN_REWARD_RISK:
        return RiskAssessment(approved=False, reason="REWARD_RISK_TOO_LOW", reward_risk=rr)

    stop_pct = abs(signal.entry - signal.stop) / signal.entry
    if stop_pct <= 0:
        return RiskAssessment(approved=False, reason="INVALID_STOP_DISTANCE")

    requested_risk_pct = cfg.default_risk_pct
    if cfg.confidence_risk_scaling_enabled:
        if signal.confidence >= 0.88 and rr >= 2.0 and account.drawdown_pct < 5:
            requested_risk_pct = min(1.5, cfg.max_risk_pct)
        if signal.confidence >= 0.94 and rr >= 2.5 and signal.volatility_pct <= 2.5:
            requested_risk_pct = min(2.0, cfg.max_risk_pct)

    risk_usdt = account.equity * requested_risk_pct / 100.0
    notional = risk_usdt / (stop_pct + FRICTION_RATE)
    leverage = _select_leverage(signal, account, cfg)

    max_margin = account.equity * cfg.max_margin_utilization
    max_notional_by_margin = max_margin * leverage
    notional = min(notional, max_notional_by_margin)

    projected_exposure = account.current_gross_exposure + notional
    projected_gross_leverage = projected_exposure / account.equity
    if projected_gross_leverage > cfg.max_portfolio_gross_leverage:
        return RiskAssessment(
            approved=False,
            reason="PORTFOLIO_GROSS_LEVERAGE_LIMIT",
            risk_pct=requested_risk_pct,
            risk_usdt=risk_usdt,
            stop_distance_pct=stop_pct * 100,
            reward_risk=rr,
            notional=notional,
            leverage=leverage,
            margin_required=notional / leverage,
            projected_gross_leverage=projected_gross_leverage,
        )

    margin_required = notional / leverage
    if account.current_margin_used + margin_required > account.equity * cfg.max_margin_utilization:
        return RiskAssessment(approved=False, reason="MARGIN_UTILIZATION_LIMIT")

    actual_risk = notional * (stop_pct + FRICTION_RATE)
    actual_risk_pct = actual_risk / account.equity * 100.0
    return RiskAssessment(
        approved=True,
        reason="RISK_APPROVED_PAPER",
        risk_pct=actual_risk_pct,
        risk_usdt=actual_risk,
        stop_distance_pct=stop_pct * 100,
        reward_risk=rr,
        notional=notional,
        leverage=leverage,
        margin_required=margin_required,
        projected_gross_leverage=projected_gross_leverage,
    )
