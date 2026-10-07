from __future__ import annotations

import asyncio
from dataclasses import dataclass, asdict

from .binance_public import BinancePublicClient
from .indicators import ema
from .models import Side, Signal


@dataclass
class ReferenceRegime:
    btc: str
    eth: str
    combined: str


@dataclass
class OpportunityAssessment:
    approved: bool
    score: float
    reason: str
    oi_change_pct: float | None
    funding_rate: float | None
    taker_ratio: float | None
    global_long_short_ratio: float | None
    book_imbalance: float | None
    spread_bps: float | None
    mark_index_basis_bps: float | None
    regime: str

    def to_dict(self) -> dict:
        return asdict(self)


def _regime_from_klines(rows: list[list]) -> str:
    closes = [float(x[4]) for x in rows[:-1]] if len(rows) > 1 else []
    if len(closes) < 55:
        return 'UNKNOWN'
    e20, e50 = ema(closes, 20), ema(closes, 50)
    last = closes[-1]
    if last > e20 > e50:
        return 'BULL'
    if last < e20 < e50:
        return 'BEAR'
    return 'MIXED'


class MarketContextEngine:
    def __init__(self, market: BinancePublicClient) -> None:
        self.market = market

    async def reference_regime(self) -> ReferenceRegime:
        btc1, btc4, eth1, eth4 = await asyncio.gather(
            self.market.klines('BTCUSDT', '1h', 99), self.market.klines('BTCUSDT', '4h', 99),
            self.market.klines('ETHUSDT', '1h', 99), self.market.klines('ETHUSDT', '4h', 99),
        )
        def pair(a,b):
            ra, rb = _regime_from_klines(a), _regime_from_klines(b)
            return ra if ra == rb else 'MIXED'
        btc, eth = pair(btc1, btc4), pair(eth1, eth4)
        combined = btc if btc == eth else 'MIXED'
        return ReferenceRegime(btc=btc, eth=eth, combined=combined)

    async def collect(self, symbol: str) -> dict:
        oi, depth, premium, oih, gls, taker, funding, ticker = await asyncio.gather(
            self.market.open_interest(symbol),
            self.market.depth(symbol, 20),
            self.market.premium_index(symbol),
            self.market.open_interest_history(symbol, '5m', 48),
            self.market.global_long_short_ratio(symbol, '5m', 48),
            self.market.taker_long_short_ratio(symbol, '5m', 48),
            self.market.funding_history(symbol, 10),
            self.market.ticker_24h_symbol(symbol),
        )
        return {'open_interest':oi,'depth':depth,'premium':premium,'oi_history':oih,'global_ls':gls,'taker':taker,'funding':funding,'ticker':ticker}

    def assess(self, signal: Signal, data: dict, regime: ReferenceRegime) -> OpportunityAssessment:
        score = 60.0  # base setup already passed trend+breakout+volume gate
        side = signal.side
        oih = data.get('oi_history') or []
        oi_change = None
        if len(oih) >= 2:
            a=float(oih[0].get('sumOpenInterestValue') or oih[0].get('sumOpenInterest') or 0)
            b=float(oih[-1].get('sumOpenInterestValue') or oih[-1].get('sumOpenInterest') or 0)
            if a > 0:
                oi_change=(b-a)/a*100
                score += 6 if oi_change > 1 else (-4 if oi_change < -2 else 0)

        premium=data.get('premium') or {}
        funding_rate=float(premium.get('lastFundingRate') or 0)
        mark=float(premium.get('markPrice') or 0)
        index=float(premium.get('indexPrice') or 0)
        basis_bps=((mark-index)/index*10000) if index else None
        if side == Side.LONG and funding_rate > 0.001:
            score -= 8
        elif side == Side.SHORT and funding_rate < -0.001:
            score -= 8
        elif abs(funding_rate) < 0.0005:
            score += 3

        taker_rows=data.get('taker') or []
        taker_ratio=float(taker_rows[-1].get('buySellRatio')) if taker_rows else None
        if taker_ratio is not None:
            if side == Side.LONG:
                score += 8 if taker_ratio >= 1.08 else (-6 if taker_ratio <= 0.92 else 0)
            else:
                score += 8 if taker_ratio <= 0.92 else (-6 if taker_ratio >= 1.08 else 0)

        gls_rows=data.get('global_ls') or []
        gls=float(gls_rows[-1].get('longShortRatio')) if gls_rows else None
        if gls is not None:
            if side == Side.LONG and gls > 2.5: score -= 7
            if side == Side.SHORT and gls < 0.4: score -= 7

        depth=data.get('depth') or {}
        bids=depth.get('bids') or []
        asks=depth.get('asks') or []
        bid_notional=sum(float(p)*float(q) for p,q in bids)
        ask_notional=sum(float(p)*float(q) for p,q in asks)
        denom=bid_notional+ask_notional
        imbalance=bid_notional/denom if denom else None
        spread_bps=None
        if bids and asks:
            bid=float(bids[0][0]); ask=float(asks[0][0]); mid=(bid+ask)/2
            spread_bps=(ask-bid)/mid*10000 if mid else None
            if spread_bps is not None and spread_bps > 8: score -= 10
        if imbalance is not None:
            if side == Side.LONG and imbalance >= .55: score += 4
            if side == Side.SHORT and imbalance <= .45: score += 4

        ref=regime.combined
        if signal.symbol not in {'BTCUSDT','ETHUSDT'}:
            if side == Side.LONG and ref == 'BEAR': score -= 15
            elif side == Side.SHORT and ref == 'BULL': score -= 15
            elif (side == Side.LONG and ref == 'BULL') or (side == Side.SHORT and ref == 'BEAR'): score += 8

        score=max(0.0,min(100.0,score))
        approved = score >= 72 and (spread_bps is None or spread_bps <= 8)
        reason = 'OPPORTUNITY_APPROVED' if approved else 'OPPORTUNITY_REJECTED'
        return OpportunityAssessment(approved,score,reason,oi_change,funding_rate,taker_ratio,gls,imbalance,spread_bps,basis_bps,ref)
