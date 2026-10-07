from __future__ import annotations

import uuid

from .binance_private import BinancePrivateClient
from .exchange_rules import SymbolRules, floor_to_step, round_price
from .models import Side


class LiveExecutionGateway:
    """Protected live-order transaction. Not wired to HTTP while PAPER_ONLY is enforced."""

    def __init__(self, client: BinancePrivateClient) -> None:
        self.client = client

    @staticmethod
    def _cid(prefix: str, symbol: str) -> str:
        return f"jarvis-{prefix}-{symbol[:8]}-{uuid.uuid4().hex[:12]}"[:36]

    async def open_protected_position(
        self,
        symbol: str,
        side: Side,
        qty: float,
        leverage: int,
        stop: float,
        target: float,
        rules: SymbolRules,
        allow_live: bool,
    ) -> dict:
        if not allow_live:
            raise RuntimeError('LIVE_EXECUTION_DISABLED')
        if not self.client.configured:
            raise RuntimeError('BINANCE_PRIVATE_API_NOT_CONFIGURED')
        qty = floor_to_step(qty, rules.step_size)
        if qty <= 0:
            raise RuntimeError('INVALID_QTY_AFTER_EXCHANGE_ROUNDING')
        stop = round_price(stop, rules.tick_size, upward=(side == Side.SHORT))
        target = round_price(target, rules.tick_size, upward=(side == Side.LONG))
        await self.client.change_leverage(symbol, leverage)
        try:
            await self.client.change_margin_type(symbol, 'ISOLATED')
        except Exception as exc:
            if '-4046' not in str(exc):
                raise
        entry_side = 'BUY' if side == Side.LONG else 'SELL'
        exit_side = 'SELL' if side == Side.LONG else 'BUY'
        entry = await self.client.place_order(
            symbol=symbol, side=entry_side, type='MARKET', quantity=qty,
            newClientOrderId=self._cid('entry', symbol), newOrderRespType='RESULT',
        )
        try:
            stop_order = await self.client.place_order(
                symbol=symbol, side=exit_side, type='STOP_MARKET', stopPrice=stop,
                closePosition='true', workingType='MARK_PRICE', priceProtect='TRUE',
                newClientOrderId=self._cid('stop', symbol),
            )
            tp_order = await self.client.place_order(
                symbol=symbol, side=exit_side, type='TAKE_PROFIT_MARKET', stopPrice=target,
                closePosition='true', workingType='MARK_PRICE', priceProtect='TRUE',
                newClientOrderId=self._cid('tp', symbol),
            )
            return {'entry': entry, 'stop': stop_order, 'target': tp_order}
        except Exception:
            # Fail closed: if exchange-side protection cannot be armed, flatten immediately.
            await self.client.place_order(
                symbol=symbol, side=exit_side, type='MARKET', quantity=qty,
                reduceOnly='true', newClientOrderId=self._cid('panic', symbol),
            )
            raise
