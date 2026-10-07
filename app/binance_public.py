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
