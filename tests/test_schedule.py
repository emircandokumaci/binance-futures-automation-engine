from datetime import datetime
from zoneinfo import ZoneInfo

from app.schedule import no_new_trades_window


def test_blocks_istanbul_0830():
    dt = datetime(2026, 10, 7, 8, 30, tzinfo=ZoneInfo("Europe/Istanbul"))
    blocked, reason = no_new_trades_window(dt, "Europe/Istanbul", "08:00", "09:00")
    assert blocked is True
    assert reason.startswith("NO_NEW_TRADES")


def test_opens_at_0900():
    dt = datetime(2026, 10, 7, 9, 0, tzinfo=ZoneInfo("Europe/Istanbul"))
    blocked, reason = no_new_trades_window(dt, "Europe/Istanbul", "08:00", "09:00")
    assert blocked is False
    assert reason == "TRADING_WINDOW_OPEN"
