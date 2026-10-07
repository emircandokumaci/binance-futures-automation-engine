from app.universe import eligible_usdt_perpetual_symbols


def test_filters_only_trading_usdt_perpetuals():
    info = {'symbols': [
        {'symbol':'BTCUSDT','contractType':'PERPETUAL','quoteAsset':'USDT','marginAsset':'USDT','status':'TRADING'},
        {'symbol':'ETHUSDT_261225','contractType':'CURRENT_QUARTER','quoteAsset':'USDT','marginAsset':'USDT','status':'TRADING'},
        {'symbol':'FOOUSDT','contractType':'PERPETUAL','quoteAsset':'USDT','marginAsset':'USDT','status':'BREAK'},
    ]}
    assert eligible_usdt_perpetual_symbols(info) == ['BTCUSDT']
