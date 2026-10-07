from app.research_backtest import aggregate_bars, walk_forward_metrics, BacktestTrade
from app.shadow import Candle


def test_aggregate_four_15m_to_1h():
    bars=[]
    for i in range(4):
        bars.append(Candle(i*900000,100+i,102+i,99+i,101+i,10, (i+1)*900000-1))
    out=aggregate_bars(bars,3600000,4)
    assert len(out)==1
    assert out[0].open==100
    assert out[0].close==104
    assert out[0].volume==40


def test_walk_forward_requires_sample():
    t=BacktestTrade(1,2,'LONG',100,99,102.5,'TP_FIRST',2.4,2.5,0.2,3)
    r=walk_forward_metrics([t])
    assert r['status']=='INSUFFICIENT_DATA'
