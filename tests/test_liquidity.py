from app.liquidity import select_liquid_universe


def test_selects_liquid_old_low_spread_contracts():
    now_ms = 2_000_000_000_000
    old = now_ms - 60 * 86_400_000
    new = now_ms - 5 * 86_400_000
    info = {'symbols': [
        {'symbol':'BTCUSDT','contractType':'PERPETUAL','quoteAsset':'USDT','marginAsset':'USDT','status':'TRADING','onboardDate':old},
        {'symbol':'NEWUSDT','contractType':'PERPETUAL','quoteAsset':'USDT','marginAsset':'USDT','status':'TRADING','onboardDate':new},
        {'symbol':'WIDEUSDT','contractType':'PERPETUAL','quoteAsset':'USDT','marginAsset':'USDT','status':'TRADING','onboardDate':old},
        {'symbol':'龙虾USDT','contractType':'PERPETUAL','quoteAsset':'USDT','marginAsset':'USDT','status':'TRADING','onboardDate':old},
    ]}
    tickers = [
        {'symbol':'BTCUSDT','quoteVolume':'100000000'},
        {'symbol':'NEWUSDT','quoteVolume':'200000000'},
        {'symbol':'WIDEUSDT','quoteVolume':'100000000'},
        {'symbol':'龙虾USDT','quoteVolume':'300000000'},
    ]
    books = [
        {'symbol':'BTCUSDT','bidPrice':'100','askPrice':'100.02'},
        {'symbol':'NEWUSDT','bidPrice':'10','askPrice':'10.01'},
        {'symbol':'WIDEUSDT','bidPrice':'100','askPrice':'101'},
        {'symbol':'龙虾USDT','bidPrice':'100','askPrice':'100.01'},
    ]
    out = select_liquid_universe(info,tickers,books,top_n=20,min_quote_volume=50_000_000,max_spread_bps=8,min_listing_age_days=30,now_ms=now_ms)
    assert [x['symbol'] for x in out] == ['BTCUSDT']
