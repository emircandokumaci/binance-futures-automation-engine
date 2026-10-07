import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .account import PaperAccountService
from .binance_private import BinancePrivateClient
from .binance_public import BinancePublicClient
from .db import init_db, log_event, log_risk_decision
from .exchange_rules import SymbolRules, constrain_risk_to_exchange, parse_symbol_rules
from .execution_costs import estimate_top_book_slippage_bps
from .liquidation import (
    LiquidationBracketStore,
    estimate_isolated_liquidation_price,
    liquidation_guard,
)
from .liquidity import select_liquid_universe
from .models import AccountState, Side, Signal
from .outcomes import ShadowOutcomeTracker, outcome_stats
from .paper import PaperExecutionConfig, PaperExecutor
from .reconciliation import ReconciliationService
from .research_backtest import run_base_strategy_backtest
from .risk import assess_signal
from .safety import enforce_phase_one_safety
from .schedule import no_new_trades_window
from .settings import settings
from .shadow import ShadowScanner, recent_signals

market = BinancePublicClient(settings.binance_fapi_base, settings.binance_ws_base)
private = BinancePrivateClient(
    settings.binance_fapi_base, settings.binance_api_key, settings.binance_api_secret, settings.binance_recv_window
)
paper = PaperExecutor(
    settings.database_url,
    PaperExecutionConfig(taker_fee_rate=settings.paper_taker_fee_rate, slippage_bps=settings.paper_slippage_bps),
)
account = PaperAccountService(settings.database_url, settings.tz)
shadow = ShadowScanner(settings.database_url, market, concurrency=5)
outcomes = ShadowOutcomeTracker(settings.database_url, market, settings.shadow_outcome_horizon_hours)
liquidation_brackets = LiquidationBracketStore()
reconciliation = ReconciliationService(settings.database_url, private)
market_task: asyncio.Task | None = None
paper_task: asyncio.Task | None = None
shadow_task: asyncio.Task | None = None
outcome_task: asyncio.Task | None = None
reconcile_task: asyncio.Task | None = None
liquid_universe: list[dict] = []
selected_symbols: list[str] = []
exchange_rules: dict[str, SymbolRules] = {}
last_shadow_bucket: str | None = None
shadow_scan_lock = asyncio.Lock()


class RiskPreviewRequest(BaseModel):
    signal: Signal
    account: AccountState


class PaperOpenRequest(BaseModel):
    signal: Signal


class LiquidationPreviewRequest(BaseModel):
    symbol: str
    side: Side
    entry: float
    stop: float
    notional: float
    leverage: int


def _slippage_for(symbol: str, side: Side, notional: float) -> float:
    return estimate_top_book_slippage_bps(
        side,
        notional,
        market.state.book_bid.get(symbol), market.state.book_bid_qty.get(symbol),
        market.state.book_ask.get(symbol), market.state.book_ask_qty.get(symbol),
        floor_bps=settings.dynamic_slippage_floor_bps,
        cap_bps=settings.dynamic_slippage_cap_bps,
    )


async def paper_monitor_loop() -> None:
    while True:
        try:
            age = market.state.tick_age_seconds()
            if market.state.connected and age is not None and age < 10:
                active = await asyncio.to_thread(paper.list_positions, 'ACTIVE')
                slips: dict[str, float] = {}
                now_ms = int(time.time() * 1000)
                for pos in active:
                    symbol = pos['symbol']
                    side = Side(pos['side'])
                    slips[symbol] = _slippage_for(symbol, side, float(pos['notional']))
                    ft = market.state.next_funding_time.get(symbol)
                    fr = market.state.funding_rate.get(symbol)
                    mark = market.state.mark_prices.get(symbol)
                    if ft and fr is not None and mark and now_ms >= ft:
                        result = await asyncio.to_thread(paper.apply_funding, pos['id'], ft, fr, mark)
                        if result.get('applied'):
                            log_event(settings.database_url, 'PAPER_FUNDING_APPLIED', {'position_id': pos['id'], 'symbol': symbol, **result})
                closed = await asyncio.to_thread(paper.on_prices, dict(market.state.mark_prices), slips)
                for item in closed:
                    log_event(settings.database_url, 'PAPER_POSITION_CLOSED', {
                        'id': item.get('id'), 'symbol': item.get('symbol'),
                        'reason': item.get('exit_reason'), 'pnl': item.get('realized_pnl'),
                    })
                await asyncio.to_thread(account.snapshot, dict(market.state.mark_prices))
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_event(settings.database_url, 'PAPER_MONITOR_ERROR', {'error': f'{type(exc).__name__}: {exc}'})
            await asyncio.sleep(2.0)


