from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx


@dataclass
class PrivateApiStatus:
    configured: bool
    last_ok_ts: float = 0.0
    last_error: str = ""
    time_offset_ms: int = 0


class BinancePrivateClient:
    """Minimal HMAC client for USDⓈ-M Futures private endpoints.

    The client is inert when credentials are absent. Secrets are never logged or exposed.
    """

    def __init__(self, base_url: str, api_key: str = "", api_secret: str = "", recv_window: int = 5000) -> None:
        self.base_url = base_url.rstrip('/')
        self.api_key = (api_key or '').strip()
        self.api_secret = (api_secret or '').strip()
        self.recv_window = int(recv_window)
        self.status = PrivateApiStatus(configured=bool(self.api_key and self.api_secret))

    @property
    def configured(self) -> bool:
        return self.status.configured

    async def sync_time(self) -> int:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{self.base_url}/fapi/v1/time")
            r.raise_for_status()
            server = int(r.json()['serverTime'])
        local = int(time.time() * 1000)
        self.status.time_offset_ms = server - local
        return self.status.time_offset_ms

    def _timestamp(self) -> int:
        return int(time.time() * 1000) + self.status.time_offset_ms

    def _signed_params(self, params: dict | None = None) -> dict:
        if not self.configured:
            raise RuntimeError('BINANCE_PRIVATE_API_NOT_CONFIGURED')
        out = dict(params or {})
        out.setdefault('recvWindow', self.recv_window)
        out.setdefault('timestamp', self._timestamp())
        query = urlencode(out, doseq=True)
        out['signature'] = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return out

    async def _signed(self, method: str, path: str, params: dict | None = None):
        if not self.configured:
            raise RuntimeError('BINANCE_PRIVATE_API_NOT_CONFIGURED')
        headers = {'X-MBX-APIKEY': self.api_key}
        signed = self._signed_params(params)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.request(method, f"{self.base_url}{path}", params=signed, headers=headers)
                if r.status_code == 400 and 'Timestamp for this request' in r.text:
                    await self.sync_time()
                    signed = self._signed_params(params)
                    r = await client.request(method, f"{self.base_url}{path}", params=signed, headers=headers)
                r.raise_for_status()
                self.status.last_ok_ts = time.time()
                self.status.last_error = ''
                return r.json() if r.content else {}
        except Exception as exc:
            self.status.last_error = f'{type(exc).__name__}: {exc}'
            raise

    async def leverage_brackets(self, symbol: str | None = None):
        params = {'symbol': symbol.upper()} if symbol else {}
        return await self._signed('GET', '/fapi/v1/leverageBracket', params)

    async def account(self):
        return await self._signed('GET', '/fapi/v3/account')

    async def position_risk(self, symbol: str | None = None):
        params = {'symbol': symbol.upper()} if symbol else {}
        return await self._signed('GET', '/fapi/v3/positionRisk', params)

    async def open_orders(self, symbol: str | None = None):
        params = {'symbol': symbol.upper()} if symbol else {}
        return await self._signed('GET', '/fapi/v1/openOrders', params)

    async def change_leverage(self, symbol: str, leverage: int):
        return await self._signed('POST', '/fapi/v1/leverage', {'symbol': symbol.upper(), 'leverage': int(leverage)})

    async def change_margin_type(self, symbol: str, margin_type: str = 'ISOLATED'):
        return await self._signed('POST', '/fapi/v1/marginType', {'symbol': symbol.upper(), 'marginType': margin_type})

    async def place_order(self, **params):
        return await self._signed('POST', '/fapi/v1/order', params)

    async def cancel_order(self, symbol: str, order_id: int | None = None, client_order_id: str | None = None):
        params: dict = {'symbol': symbol.upper()}
        if order_id is not None:
            params['orderId'] = order_id
        if client_order_id:
            params['origClientOrderId'] = client_order_id
        return await self._signed('DELETE', '/fapi/v1/order', params)
