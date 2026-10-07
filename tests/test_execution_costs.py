from app.execution_costs import estimate_top_book_slippage_bps
from app.models import Side


def test_slippage_increases_with_size():
    small = estimate_top_book_slippage_bps(Side.LONG, 100, 99.9, 10, 100.1, 10)
    big = estimate_top_book_slippage_bps(Side.LONG, 5000, 99.9, 10, 100.1, 10)
    assert big >= small
    assert big <= 25
