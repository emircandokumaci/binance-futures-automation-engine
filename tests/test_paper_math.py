from app.models import Side
from app.paper import apply_slippage, gross_pnl


def test_slippage_is_adverse():
    assert apply_slippage(100, Side.LONG, True, 10) > 100
    assert apply_slippage(100, Side.LONG, False, 10) < 100
    assert apply_slippage(100, Side.SHORT, True, 10) < 100
    assert apply_slippage(100, Side.SHORT, False, 10) > 100


def test_long_and_short_profit_math():
    assert gross_pnl(Side.LONG, 2, 100, 105) == 10
    assert gross_pnl(Side.SHORT, 2, 100, 95) == 10
