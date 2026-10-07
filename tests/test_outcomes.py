from app.models import Side
from app.outcomes import evaluate_1m_path


def bar(high, low):
    return [0,"100",str(high),str(low),"100","1",59999,"0",1,"0","0","0"]


def test_long_tp_first():
    out=evaluate_1m_path(Side.LONG,100,98,105,[bar(102,99),bar(105.2,100)])
    assert out.status == 'TP_FIRST'
    assert out.mfe_r >= 2.5


def test_long_sl_first():
    out=evaluate_1m_path(Side.LONG,100,98,105,[bar(101,97.9)])
    assert out.status == 'SL_FIRST'
    assert out.mae_r >= 1


def test_both_hit_same_minute_is_ambiguous():
    out=evaluate_1m_path(Side.SHORT,100,102,95,[bar(102.1,94.9)])
    assert out.status == 'AMBIGUOUS'


def test_unresolved_path_tracks_excursions():
    out=evaluate_1m_path(Side.SHORT,100,102,95,[bar(101,98)])
    assert out.status == 'PENDING'
    assert out.mfe_r == 1.0
    assert out.mae_r == 0.5
