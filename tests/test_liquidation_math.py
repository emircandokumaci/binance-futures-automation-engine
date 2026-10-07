from app.liquidation import NotionalBracket, estimate_isolated_liquidation_price, liquidation_guard


def test_long_liquidation_is_beyond_stop_at_5x():
    b = NotionalBracket(0, 50000, 0.004, 0, initial_leverage=125)
    liq = estimate_isolated_liquidation_price('LONG', 100, 1, 5, b)
    assert liq < 90
    g = liquidation_guard('LONG', 100, 96, liq, 7.5, 2.5)
    assert g['approved'] is True


def test_high_leverage_can_fail_buffer():
    b = NotionalBracket(0, 50000, 0.004, 0, initial_leverage=125)
    liq = estimate_isolated_liquidation_price('LONG', 100, 1, 20, b)
    g = liquidation_guard('LONG', 100, 98, liq, 7.5, 2.5)
    assert g['approved'] is False
