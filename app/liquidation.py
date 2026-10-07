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
