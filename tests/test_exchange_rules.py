from app.exchange_rules import parse_symbol_rules, floor_to_step


def test_parse_and_floor_rules():
    info = {'symbols': [{'symbol': 'BTCUSDT','triggerProtect':'0.05','liquidationFee':'0.01','marketTakeBound':'0.3',
        'filters':[{'filterType':'PRICE_FILTER','tickSize':'0.10'}, {'filterType':'MARKET_LOT_SIZE','stepSize':'0.001','minQty':'0.001','maxQty':'100'}, {'filterType':'MIN_NOTIONAL','notional':'5'}]}]}
    rules = parse_symbol_rules(info)['BTCUSDT']
    assert float(rules.tick_size) == 0.1
    assert floor_to_step(0.12345, rules.step_size) == 0.123
