from app.account import drawdown_pct, unrealized_pnl
from app.models import Side


def test_unrealized_pnl_long_short():
    assert unrealized_pnl(Side.LONG, 2.0, 100.0, 105.0) == 10.0
    assert unrealized_pnl(Side.SHORT, 2.0, 100.0, 95.0) == 10.0


def test_drawdown():
    assert drawdown_pct(90.0, 100.0) == 10.0
    assert drawdown_pct(105.0, 100.0) == 0.0
