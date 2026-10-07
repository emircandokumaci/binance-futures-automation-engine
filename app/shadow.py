from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from .binance_public import BinancePublicClient
from .indicators import atr, ema, mean
from .models import Side, Signal
from .market_context import MarketContextEngine


@dataclass
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int


def parse_closed_klines(raw: list[list], now_ms: int) -> list[Candle]:
    out: list[Candle] = []
    for k in raw:
        if int(k[6]) >= now_ms:
            continue
        out.append(Candle(
            open_time=int(k[0]),
            open=float(k[1]),
            high=float(k[2]),
            low=float(k[3]),
            close=float(k[4]),
            volume=float(k[5]),
            close_time=int(k[6]),
        ))
    return out


class TrendBreakoutShadowV1:
    name = 'trend_breakout_shadow'
    version = '0.2.0'

    def evaluate(self, symbol: str, bars15: list[Candle], bars1h: list[Candle], bars4h: list[Candle]) -> Signal | None:
        if min(len(bars15), len(bars1h), len(bars4h)) < 55:
            return None
        closes4 = [x.close for x in bars4h]
        closes1 = [x.close for x in bars1h]
        closes15 = [x.close for x in bars15]
        highs15 = [x.high for x in bars15]
        lows15 = [x.low for x in bars15]
        vols15 = [x.volume for x in bars15]

        ema20_4, ema50_4 = ema(closes4, 20), ema(closes4, 50)
        ema20_1, ema50_1 = ema(closes1, 20), ema(closes1, 50)
        last = bars15[-1]
        prior = bars15[-21:-1]
        prior_high = max(x.high for x in prior)
        prior_low = min(x.low for x in prior)
        avg_vol = mean(vols15[-21:-1])
        volume_ratio = last.volume / avg_vol if avg_vol > 0 else 0.0
        atr14 = atr(highs15, lows15, closes15, 14)
        atr_pct = atr14 / last.close * 100.0 if last.close > 0 else 0.0

        bullish_regime = closes4[-1] > ema20_4 > ema50_4 and closes1[-1] > ema20_1 > ema50_1
        bearish_regime = closes4[-1] < ema20_4 < ema50_4 and closes1[-1] < ema20_1 < ema50_1
        long_breakout = last.close > prior_high
        short_breakout = last.close < prior_low
        volume_ok = volume_ratio >= 1.15

        side: Side | None = None
        if bullish_regime and long_breakout and volume_ok:
            side = Side.LONG
        elif bearish_regime and short_breakout and volume_ok:
            side = Side.SHORT
        if side is None:
            return None

        stop_distance = max(1.5 * atr14, last.close * 0.004)
        if side == Side.LONG:
            stop = last.close - stop_distance
            target = last.close + 2.5 * stop_distance
        else:
            stop = last.close + stop_distance
            target = last.close - 2.5 * stop_distance

        trend_strength_4h = abs(ema20_4 - ema50_4) / last.close * 100.0
        trend_strength_1h = abs(ema20_1 - ema50_1) / last.close * 100.0
        confidence = 0.72
        confidence += min(0.08, trend_strength_4h / 10.0)
        confidence += min(0.07, trend_strength_1h / 10.0)
        confidence += min(0.08, max(0.0, volume_ratio - 1.15) * 0.08)
        if 0.5 <= atr_pct <= 4.0:
            confidence += 0.05
        confidence = min(confidence, 0.98)

        reason = json.dumps({
            'strategy': self.name,
            'version': self.version,
            'bar_open_time': last.open_time,
            'ema20_4h': ema20_4,
            'ema50_4h': ema50_4,
            'ema20_1h': ema20_1,
            'ema50_1h': ema50_1,
            'breakout_level': prior_high if side == Side.LONG else prior_low,
            'volume_ratio': volume_ratio,
            'atr14': atr14,
            'atr_pct': atr_pct,
        }, separators=(',', ':'))
        return Signal(
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=last.close,
            stop=stop,
            target=target,
            volatility_pct=atr_pct,
            reason=reason,
        )


class ShadowScanner:
    def __init__(self, database_url: str, market: BinancePublicClient, concurrency: int = 5) -> None:
        self.database_url = database_url
        self.market = market
        self.strategy = TrendBreakoutShadowV1()
        self.semaphore = asyncio.Semaphore(concurrency)
        self.context = MarketContextEngine(market)

    async def scan_symbol(self, symbol: str, now_ms: int) -> Signal | None:
        async with self.semaphore:
            raw15, raw1h, raw4h = await asyncio.gather(
                self.market.klines(symbol, '15m', 99),
                self.market.klines(symbol, '1h', 99),
                self.market.klines(symbol, '4h', 99),
            )
        bars15 = parse_closed_klines(raw15, now_ms)
        bars1h = parse_closed_klines(raw1h, now_ms)
        bars4h = parse_closed_klines(raw4h, now_ms)
        return self.strategy.evaluate(symbol, bars15, bars1h, bars4h)

    async def scan(self, symbols: list[str]) -> list[Signal]:
        now_ms = await self.market.server_time()
        reference_regime = await self.context.reference_regime()
        results = await asyncio.gather(
            *(self.scan_symbol(symbol, now_ms) for symbol in symbols),
            return_exceptions=True,
        )
        signals: list[Signal] = []
        for symbol, result in zip(symbols, results):
            if isinstance(result, Exception):
                self._log_error(symbol, result)
                continue
            if result is not None:
                try:
                    ctx = await self.context.collect(symbol)
                    opp = self.context.assess(result, ctx, reference_regime)
                    meta = json.loads(result.reason)
                    meta['opportunity_v2'] = opp.to_dict()
                    result = result.model_copy(update={'confidence': opp.score / 100.0, 'reason': json.dumps(meta, separators=(',', ':'))})
                    if not opp.approved:
                        with psycopg.connect(self.database_url, autocommit=True) as conn:
                            conn.execute(
                                "INSERT INTO system_events(event_type,payload) VALUES('SHADOW_OPPORTUNITY_REJECTED',%s::jsonb)",
                                (json.dumps({'symbol': symbol, 'side': result.side.value, 'score': opp.score, 'assessment': opp.to_dict()}),),
                            )
                        continue
                except Exception as exc:
                    self._log_error(symbol, exc)
                    continue
                self._persist(result)
                signals.append(result)
        return signals

    def _persist(self, signal: Signal) -> None:
        meta = json.loads(signal.reason)
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            conn.execute(
                """INSERT INTO shadow_signals
                (bar_open_time,strategy_name,strategy_version,symbol,side,confidence,entry,stop,target,volatility_pct,reason)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (strategy_name,strategy_version,symbol,side,bar_open_time) DO NOTHING""",
                (
                    datetime.fromtimestamp(meta['bar_open_time'] / 1000, tz=timezone.utc),
                    self.strategy.name,
                    self.strategy.version,
                    signal.symbol,
                    signal.side.value,
                    signal.confidence,
                    signal.entry,
                    signal.stop,
                    signal.target,
                    signal.volatility_pct,
                    signal.reason,
                ),
            )

    def _log_error(self, symbol: str, exc: Exception) -> None:
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO system_events(event_type,payload) VALUES('SHADOW_SCAN_ERROR',%s::jsonb)",
                (json.dumps({'symbol': symbol, 'error': f'{type(exc).__name__}: {exc}'}),),
            )


def recent_signals(database_url: str, limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            "SELECT * FROM shadow_signals ORDER BY ts DESC LIMIT %s",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