async def run_shadow_scan() -> list[Signal]:
    if not selected_symbols:
        return []
    async with shadow_scan_lock:
        signals = await shadow.scan(selected_symbols)
        log_event(settings.database_url, 'SHADOW_SCAN_COMPLETE', {
            'symbols_scanned': len(selected_symbols), 'signals_found': len(signals),
            'signals': [f'{s.symbol}:{s.side.value}:{s.confidence:.3f}' for s in signals],
        })
        return signals


async def shadow_scheduler_loop() -> None:
    global last_shadow_bucket
    tz = ZoneInfo(settings.tz)
    while True:
        try:
            now = datetime.now(tz)
            blocked, _ = no_new_trades_window(now, settings.tz, settings.no_new_trades_start, settings.no_new_trades_end)
            bucket = now.strftime('%Y-%m-%d-%H-') + f'{(now.minute // 15) * 15:02d}'
            if not blocked and now.minute % 15 in {1, 2} and bucket != last_shadow_bucket:
                await run_shadow_scan()
                last_shadow_bucket = bucket
            await asyncio.sleep(20.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_event(settings.database_url, 'SHADOW_SCHEDULER_ERROR', {'error': f'{type(exc).__name__}: {exc}'})
            await asyncio.sleep(30.0)


async def outcome_tracker_loop() -> None:
    while True:
        try:
            results = await outcomes.run_once(30)
            if results:
                log_event(settings.database_url, 'SHADOW_OUTCOME_UPDATE', {'count': len(results), 'results': results[:10]})
            await asyncio.sleep(300.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_event(settings.database_url, 'SHADOW_OUTCOME_ERROR', {'error': f'{type(exc).__name__}: {exc}'})
            await asyncio.sleep(60.0)


async def reconciliation_loop() -> None:
    while True:
        try:
            await reconciliation.run_once()
            await asyncio.sleep(max(10, settings.private_reconcile_interval_seconds))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_event(settings.database_url, 'RECONCILIATION_LOOP_ERROR', {'error': f'{type(exc).__name__}: {exc}'})
            await asyncio.sleep(30.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global market_task, paper_task, shadow_task, outcome_task, reconcile_task
    global liquid_universe, selected_symbols, exchange_rules
    enforce_phase_one_safety(settings)
    init_db(settings.database_url, settings.paper_starting_equity)

    server_time, info, tickers, books = await asyncio.gather(
        market.server_time(), market.exchange_info(), market.ticker_24h(), market.book_ticker()
    )
    exchange_rules = parse_symbol_rules(info)
    liquid_universe = select_liquid_universe(
        info, tickers, books,
        top_n=settings.universe_top_n, min_quote_volume=settings.min_quote_volume_usdt,
        max_spread_bps=settings.max_spread_bps, min_listing_age_days=settings.min_listing_age_days,
        now_ms=server_time,
    )
    selected_symbols = [row['symbol'] for row in liquid_universe]
    if not selected_symbols:
        raise RuntimeError('No liquid USDT perpetual symbols passed the configured filters')

    if private.configured:
        try:
            await private.sync_time()
            rows = await private.leverage_brackets()
            if isinstance(rows, dict):
                rows = [rows]
            liquidation_brackets.load_signed_snapshot(rows)
            await reconciliation.run_once()
        except Exception as exc:
            log_event(settings.database_url, 'PRIVATE_BOOTSTRAP_ERROR', {'error': f'{type(exc).__name__}: {exc}'})

    log_event(settings.database_url, 'ENGINE_STARTED', {
        'paper_only': True, 'server_time': server_time, 'selected_symbols': selected_symbols,
        'universe_count': len(selected_symbols), 'private_api_configured': private.configured,
        'exchange_rules_count': len(exchange_rules),
    })
    market_task = asyncio.create_task(market.run_mark_price_stream(tuple(s.lower() for s in selected_symbols)))
    paper_task = asyncio.create_task(paper_monitor_loop())
    shadow_task = asyncio.create_task(shadow_scheduler_loop())
    outcome_task = asyncio.create_task(outcome_tracker_loop())
    if private.configured:
        reconcile_task = asyncio.create_task(reconciliation_loop())
    try:
        yield
    finally:
        for task in (reconcile_task, outcome_task, shadow_task, paper_task, market_task):
            if task:
                task.cancel()
        for task in (reconcile_task, outcome_task, shadow_task, paper_task, market_task):
            if task:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        log_event(settings.database_url, 'ENGINE_STOPPED', {'paper_only': True})


app = FastAPI(title='Jarvis Futures Engine', version='0.6.1', lifespan=lifespan)


def current_account_payload() -> dict:
    snap = account.snapshot(dict(market.state.mark_prices))
    return {
        'cash_balance': snap.cash_balance, 'unrealized_pnl': snap.unrealized_pnl, 'equity': snap.equity,
        'peak_equity': snap.peak_equity, 'daily_start_equity': snap.daily_start_equity,
        'daily_pnl_pct': snap.daily_pnl_pct, 'drawdown_pct': snap.drawdown_pct,
        'gross_exposure': snap.gross_exposure, 'margin_used': snap.margin_used,
        'available_equity': snap.available_equity, 'open_positions': snap.open_positions,
    }


def live_readiness() -> dict:
    liq = liquidation_brackets.status(selected_symbols)
    rec = reconciliation.status()
    gates = {
        'live_flag_enabled': settings.live_trading_enabled,
        'private_api_configured': private.configured,
        'liquidation_brackets_ready': liq['ready'],
        'reconciliation_ok': bool(rec.get('ok')) if private.configured else False,
        'one_way_isolated_policy': True,
        'exchange_rules_loaded': bool(exchange_rules),
        'market_stream_fresh': bool(market.state.connected and (market.state.tick_age_seconds() or 999) < 10),
    }
    return {'ready': all(gates.values()), 'gates': gates, 'policy': 'FAIL_CLOSED', 'paper_only': True}


@app.get('/health')
def health():
    age = market.state.tick_age_seconds()
    return {'ok': bool(market.state.connected and age is not None and age < 15), 'paper_only': True,
            'market_connected': market.state.connected, 'tick_age_seconds': age}


@app.get('/status')
def status():
    blocked, reason = no_new_trades_window(datetime.now(ZoneInfo(settings.tz)), settings.tz,
                                           settings.no_new_trades_start, settings.no_new_trades_end)
    return {
        'mode': settings.trading_mode, 'live_trading_enabled': settings.live_trading_enabled,
        'new_trades_blocked': blocked, 'schedule_reason': reason,
        'market_connected': market.state.connected, 'reconnects': market.state.reconnects,
        'last_error': market.state.last_error, 'selected_universe_count': len(selected_symbols),
        'shadow_strategy': {'name': shadow.strategy.name, 'version': shadow.strategy.version, 'auto_execute': False},
        'liquidation_guard': liquidation_brackets.status(selected_symbols),
        'private_api': {'configured': private.configured, 'last_ok_ts': private.status.last_ok_ts, 'last_error': private.status.last_error},
        'reconciliation': reconciliation.status(),
        'live_readiness': live_readiness(),
        'paper_account': current_account_payload(),
    }


@app.get('/market/marks')
def marks():
    return market.state.mark_prices


@app.get('/market/universe')
def universe():
    return {'count': len(liquid_universe), 'filters': {
        'top_n': settings.universe_top_n, 'min_quote_volume_usdt': settings.min_quote_volume_usdt,
        'max_spread_bps': settings.max_spread_bps, 'min_listing_age_days': settings.min_listing_age_days,
    }, 'symbols': liquid_universe}


@app.get('/paper/account')
def paper_account():
    return current_account_payload()


@app.get('/risk/liquidation/status')
def liquidation_status():
    return liquidation_brackets.status(selected_symbols)


@app.post('/risk/liquidation/preview')
def liquidation_preview(req: LiquidationPreviewRequest):
    bracket = liquidation_brackets.select(req.symbol, req.notional)
    if not bracket:
        return {'approved': False, 'reason': 'LIQUIDATION_BRACKET_NOT_AVAILABLE'}
    qty = req.notional / req.entry
    liq = estimate_isolated_liquidation_price(req.side.value, req.entry, qty, req.leverage, bracket)
    return liquidation_guard(req.side.value, req.entry, req.stop, liq,
                             settings.min_liquidation_buffer_pct, settings.min_liquidation_stop_multiple)


@app.get('/private/status')
def private_status():
    return {'configured': private.configured, 'last_ok_ts': private.status.last_ok_ts,
            'last_error': private.status.last_error, 'time_offset_ms': private.status.time_offset_ms}


@app.get('/reconcile/status')
def reconcile_status():
    return reconciliation.status()


@app.post('/reconcile/run')
async def reconcile_run():
    return await reconciliation.run_once()


@app.get('/live/readiness')
def live_ready():
    return live_readiness()


@app.get('/research/backtest/{symbol}')
async def research_backtest(symbol: str, limit: int = 1500):
    symbol=symbol.upper()
    if symbol not in selected_symbols:
        raise HTTPException(status_code=400, detail='SYMBOL_NOT_IN_LIQUID_UNIVERSE')
    return await run_base_strategy_backtest(market, symbol, limit)


@app.post('/risk/preview')
def risk_preview(req: RiskPreviewRequest):
    result = assess_signal(req.signal, req.account, settings)
    log_risk_decision(settings.database_url, req.signal.symbol, result.approved, result.reason, result.model_dump())
    return result


@app.post('/paper/open')
def paper_open(req: PaperOpenRequest):
    if req.signal.symbol not in selected_symbols:
        raise HTTPException(status_code=400, detail='SYMBOL_NOT_IN_LIQUID_UNIVERSE')
    mark = market.state.mark_prices.get(req.signal.symbol)
    age = market.state.tick_age_seconds()
    if mark is None or age is None or age >= 10:
        raise HTTPException(status_code=503, detail='NO_FRESH_MARK_PRICE')
    active = paper.list_positions('ACTIVE')
    if any(p['symbol'] == req.signal.symbol for p in active):
        return {'opened': False, 'reason': 'SYMBOL_ALREADY_ACTIVE'}
    snap = account.snapshot(dict(market.state.mark_prices))
    effective_signal = req.signal.model_copy(update={'entry': mark})
    risk = assess_signal(effective_signal, snap.as_risk_state(), settings)
    rules = exchange_rules.get(req.signal.symbol)
    if risk.approved and rules:
        risk = constrain_risk_to_exchange(effective_signal, risk, mark, rules)
    log_risk_decision(settings.database_url, effective_signal.symbol, risk.approved, risk.reason, risk.model_dump())
    if not risk.approved:
        return {'opened': False, 'risk': risk.model_dump()}
    slip = _slippage_for(req.signal.symbol, effective_signal.side, risk.notional)
    position = paper.open_position(effective_signal, risk, mark, slip)
    return {'opened': True, 'risk': risk.model_dump(), 'execution': {'slippage_bps': slip},
            'position': position, 'account': current_account_payload()}


@app.get('/paper/positions')
def paper_positions(status: str | None = None):
    if status is not None and status not in {'ACTIVE', 'CLOSED'}:
        raise HTTPException(status_code=400, detail='status must be ACTIVE or CLOSED')
    return {'positions': paper.list_positions(status)}


@app.post('/shadow/run')
async def shadow_run():
    blocked, reason = no_new_trades_window(datetime.now(ZoneInfo(settings.tz)), settings.tz,
                                           settings.no_new_trades_start, settings.no_new_trades_end)
    if blocked:
        return {'ran': False, 'reason': reason}
    signals = await run_shadow_scan()
    return {'ran': True, 'symbols_scanned': len(selected_symbols), 'signals_found': len(signals),
            'signals': [s.model_dump() for s in signals], 'auto_execute': False}


@app.get('/shadow/signals')
def shadow_signals(limit: int = 50):
    return {'signals': recent_signals(settings.database_url, limit)}


@app.post('/shadow/outcomes/run')
async def shadow_outcomes_run():
    results = await outcomes.run_once(50)
    return {'updated': len(results), 'results': results}


@app.get('/shadow/outcomes/stats')
def shadow_outcomes_stats():
    return outcome_stats(settings.database_url)
