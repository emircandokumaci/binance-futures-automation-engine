from datetime import datetime, time
from zoneinfo import ZoneInfo


def _parse_hhmm(value: str) -> time:
    hour, minute = (int(x) for x in value.split(":", 1))
    return time(hour=hour, minute=minute)


def no_new_trades_window(
    now: datetime | None,
    tz_name: str,
    start_hhmm: str,
    end_hhmm: str,
) -> tuple[bool, str]:
    tz = ZoneInfo(tz_name)
    current = (now or datetime.now(tz)).astimezone(tz)
    start = _parse_hhmm(start_hhmm)
    end = _parse_hhmm(end_hhmm)
    local_t = current.timetz().replace(tzinfo=None)

    if start < end:
        blocked = start <= local_t < end
    else:
        blocked = local_t >= start or local_t < end

    if blocked:
        return True, f"NO_NEW_TRADES {start_hhmm}-{end_hhmm} {tz_name}"
    return False, "TRADING_WINDOW_OPEN"
