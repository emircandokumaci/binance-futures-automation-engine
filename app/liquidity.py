from __future__ import annotations

from datetime import datetime, timezone


def _spread_bps(bid: float, ask: float) -> float:
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return 1e9
    return (ask - bid) / mid * 10_000.0


def select_liquid_universe(
    exchange_info: dict,
    tickers_24h: list[dict],
    book_tickers: list[dict],
    *,
    top_n: int,
    min_quote_volume: float,
    max_spread_bps: float,
    min_listing_age_days: int,
    now_ms: int | None = None,
) -> list[dict]:
    now_ms = now_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
    eligible: dict[str, dict] = {}
    for s in exchange_info.get('symbols', []):
        symbol = str(s.get('symbol') or '')
        if not symbol.isascii() or not symbol.replace('_', '').isalnum():
            continue
        if not (
            s.get('contractType') == 'PERPETUAL'
            and s.get('quoteAsset') == 'USDT'
            and s.get('marginAsset') == 'USDT'
            and s.get('status') == 'TRADING'
        ):
            continue
        onboard = int(s.get('onboardDate') or 0)
        age_days = (now_ms - onboard) / 86_400_000 if onboard > 0 else 10_000
        if age_days < min_listing_age_days:
            continue
        eligible[s['symbol']] = {'symbol': s['symbol'], 'listing_age_days': age_days}

    volumes = {x.get('symbol'): float(x.get('quoteVolume') or 0.0) for x in tickers_24h}
    books = {
        x.get('symbol'): (float(x.get('bidPrice') or 0.0), float(x.get('askPrice') or 0.0))
        for x in book_tickers
    }

    rows: list[dict] = []
    for symbol, meta in eligible.items():
        volume = volumes.get(symbol, 0.0)
        bid, ask = books.get(symbol, (0.0, 0.0))
        if volume < min_quote_volume or bid <= 0 or ask <= 0 or ask < bid:
            continue
        spread = _spread_bps(bid, ask)
        if spread > max_spread_bps:
            continue
        rows.append({
            **meta,
            'quote_volume_24h': volume,
            'bid': bid,
            'ask': ask,
            'spread_bps': spread,
        })

    rows.sort(key=lambda x: x['quote_volume_24h'], reverse=True)
    return rows[:max(1, top_n)]
