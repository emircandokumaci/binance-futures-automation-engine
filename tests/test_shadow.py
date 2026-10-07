from app.shadow import Candle, TrendBreakoutShadowV1
from app.models import Side


def make_bars(start, step, n=60, breakout=False, down=False):
    bars=[]
    for i in range(n):
        c = start + (-step*i if down else step*i)
        bars.append(Candle(i*1000,c-0.2,c+0.5,c-0.5,c,100.0,i*1000+999))
    if breakout:
        if down:
            bars[-1].close = min(x.low for x in bars[-21:-1]) - 1
            bars[-1].low = bars[-1].close - 0.5
        else:
            bars[-1].close = max(x.high for x in bars[-21:-1]) + 1
            bars[-1].high = bars[-1].close + 0.5
        bars[-1].volume = 200.0
    return bars


def test_long_breakout_signal():
    s=TrendBreakoutShadowV1()
    b15=make_bars(100,0.2,60,breakout=True)
    b1=make_bars(100,0.3,60)
    b4=make_bars(100,0.5,60)
    out=s.evaluate('BTCUSDT',b15,b1,b4)
    assert out is not None
    assert out.side == Side.LONG
    assert out.stop < out.entry < out.target


def test_no_breakout_no_signal():
    s=TrendBreakoutShadowV1()
    bars=make_bars(100,0.2,60,breakout=False)
    assert s.evaluate('BTCUSDT',bars,bars,bars) is None
