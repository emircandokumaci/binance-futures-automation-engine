from __future__ import annotations


def ema(values: list[float], period: int) -> float:
    if len(values) < period:
        raise ValueError('not enough values for EMA')
    alpha = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    if not (len(highs) == len(lows) == len(closes)) or len(closes) < period + 1:
        raise ValueError('not enough values for ATR')
    trs: list[float] = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = ((period - 1) * value + tr) / period
    return value


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError('empty values')
    return sum(values) / len(values)
