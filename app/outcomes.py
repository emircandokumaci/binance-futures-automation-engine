from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

from .binance_public import BinancePublicClient
from .models import Side


@dataclass
class PathOutcome:
    status: str
    mfe_pct: float
    mae_pct: float
    mfe_r: float
    mae_r: float
    bars_observed: int

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_1m_path(side: Side, entry: float, stop: float, target: float, rows: list[list]) -> PathOutcome:
    risk_abs = abs(entry - stop)
    if risk_abs <= 0:
        raise ValueError('invalid stop distance')
    mfe_abs = 0.0
    mae_abs = 0.0
    status = 'PENDING'
    observed = 0
    for row in rows:
        high=float(row[2]); low=float(row[3]); observed += 1
        if side == Side.LONG:
            favorable=max(0.0, high-entry)
            adverse=max(0.0, entry-low)
            tp_hit=high >= target
            sl_hit=low <= stop
        else:
            favorable=max(0.0, entry-low)
            adverse=max(0.0, high-entry)
            tp_hit=low <= target
            sl_hit=high >= stop
        mfe_abs=max(mfe_abs, favorable)
        mae_abs=max(mae_abs, adverse)
        if tp_hit and sl_hit:
            status='AMBIGUOUS'
            break
        if sl_hit:
            status='SL_FIRST'
            break
        if tp_hit:
            status='TP_FIRST'
            break
    return PathOutcome(
        status=status,
        mfe_pct=mfe_abs/entry*100.0,
        mae_pct=mae_abs/entry*100.0,
        mfe_r=mfe_abs/risk_abs,
        mae_r=mae_abs/risk_abs,
        bars_observed=observed,
    )


class ShadowOutcomeTracker:
    def __init__(self, database_url: str, market: BinancePublicClient, horizon_hours: int = 24) -> None:
        self.database_url=database_url
        self.market=market
        self.horizon_hours=horizon_hours

    def pending(self, limit: int = 30) -> list[dict]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows=conn.execute(
                """SELECT * FROM shadow_candidates
                   WHERE outcome_status='PENDING'
                   ORDER BY ts ASC LIMIT %s""", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    async def update_candidate(self, row: dict, now_ms: int) -> dict:
        # Entry is generated from a closed 15m bar; start measuring at the next millisecond.
        start_dt=row['bar_open_time'] + timedelta(minutes=15)
        start_ms=int(start_dt.timestamp()*1000)
        horizon_ms=int((start_dt + timedelta(hours=self.horizon_hours)).timestamp()*1000)
        end_ms=min(now_ms, horizon_ms)
        if end_ms <= start_ms:
            return {'id': row['id'], 'status': 'PENDING'}
        raw=await self.market.klines_range(row['symbol'],'1m',start_ms,end_ms,1500)
        # Ignore a still-open final candle.
        closed=[x for x in raw if int(x[6]) < now_ms]
        result=evaluate_1m_path(Side(row['side']),float(row['entry']),float(row['stop']),float(row['target']),closed)
        status=result.status
        if status == 'PENDING' and now_ms >= horizon_ms:
            status='TIMEOUT'
        resolved_at=datetime.now(timezone.utc) if status != 'PENDING' else None
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            conn.execute(
                """UPDATE shadow_candidates
                   SET outcome_status=%s,mfe_pct=%s,mae_pct=%s,mfe_r=%s,mae_r=%s,bars_observed=%s,resolved_at=%s
                   WHERE id=%s""",
                (status,result.mfe_pct,result.mae_pct,result.mfe_r,result.mae_r,result.bars_observed,resolved_at,row['id'])
            )
        out=result.to_dict(); out['status']=status; out['id']=row['id']; out['symbol']=row['symbol']; out['side']=row['side']
        return out

    async def run_once(self, limit: int = 30) -> list[dict]:
        rows=self.pending(limit)
        if not rows:
            return []
        now_ms=await self.market.server_time()
        out=[]
        for row in rows:
            try:
                out.append(await self.update_candidate(row,now_ms))
            except Exception as exc:
                out.append({'id':row['id'],'symbol':row['symbol'],'error':f'{type(exc).__name__}: {exc}'})
        return out


def outcome_stats(database_url: str) -> dict:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        summary=conn.execute("""
            SELECT opportunity_approved,outcome_status,count(*) AS n,
                   avg(mfe_r) AS avg_mfe_r,avg(mae_r) AS avg_mae_r
            FROM shadow_candidates GROUP BY opportunity_approved,outcome_status
            ORDER BY opportunity_approved DESC,outcome_status
        """).fetchall()
        return {'groups':[dict(r) for r in summary]}
