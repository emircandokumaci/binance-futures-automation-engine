from app.indicators import atr, ema


def test_ema_on_constant_series():
    assert ema([10.0] * 60, 20) == 10.0


def test_atr_positive():
    closes = [100 + i * 0.1 for i in range(20)]
    highs = [x + 1 for x in closes]
    lows = [x - 1 for x in closes]
    assert atr(highs, lows, closes, 14) > 0
