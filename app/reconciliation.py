from __future__ import annotations

import hashlib
import json
import time

import psycopg

from .binance_private import BinancePrivateClient


class ReconciliationService:
    def __init__(self, database_url: str, client: BinancePrivateClient) -> None:
        self.database_url = database_url
        self.client = client
        self.last_run_ts = 0.0
        self.last_error = ''
        self.last_result: dict = {'configured': client.configured, 'ok': False, 'reason': 'NOT_RUN'}
        self._last_persist_fingerprint = ''
        self._last_persist_ts = 0.0

    async def run_once(self) -> dict:
        if not self.client.configured:
            self.last_result = {'configured': False, 'ok': False, 'reason': 'PRIVATE_API_NOT_CONFIGURED'}
            return self.last_result
        try:
            positions = await self.client.position_risk()
            orders = await self.client.open_orders()
            external_positions = []
            for p in positions if isinstance(positions, list) else [positions]:
                amt = float(p.get('positionAmt') or 0)
                if abs(amt) > 0:
                    external_positions.append({
                        'symbol': p.get('symbol'), 'positionAmt': amt,
                        'entryPrice': float(p.get('entryPrice') or 0),
                        'markPrice': float(p.get('markPrice') or 0),
                        'liquidationPrice': float(p.get('liquidationPrice') or 0),
                        'leverage': int(float(p.get('leverage') or 0)),
                        'marginType': p.get('marginType'),
                        'positionSide': p.get('positionSide'),
                    })
            with psycopg.connect(self.database_url) as conn:
                managed = {r[0] for r in conn.execute("SELECT symbol FROM live_position_registry WHERE status='ACTIVE'").fetchall()}
                unmanaged = [p for p in external_positions if p['symbol'] not in managed]
                payload = {
                    'external_positions': external_positions,
                    'open_orders_count': len(orders) if isinstance(orders, list) else 0,
                    'managed_symbols': sorted(managed),
                    'unmanaged_positions': unmanaged,
                }
                canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
                fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
                now = time.time()
                should_persist = (fingerprint != self._last_persist_fingerprint) or (now - self._last_persist_ts >= 300.0)
                if should_persist:
                    conn.execute(
                        "INSERT INTO reconciliation_snapshots(ok,payload) VALUES(%s,%s::jsonb)",
                        (not unmanaged, canonical),
                    )
                    conn.execute(
                        "INSERT INTO system_events(event_type,payload) VALUES(%s,%s::jsonb)",
                        ('RECONCILIATION_OK' if not unmanaged else 'RECONCILIATION_UNMANAGED_POSITION', canonical),
                    )
                    self._last_persist_fingerprint = fingerprint
                    self._last_persist_ts = now
            self.last_run_ts = time.time()
            self.last_error = ''
            self.last_result = {'configured': True, 'ok': not unmanaged, **payload}
            return self.last_result
        except Exception as exc:
            self.last_error = f'{type(exc).__name__}: {exc}'
            self.last_result = {'configured': True, 'ok': False, 'reason': 'RECONCILIATION_ERROR', 'error': self.last_error}
            return self.last_result

    def status(self) -> dict:
        return {'last_run_ts': self.last_run_ts, 'last_error': self.last_error, **self.last_result}
