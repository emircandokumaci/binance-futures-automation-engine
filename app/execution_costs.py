from __future__ import annotations

from .models import Side


def estimate_top_book_slippage_bps(
    side: Side,
    notional: float,
    bid: float | None,
    bid_qty: float | None,
    ask: float | None,
    ask_qty: float | None,
    floor_bps: float = 0.5,
    cap_bps: float = 25.0,
) -> float:
    if not bid or not ask or bid <= 0 or ask <= 0 or ask < bid:
        return min(cap_bps, max(floor_bps, 5.0))
    mid = (bid + ask) / 2.0
    spread_bps = (ask - bid) / mid * 10_000.0
    if side == Side.LONG:
        touch = ask * max(float(ask_qty or 0), 0.0)
    else:
        touch = bid * max(float(bid_qty or 0), 0.0)
    if touch <= 0:
        impact_bps = 5.0
    else:
        participation = max(0.0, notional / touch)
        impact_bps = min(20.0, participation * 5.0)
    return min(cap_bps, max(floor_bps, spread_bps / 2.0 + impact_bps))
