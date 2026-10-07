from datetime import datetime
from zoneinfo import ZoneInfo
from app.models import AccountState, Side, Signal
from app.risk import assess_signal
from app.settings import Settings


def test_max_concurrent_positions_blocks():
    cfg = Settings(database_url='postgresql://x:x@localhost/x')
    signal = Signal(symbol='BTCUSDT', side=Side.LONG, confidence=0.9,
                    entry=100, stop=98, target=104, volatility_pct=2)
    account = AccountState(equity=100, current_open_positions=2)
    now = datetime(2026, 10, 7, 10, 0, tzinfo=ZoneInfo('Europe/Istanbul'))
    out = assess_signal(signal, account, cfg, now)
    assert not out.approved
    assert out.reason == 'MAX_CONCURRENT_POSITIONS'
