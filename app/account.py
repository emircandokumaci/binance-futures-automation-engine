from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from .models import AccountState, Side


@dataclass
class PaperAccountSnapshot:
    cash_balance: float
    unrealized_pnl: float
    equity: float
    peak_equity: float
    daily_start_equity: float
    daily_pnl_pct: float
    drawdown_pct: float
    gross_exposure: float
    margin_used: float
    open_positions: int
    available_equity: float

    def as_risk_state(self) -> AccountState:
        return AccountState(
            equity=max(self.equity, 1e-9),
            daily_pnl_pct=self.daily_pnl_pct,
            drawdown_pct=self.drawdown_pct,
            current_gross_exposure=self.gross_exposure,
            current_margin_used=self.margin_used,
            current_open_positions=self.open_positions,
        )


def unrealized_pnl(side: Side, qty: float, entry: float, current: float) -> float:
    if side == Side.LONG:
        return qty * (current - entry)
    return qty * (entry - current)


def drawdown_pct(equity: float, peak: float) -> float:
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - equity) / peak * 100.0)


class PaperAccountService:
    def __init__(self, database_url: str, tz_name: str) -> None:
        self.database_url = database_url
        self.tz = ZoneInfo(tz_name)

    def snapshot(self, prices: dict[str, float]) -> PaperAccountSnapshot:
        today = datetime.now(self.tz).date()
        with psycopg.connect(self.database_url, row_factory=dict_row, autocommit=True) as conn:
            row = conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
            if not row:
                raise RuntimeError("paper_account is not initialized")
            positions = conn.execute("SELECT * FROM paper_positions WHERE status='ACTIVE'").fetchall()

            cash = float(row['cash_balance'])
            upnl = 0.0
            gross = 0.0
            margin = 0.0
            for p in positions:
                current = float(prices.get(p['symbol'], p['current_price']))
                upnl += unrealized_pnl(Side(p['side']), float(p['qty']), float(p['entry_price']), current)
                gross += float(p['notional'])
                margin += float(p['margin_used'])

            equity = cash + upnl
            peak = max(float(row['peak_equity']), equity)
            day_start_date = row['daily_start_date']
            day_start = float(row['daily_start_equity'])
            if day_start_date != today:
                day_start = equity
                conn.execute(
                    "UPDATE paper_account SET daily_start_date=%s,daily_start_equity=%s,updated_at=NOW() WHERE id=1",
                    (today, equity),
                )
            if peak != float(row['peak_equity']):
                conn.execute("UPDATE paper_account SET peak_equity=%s,updated_at=NOW() WHERE id=1", (peak,))

            daily_pct = ((equity - day_start) / day_start * 100.0) if day_start > 0 else 0.0
            dd = drawdown_pct(equity, peak)
            return PaperAccountSnapshot(
                cash_balance=cash,
                unrealized_pnl=upnl,
                equity=equity,
                peak_equity=peak,
                daily_start_equity=day_start,
                daily_pnl_pct=daily_pct,
                drawdown_pct=dd,
                gross_exposure=gross,
                margin_used=margin,
                open_positions=len(positions),
                available_equity=max(0.0, equity - margin),
            )
