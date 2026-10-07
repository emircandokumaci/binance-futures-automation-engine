from app.liquidation import LiquidationBracketStore


def test_signed_snapshot_readiness_and_selection():
    s=LiquidationBracketStore()
    s.load_signed_snapshot([{
        "symbol":"BTCUSDT",
        "brackets":[
            {"initialLeverage":125,"notionalFloor":0,"notionalCap":50000,"maintMarginRatio":0.004,"cum":0},
            {"initialLeverage":100,"notionalFloor":50000,"notionalCap":250000,"maintMarginRatio":0.005,"cum":50},
        ]
    }])
    assert s.ready_for("BTCUSDT")
    assert s.select("BTCUSDT", 1000).maint_margin_ratio == 0.004
    assert s.status(["BTCUSDT"])["ready"] is True


def test_missing_symbol_fails_closed():
    s=LiquidationBracketStore()
    out=s.status(["BTCUSDT","ETHUSDT"])
    assert out["ready"] is False
    assert set(out["missing_symbols"]) == {"BTCUSDT","ETHUSDT"}


def test_contract_info_update_parses_brackets_but_is_not_full_snapshot():
    s=LiquidationBracketStore()
    s.apply_contract_info_event({"s":"ETHUSDT","bks":[{"bnf":"0","bnc":"10000","mmr":"0.0065","cf":"0","mi":1,"ma":75}]})
    assert s.ready_for("ETHUSDT")
    assert s.source == "contract_updates_only"
    b=s.select("ETHUSDT",500)
    assert b.max_leverage == 75
