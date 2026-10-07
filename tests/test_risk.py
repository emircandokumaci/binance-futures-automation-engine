from datetime import datetime
from zoneinfo import ZoneInfo

from app.models import AccountState, Side, Signal
from app.risk import assess_signal
from app.settings import Settings


def cfg():
    return Settings(database_url='postgresql://x:x@localhost/x')


def test_position_sizing_and_controlled_aggression():
    signal = Signal(symbol='BTCUSDT', side=Side.LONG, confidence=0.95,
                    entry=100.0, stop=98.0, target=105.0,
                    volatility_pct=1.5, reason='test')
    account = AccountState(equity=100.0)
    dt = datetime(2026, 10, 7, 10, 0, tzinfo=ZoneInfo('Europe/Istanbul'))
    out = assess_signal(signal, account, cfg(), dt)
    assert out.approved is True
    assert 0 < out.risk_usdt <= 2.0
    assert out.leverage <= 10
    assert out.margin_required <= 50.0
    assert out.reward_risk == 2.5


def test_daily_loss_blocks_new_trade():
    signal = Signal(symbol='ETHUSDT', side=Side.SHORT, confidence=0.9,
                    entry=100.0, stop=103.0, target=94.0,
                    volatility_pct=2.0, reason='test')
    account = AccountState(equity=100.0, daily_pnl_pct=-10.0)
    dt = datetime(2026, 10, 7, 10, 0, tzinfo=ZoneInfo('Europe/Istanbul'))
    out = assess_signal(signal, account, cfg(), dt)
    assert out.approved is False
    assert out.reason == 'DAILY_LOSS_LIMIT'
