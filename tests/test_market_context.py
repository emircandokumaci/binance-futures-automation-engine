from app.market_context import MarketContextEngine, ReferenceRegime
from app.models import Signal, Side


class DummyMarket:
    pass


def data(taker="1.20", gls="1.10", funding="0.0001", bid_qty="2", ask_qty="1", oi0="100", oi1="103"):
    return {
        "oi_history": [
            {"sumOpenInterestValue": oi0},
            {"sumOpenInterestValue": oi1},
        ],
        "premium": {"lastFundingRate": funding, "markPrice": "100.0", "indexPrice": "99.99"},
        "taker": [{"buySellRatio": taker}],
        "global_ls": [{"longShortRatio": gls}],
        "depth": {"bids": [["99.99", bid_qty]], "asks": [["100.01", ask_qty]]},
        "funding": [],
        "ticker": {},
    }


def signal(side=Side.LONG):
    return Signal(symbol="SOLUSDT", side=side, confidence=.8, entry=100, stop=98 if side == Side.LONG else 102, target=105 if side == Side.LONG else 95, volatility_pct=2, reason="{}")


def test_favorable_long_context_can_pass():
    e=MarketContextEngine(DummyMarket())
    out=e.assess(signal(), data(), ReferenceRegime("BULL","BULL","BULL"))
    assert out.score >= 72
    assert out.approved is True


def test_bear_regime_penalizes_alt_long():
    e=MarketContextEngine(DummyMarket())
    out=e.assess(signal(), data(taker="1.00", bid_qty="1", ask_qty="1"), ReferenceRegime("BEAR","BEAR","BEAR"))
    assert out.approved is False


def test_extreme_long_crowding_is_penalized():
    e=MarketContextEngine(DummyMarket())
    normal=e.assess(signal(), data(gls="1.1"), ReferenceRegime("MIXED","MIXED","MIXED"))
    crowded=e.assess(signal(), data(gls="3.2"), ReferenceRegime("MIXED","MIXED","MIXED"))
    assert crowded.score < normal.score
