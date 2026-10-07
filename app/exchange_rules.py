from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_UP

from .models import RiskAssessment, Signal


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    max_qty: Decimal
    min_notional: Decimal
    trigger_protect: float
    liquidation_fee: float
    market_take_bound: float


def _d(v, default='0') -> Decimal:
    return Decimal(str(v if v is not None else default))


def parse_symbol_rules(exchange_info: dict) -> dict[str, SymbolRules]:
    out: dict[str, SymbolRules] = {}
    for row in exchange_info.get('symbols', []):
        symbol = str(row.get('symbol') or '').upper()
        if not symbol:
            continue
        filters = {f.get('filterType'): f for f in row.get('filters', [])}
        pf = filters.get('PRICE_FILTER', {})
        lot = filters.get('MARKET_LOT_SIZE') or filters.get('LOT_SIZE') or {}
        min_notional = filters.get('MIN_NOTIONAL', {}).get('notional')
        if min_notional is None:
            min_notional = filters.get('NOTIONAL', {}).get('minNotional', 0)
        out[symbol] = SymbolRules(
            symbol=symbol,
            tick_size=_d(pf.get('tickSize'), '0.00000001'),
            step_size=_d(lot.get('stepSize'), '0.00000001'),
            min_qty=_d(lot.get('minQty'), '0'),
            max_qty=_d(lot.get('maxQty'), '1e50'),
            min_notional=_d(min_notional, '0'),
            trigger_protect=float(row.get('triggerProtect') or 0),
            liquidation_fee=float(row.get('liquidationFee') or 0),
            market_take_bound=float(row.get('marketTakeBound') or 0),
        )
    return out


def floor_to_step(value: float, step: Decimal) -> float:
    d = Decimal(str(value))
    if step <= 0:
        return float(d)
    return float((d / step).to_integral_value(rounding=ROUND_DOWN) * step)


def round_price(value: float, tick: Decimal, upward: bool = False) -> float:
    d = Decimal(str(value))
    if tick <= 0:
        return float(d)
    mode = ROUND_UP if upward else ROUND_DOWN
    return float((d / tick).to_integral_value(rounding=mode) * tick)


def constrain_risk_to_exchange(signal: Signal, risk: RiskAssessment, mark: float, rules: SymbolRules) -> RiskAssessment:
    if not risk.approved:
        return risk
    qty = floor_to_step(risk.notional / mark, rules.step_size)
    if qty <= 0 or Decimal(str(qty)) < rules.min_qty:
        return risk.model_copy(update={'approved': False, 'reason': 'EXCHANGE_MIN_QTY'})
    if Decimal(str(qty)) > rules.max_qty:
        qty = float(rules.max_qty)
    notional = qty * mark
    if Decimal(str(notional)) < rules.min_notional:
        return risk.model_copy(update={'approved': False, 'reason': 'EXCHANGE_MIN_NOTIONAL'})
    stop_pct = abs(signal.entry - signal.stop) / signal.entry
    actual_risk = notional * (stop_pct + 0.001)
    return risk.model_copy(update={
        'notional': notional,
        'margin_required': notional / max(risk.leverage, 1),
        'risk_usdt': actual_risk,
        'risk_pct': actual_risk / max(1e-9, (risk.risk_usdt / max(risk.risk_pct, 1e-9) * 100.0)) * 100.0 if risk.risk_pct > 0 else risk.risk_pct,
    })
