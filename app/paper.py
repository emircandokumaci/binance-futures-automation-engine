from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from .models import RiskAssessment, Side, Signal


@dataclass
class PaperExecutionConfig:
    taker_fee_rate: float = 0.0005
    slippage_bps: float = 5.0


def apply_slippage(price: float, side: Side, is_entry: bool, bps: float) -> float:
    slip = bps / 10_000.0
    if side == Side.LONG:
        return price * (1 + slip if is_entry else 1 - slip)
    return price * (1 - slip if is_entry else 1 + slip)


def gross_pnl(side: Side, qty: float, entry: float, exit_price: float) -> float:
    if side == Side.LONG:
        return qty * (exit_price - entry)
    return qty * (entry - exit_price)


class PaperExecutor:
    def __init__(self, database_url: str, config: PaperExecutionConfig) -> None:
        self.database_url = database_url
        self.config = config

    def open_position(self, signal: Signal, risk: RiskAssessment, mark_price: float, slippage_bps: float | None = None) -> dict:
        if not risk.approved:
            raise ValueError(f"Risk not approved: {risk.reason}")
        position_id, order_id, fill_id = (str(uuid.uuid4()) for _ in range(3))
        slip = self.config.slippage_bps if slippage_bps is None else float(slippage_bps)
        fill_price = apply_slippage(mark_price, signal.side, True, slip)
        qty = risk.notional / mark_price
        entry_fee = abs(qty * fill_price) * self.config.taker_fee_rate

        with psycopg.connect(self.database_url) as conn:
            account = conn.execute("SELECT cash_balance FROM paper_account WHERE id=1 FOR UPDATE").fetchone()
            if not account:
                raise RuntimeError("paper account missing")
            if float(account[0]) <= entry_fee:
                raise RuntimeError("insufficient paper cash for entry fee")
            conn.execute("UPDATE paper_account SET cash_balance=cash_balance-%s,updated_at=NOW() WHERE id=1", (entry_fee,))
            conn.execute(
                """INSERT INTO paper_positions
                (id,symbol,side,status,entry_price,current_price,stop_price,target_price,qty,notional,leverage,margin_used,risk_usdt,entry_fee,entry_slippage_bps)
                VALUES(%s,%s,%s,'ACTIVE',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (position_id, signal.symbol, signal.side.value, fill_price, mark_price,
                 signal.stop, signal.target, qty, risk.notional, risk.leverage,
                 risk.margin_required, risk.risk_usdt, entry_fee, slip),
            )
            conn.execute(
                """INSERT INTO paper_orders(id,position_id,symbol,side,role,order_type,status,requested_price)
                VALUES(%s,%s,%s,%s,'ENTRY','MARKET','FILLED',%s)""",
                (order_id, position_id, signal.symbol, signal.side.value, mark_price),
            )
            conn.execute(
                """INSERT INTO paper_fills(id,order_id,position_id,symbol,side,qty,price,fee)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (fill_id, order_id, position_id, signal.symbol, signal.side.value, qty, fill_price, entry_fee),
            )
            self._event(conn, position_id, 'ENTRY_FILLED', {'mark': mark_price, 'fill': fill_price, 'entry_fee': entry_fee, 'slippage_bps': slip})
            self._event(conn, position_id, 'PROTECTION_ARMED', {'stop': signal.stop, 'target': signal.target})
        return self.get_position(position_id)

    def get_position(self, position_id: str) -> dict:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            row = conn.execute("SELECT * FROM paper_positions WHERE id=%s", (position_id,)).fetchone()
            return dict(row) if row else {}

    def list_positions(self, status: str | None = None) -> list[dict]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            if status:
                rows = conn.execute("SELECT * FROM paper_positions WHERE status=%s ORDER BY created_at DESC", (status,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM paper_positions ORDER BY created_at DESC LIMIT 100").fetchall()
            return [dict(r) for r in rows]

    def active_count(self) -> int:
        with psycopg.connect(self.database_url) as conn:
            return int(conn.execute("SELECT count(*) FROM paper_positions WHERE status='ACTIVE'").fetchone()[0])

    def on_prices(self, prices: dict[str, float], slippage_by_symbol: dict[str, float] | None = None) -> list[dict]:
        closed: list[dict] = []
        slippage_by_symbol = slippage_by_symbol or {}
        for pos in self.list_positions('ACTIVE'):
            price = prices.get(pos['symbol'])
            if price is None:
                continue
            self._update_price(pos['id'], price)
            side = Side(pos['side'])
            stop_hit = price <= pos['stop_price'] if side == Side.LONG else price >= pos['stop_price']
            target_hit = price >= pos['target_price'] if side == Side.LONG else price <= pos['target_price']
            slip = slippage_by_symbol.get(pos['symbol'])
            if stop_hit:
                closed.append(self.close_position(pos['id'], price, 'STOP_LOSS', slip))
            elif target_hit:
                closed.append(self.close_position(pos['id'], price, 'TAKE_PROFIT', slip))
        return closed

    def apply_funding(self, position_id: str, funding_time: int, rate: float, mark_price: float) -> dict:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            pos = conn.execute("SELECT * FROM paper_positions WHERE id=%s FOR UPDATE", (position_id,)).fetchone()
            if not pos or pos['status'] != 'ACTIVE':
                return {'applied': False, 'reason': 'POSITION_NOT_ACTIVE'}
            side = Side(pos['side'])
            notional = abs(float(pos['qty']) * mark_price)
            payment = notional * float(rate)
            if side == Side.LONG:
                payment = -payment
            try:
                conn.execute(
                    """INSERT INTO paper_funding_events(position_id,funding_time,symbol,rate,mark_price,payment)
                    VALUES(%s,%s,%s,%s,%s,%s)""",
                    (position_id, int(funding_time), pos['symbol'], float(rate), mark_price, payment),
                )
            except psycopg.errors.UniqueViolation:
                conn.rollback()
                return {'applied': False, 'reason': 'ALREADY_APPLIED'}
            conn.execute("UPDATE paper_account SET cash_balance=cash_balance+%s,updated_at=NOW() WHERE id=1", (payment,))
            conn.execute("UPDATE paper_positions SET funding_pnl=funding_pnl+%s,updated_at=NOW() WHERE id=%s", (payment, position_id))
            self._event(conn, position_id, 'FUNDING_APPLIED', {'funding_time': funding_time, 'rate': rate, 'mark': mark_price, 'payment': payment})
            return {'applied': True, 'payment': payment, 'rate': rate, 'funding_time': funding_time}

    def close_position(self, position_id: str, mark_price: float, reason: str, slippage_bps: float | None = None) -> dict:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            pos = conn.execute(
                "SELECT * FROM paper_positions WHERE id=%s FOR UPDATE", (position_id,)
            ).fetchone()
            if not pos or pos['status'] != 'ACTIVE':
                return dict(pos) if pos else {}
            side = Side(pos['side'])
            slip = self.config.slippage_bps if slippage_bps is None else float(slippage_bps)
            exit_price = apply_slippage(mark_price, side, False, slip)
            exit_fee = abs(float(pos['qty']) * exit_price) * self.config.taker_fee_rate
            pnl_gross = gross_pnl(side, float(pos['qty']), float(pos['entry_price']), exit_price)
            funding_pnl = float(pos.get('funding_pnl') or 0)
            pnl_net = pnl_gross - float(pos['entry_fee']) - exit_fee + funding_pnl
            order_id, fill_id = str(uuid.uuid4()), str(uuid.uuid4())
            exit_side = 'SHORT' if side == Side.LONG else 'LONG'

            conn.execute(
                """UPDATE paper_positions SET status='CLOSED',current_price=%s,exit_price=%s,
                exit_fee=%s,exit_slippage_bps=%s,realized_pnl=%s,exit_reason=%s,closed_at=NOW(),updated_at=NOW()
                WHERE id=%s""",
                (mark_price, exit_price, exit_fee, slip, pnl_net, reason, position_id),
            )
            conn.execute(
                "UPDATE paper_account SET cash_balance=cash_balance+%s-%s,updated_at=NOW() WHERE id=1",
                (pnl_gross, exit_fee),
            )
            conn.execute(
                """INSERT INTO paper_orders(id,position_id,symbol,side,role,order_type,status,requested_price)
                VALUES(%s,%s,%s,%s,'EXIT','MARKET','FILLED',%s)""",
                (order_id, position_id, pos['symbol'], exit_side, mark_price),
            )
            conn.execute(
                """INSERT INTO paper_fills(id,order_id,position_id,symbol,side,qty,price,fee)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (fill_id, order_id, position_id, pos['symbol'], exit_side, pos['qty'], exit_price, exit_fee),
            )
            self._event(conn, position_id, 'POSITION_CLOSED', {
                'reason': reason, 'mark': mark_price, 'fill': exit_price,
                'gross_pnl': pnl_gross, 'funding_pnl': funding_pnl,
                'exit_fee': exit_fee, 'net_pnl': pnl_net, 'slippage_bps': slip,
            })
        return self.get_position(position_id)

    def _update_price(self, position_id: str, price: float) -> None:
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            conn.execute(
                "UPDATE paper_positions SET current_price=%s,updated_at=NOW() WHERE id=%s AND status='ACTIVE'",
                (price, position_id),
            )

    @staticmethod
    def _event(conn, position_id: str, event_type: str, payload: dict) -> None:
        conn.execute(
            "INSERT INTO position_events(position_id,event_type,payload) VALUES(%s,%s,%s::jsonb)",
            (position_id, event_type, json.dumps(payload)),
        )
