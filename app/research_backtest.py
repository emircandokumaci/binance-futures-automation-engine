from __future__ import annotations

from dataclasses import asdict, dataclass

from .models import Side
from .shadow import Candle, TrendBreakoutShadowV1, parse_closed_klines


@dataclass
class BacktestTrade:
    open_time: int
    close_time: int
    side: str
    entry: float
    stop: float
    target: float
    outcome: str
    r_net: float
    mfe_r: float
    mae_r: float
    bars_held: int


def aggregate_bars(bars: list[Candle], bucket_ms: int, expected_count: int) -> list[Candle]:
    buckets: dict[int, list[Candle]] = {}
    for bar in bars:
        key = (bar.open_time // bucket_ms) * bucket_ms
        buckets.setdefault(key, []).append(bar)
    out: list[Candle] = []
    for key in sorted(buckets):
        rows = sorted(buckets[key], key=lambda x: x.open_time)
        if len(rows) != expected_count:
            continue
        out.append(Candle(
            open_time=key,
            open=rows[0].open,
            high=max(x.high for x in rows),
            low=min(x.low for x in rows),
            close=rows[-1].close,
            volume=sum(x.volume for x in rows),
            close_time=rows[-1].close_time,
        ))
    return out


def _resolve_trade(signal, future: list[Candle], cost_pct: float) -> tuple[str, float, float, float, int, int]:
    risk = abs(signal.entry - signal.stop)
    if risk <= 0:
        return 'INVALID', -1.0, 0.0, 0.0, 0, signal.entry
    best = 0.0
    worst = 0.0
    outcome = 'TIMEOUT'
    exit_price = future[-1].close if future else signal.entry
    held = len(future)
    close_time = future[-1].close_time if future else 0
    for idx, bar in enumerate(future, 1):
        if signal.side == Side.LONG:
            favourable = bar.high - signal.entry
            adverse = signal.entry - bar.low
            stop_hit = bar.low <= signal.stop
            target_hit = bar.high >= signal.target
        else:
            favourable = signal.entry - bar.low
            adverse = bar.high - signal.entry
            stop_hit = bar.high >= signal.stop
            target_hit = bar.low <= signal.target
        best = max(best, favourable)
        worst = max(worst, adverse)
        if stop_hit and target_hit:
            outcome = 'AMBIGUOUS'
            exit_price = signal.stop
            held = idx
            close_time = bar.close_time
            break
        if stop_hit:
            outcome = 'SL_FIRST'
            exit_price = signal.stop
            held = idx
            close_time = bar.close_time
            break
        if target_hit:
            outcome = 'TP_FIRST'
            exit_price = signal.target
            held = idx
            close_time = bar.close_time
            break
    gross_r = ((exit_price - signal.entry) if signal.side == Side.LONG else (signal.entry - exit_price)) / risk
    cost_r = (signal.entry * cost_pct) / risk
    return outcome, gross_r - cost_r, best / risk, worst / risk, held, close_time


def _metrics(trades: list[BacktestTrade]) -> dict:
    if not trades:
        return {'trades': 0, 'expectancy_r': 0.0, 'win_rate': 0.0, 'profit_factor': 0.0, 'max_drawdown_r': 0.0}
    rs=[x.r_net for x in trades]
    pos=sum(x for x in rs if x>0)
    neg=-sum(x for x in rs if x<0)
    equity=peak=0.0
    maxdd=0.0
    for r in rs:
        equity += r
        peak=max(peak,equity)
        maxdd=max(maxdd,peak-equity)
    return {
        'trades':len(trades),
        'wins':sum(1 for x in trades if x.outcome=='TP_FIRST'),
        'losses':sum(1 for x in trades if x.outcome in {'SL_FIRST','AMBIGUOUS'}),
        'timeouts':sum(1 for x in trades if x.outcome=='TIMEOUT'),
        'expectancy_r':round(sum(rs)/len(rs),4),
        'win_rate':round(sum(1 for r in rs if r>0)/len(rs),4),
        'profit_factor':round(pos/neg,4) if neg>0 else (999.0 if pos>0 else 0.0),
        'max_drawdown_r':round(maxdd,4),
        'avg_mfe_r':round(sum(x.mfe_r for x in trades)/len(trades),4),
        'avg_mae_r':round(sum(x.mae_r for x in trades)/len(trades),4),
    }


def walk_forward_metrics(trades: list[BacktestTrade], folds: int = 4) -> dict:
    if len(trades) < folds * 3:
        return {'status':'INSUFFICIENT_DATA','required':folds*3,'observed':len(trades),'folds':[]}
    size=max(1,len(trades)//folds)
    results=[]
    for i in range(folds):
        start=i*size
        end=len(trades) if i==folds-1 else min(len(trades),(i+1)*size)
        part=trades[start:end]
        results.append({'fold':i+1,'start_time':part[0].open_time,'end_time':part[-1].close_time,**_metrics(part)})
    positive=sum(1 for x in results if x['expectancy_r']>0)
    return {'status':'OK','folds':results,'positive_folds_pct':round(positive/len(results)*100,1)}


async def run_base_strategy_backtest(market, symbol: str, limit: int = 1500, horizon_bars: int = 96, cost_pct: float = 0.0012) -> dict:
    limit=max(1000,min(int(limit),1500))
    now_ms=await market.server_time()
    raw=await market.klines(symbol,'15m',limit)
    bars=parse_closed_klines(raw,now_ms)
    bars1=aggregate_bars(bars,60*60*1000,4)
    bars4=aggregate_bars(bars,4*60*60*1000,16)
    strategy=TrendBreakoutShadowV1()
    trades=[]
    next_allowed=0
    for i in range(880, max(880,len(bars)-horizon_bars)):
        if i < next_allowed:
            continue
        current=bars[i]
        h1=[x for x in bars1 if x.close_time <= current.close_time][-99:]
        h4=[x for x in bars4 if x.close_time <= current.close_time][-99:]
        sig=strategy.evaluate(symbol,bars[max(0,i-98):i+1],h1,h4)
        if not sig:
            continue
        future=bars[i+1:i+1+horizon_bars]
        if not future:
            break
        outcome,r,mfe,mae,held,close_time=_resolve_trade(sig,future,cost_pct)
        trades.append(BacktestTrade(sig.reason and current.open_time,close_time,sig.side.value,sig.entry,sig.stop,sig.target,outcome,r,mfe,mae,held))
        next_allowed=i+max(1,held)
    summary=_metrics(trades)
    return {
        'symbol':symbol,
        'strategy':{'name':strategy.name,'version':strategy.version},
        'scope':'BASE_STRATEGY_ONLY_NO_HISTORICAL_OI_FUNDING_ORDERBOOK_REPLAY',
        'bars_15m':len(bars),
        'horizon_bars':horizon_bars,
        'round_trip_cost_pct':cost_pct,
        'summary':summary,
        'walk_forward':walk_forward_metrics(trades),
        'trades':[asdict(x) for x in trades[-100:]],
    }
