def eligible_usdt_perpetual_symbols(exchange_info: dict) -> list[str]:
    result: list[str] = []
    for item in exchange_info.get('symbols', []):
        if (
            item.get('contractType') == 'PERPETUAL'
            and item.get('quoteAsset') == 'USDT'
            and item.get('marginAsset') == 'USDT'
            and item.get('status') == 'TRADING'
        ):
            result.append(item['symbol'])
    return sorted(result)
