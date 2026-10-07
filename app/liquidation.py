from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class NotionalBracket:
    floor: float
    cap: float
    maint_margin_ratio: float
    cum: float
    initial_leverage: int | None = None
    min_leverage: int | None = None
    max_leverage: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class LiquidationBracketStore:
    """Readiness/metadata store only. No live liquidation-price formula is trusted yet."""

    def __init__(self) -> None:
        self._brackets: dict[str, list[NotionalBracket]] = {}
        self.source = 'none'

    def load_signed_snapshot(self, rows: list[dict]) -> None:
        parsed: dict[str, list[NotionalBracket]] = {}
        for item in rows:
            symbol = str(item.get('symbol') or '').upper()
            if not symbol:
                continue
            out: list[NotionalBracket] = []
            for b in item.get('brackets') or []:
                out.append(NotionalBracket(
                    floor=float(b.get('notionalFloor', 0)),
                    cap=float(b.get('notionalCap', 0)),
                    maint_margin_ratio=float(b.get('maintMarginRatio', 0)),
                    cum=float(b.get('cum', 0)),
                    initial_leverage=int(b['initialLeverage']) if b.get('initialLeverage') is not None else None,
                ))
            if out:
                parsed[symbol] = sorted(out, key=lambda x: x.floor)
        self._brackets.update(parsed)
        if parsed:
            self.source = 'signed_snapshot'

    def apply_contract_info_event(self, data: dict) -> None:
        symbol = str(data.get('s') or data.get('symbol') or '').upper()
        bks = data.get('bks') or []
        if not symbol or not bks:
            return
        out: list[NotionalBracket] = []
        for b in bks:
            out.append(NotionalBracket(
                floor=float(b.get('bnf', 0)),
                cap=float(b.get('bnc', 0)),
                maint_margin_ratio=float(b.get('mmr', 0)),
                cum=float(b.get('cf', 0)),
                min_leverage=int(b['mi']) if b.get('mi') is not None else None,
                max_leverage=int(b['ma']) if b.get('ma') is not None else None,
            ))
        self._brackets[symbol] = sorted(out, key=lambda x: x.floor)
        self.source = 'signed_snapshot+contract_updates' if self.source.startswith('signed_snapshot') else 'contract_updates_only'

    def ready_for(self, symbol: str) -> bool:
        return bool(self._brackets.get(symbol.upper()))

    def select(self, symbol: str, notional: float) -> NotionalBracket | None:
        rows = self._brackets.get(symbol.upper()) or []
        for b in rows:
            if notional >= b.floor and (b.cap <= 0 or notional < b.cap):
                return b
        return rows[-1] if rows and notional >= rows[-1].floor else None

    def status(self, required_symbols: list[str]) -> dict:
        required = [s.upper() for s in required_symbols]
        missing = [s for s in required if not self.ready_for(s)]
        return {
            'ready': len(required) > 0 and not missing,
            'source': self.source,
            'covered': len(required) - len(missing),
            'required': len(required),
            'missing_symbols': missing,
            'policy': 'FAIL_CLOSED_FOR_LIVE',
        }


def estimate_isolated_liquidation_price(
    side: str,
    entry: float,
    qty: float,
    leverage: int,
    bracket: NotionalBracket,
) -> float:
    """Pre-trade isolated-margin estimate using Binance bracket MMR/cum.

    Exchange-reported liquidationPrice from positionRisk remains the source of truth after fill.
    """
    if entry <= 0 or qty <= 0 or leverage <= 0:
        raise ValueError('invalid liquidation inputs')
    margin = entry * qty / leverage
    mmr = bracket.maint_margin_ratio
    cum = bracket.cum
    side = side.upper()
    if side == 'LONG':
        denom = qty * (1.0 - mmr)
        px = (qty * entry - margin - cum) / denom
    elif side == 'SHORT':
        denom = qty * (1.0 + mmr)
        px = (margin + qty * entry + cum) / denom
    else:
        raise ValueError('side must be LONG or SHORT')
    return max(0.0, px)


def liquidation_guard(
    side: str,
    entry: float,
    stop: float,
    liq: float,
    min_buffer_pct: float,
    min_stop_multiple: float,
) -> dict:
    side = side.upper()
    if entry <= 0 or liq <= 0:
        return {'approved': False, 'reason': 'INVALID_LIQUIDATION_PRICE'}
    liq_distance_pct = abs(entry - liq) / entry * 100.0
    stop_distance = abs(entry - stop)
    liq_distance = abs(entry - liq)
    multiple = liq_distance / stop_distance if stop_distance > 0 else 0.0
    correct_side = liq < stop < entry if side == 'LONG' else liq > stop > entry
    if not correct_side:
        return {'approved': False, 'reason': 'LIQUIDATION_NOT_BEYOND_STOP', 'liquidation_price': liq,
                'liquidation_distance_pct': liq_distance_pct, 'liquidation_stop_multiple': multiple}
    if liq_distance_pct < min_buffer_pct:
        return {'approved': False, 'reason': 'LIQUIDATION_BUFFER_TOO_SMALL', 'liquidation_price': liq,
                'liquidation_distance_pct': liq_distance_pct, 'liquidation_stop_multiple': multiple}
    if multiple < min_stop_multiple:
        return {'approved': False, 'reason': 'LIQUIDATION_TOO_CLOSE_TO_STOP', 'liquidation_price': liq,
                'liquidation_distance_pct': liq_distance_pct, 'liquidation_stop_multiple': multiple}
    return {'approved': True, 'reason': 'LIQUIDATION_BUFFER_OK', 'liquidation_price': liq,
            'liquidation_distance_pct': liq_distance_pct, 'liquidation_stop_multiple': multiple}
