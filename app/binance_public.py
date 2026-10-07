import asyncio
import json
import time
from dataclasses import dataclass, field

import httpx
import websockets


@dataclass
class MarketDataState:
    connected: bool = False
    last_message_ts: float = 0.0
    reconnects: int = 0
    mark_prices: dict[str, float] = field(default_factory=dict)
    last_error: str = ""

    def tick_age_seconds(self) -> float | None:
        if self.last_message_ts <= 0:
            return None
        return max(0.0, time.time() - self.last_message_ts)


class BinancePublicClient:
    def __init__(self, fapi_base: str, ws_base: str) -> None:
        self.fapi_base = fapi_base.rstrip("/")
        self.ws_base = ws_base.rstrip("/")
        self.state = MarketDataState()

    async def server_time(self) -> int:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{self.fapi_base}/fapi/v1/time")
            r.raise_for_status()
            return int(r.json()["serverTime"])

    async def exchange_info(self) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{self.fapi_base}/fapi/v1/exchangeInfo")
            r.raise_for_status()
            return r.json()


    async def ticker_24h(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{self.fapi_base}/fapi/v1/ticker/24hr")
            r.raise_for_status()
            return r.json()

    async def book_ticker(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{self.fapi_base}/fapi/v1/ticker/bookTicker")
            r.raise_for_status()
            return r.json()

    async def klines(self, symbol: str, interval: str, limit: int = 99) -> list[list]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{self.fapi_base}/fapi/v1/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
            )
            r.raise_for_status()
            return r.json()


    async def _get(self, path: str, params: dict | None = None, timeout: float = 15.0, headers: dict | None = None):
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{self.fapi_base}{path}", params=params or {}, headers=headers or {})
            r.raise_for_status()
            return r.json()

    async def open_interest(self, symbol: str) -> dict:
        return await self._get("/fapi/v1/openInterest", {"symbol": symbol})

    async def depth(self, symbol: str, limit: int = 20) -> dict:
        return await self._get("/fapi/v1/depth", {"symbol": symbol, "limit": limit})

    async def premium_index(self, symbol: str) -> dict:
        return await self._get("/fapi/v1/premiumIndex", {"symbol": symbol})

    async def open_interest_history(self, symbol: str, period: str = "5m", limit: int = 48) -> list[dict]:
        return await self._get("/futures/data/openInterestHist", {"symbol": symbol, "period": period, "limit": limit})

    async def global_long_short_ratio(self, symbol: str, period: str = "5m", limit: int = 48) -> list[dict]:
        return await self._get("/futures/data/globalLongShortAccountRatio", {"symbol": symbol, "period": period, "limit": limit})

    async def taker_long_short_ratio(self, symbol: str, period: str = "5m", limit: int = 48) -> list[dict]:
        return await self._get("/futures/data/takerlongshortRatio", {"symbol": symbol, "period": period, "limit": limit})

    async def funding_history(self, symbol: str, limit: int = 10) -> list[dict]:
        return await self._get("/fapi/v1/fundingRate", {"symbol": symbol, "limit": limit})

    async def ticker_24h_symbol(self, symbol: str) -> dict:
        return await self._get("/fapi/v1/ticker/24hr", {"symbol": symbol})

    async def klines_range(self, symbol: str, interval: str, start_time: int, end_time: int | None = None, limit: int = 1500) -> list[list]:
        params = {"symbol": symbol, "interval": interval, "startTime": start_time, "limit": limit}
        if end_time is not None:
            params["endTime"] = end_time
        return await self._get("/fapi/v1/klines", params)

    async def run_mark_price_stream(self, symbols: tuple[str, ...]) -> None:
        streams = "/".join(f"{s.lower()}@markPrice@1s" for s in symbols)
        url = f"{self.ws_base}/stream?streams={streams}"
        backoff = 1
        while True:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_queue=1024,
                ) as ws:
                    self.state.connected = True
                    self.state.last_error = ""
                    backoff = 1
                    async for raw in ws:
                        payload = json.loads(raw)
                        data = payload.get("data", payload)
                        symbol = data.get("s")
                        mark = data.get("p")
                        if symbol and mark:
                            self.state.mark_prices[symbol] = float(mark)
                            self.state.last_message_ts = time.time()
            except asyncio.CancelledError:
                self.state.connected = False
                raise
            except Exception as exc:
                self.state.connected = False
                self.state.reconnects += 1
                self.state.last_error = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
