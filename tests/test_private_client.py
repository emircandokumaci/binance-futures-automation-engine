from app.binance_private import BinancePrivateClient


def test_private_client_is_inert_without_keys():
    c = BinancePrivateClient('https://fapi.binance.com')
    assert c.configured is False
    assert c.status.configured is False
