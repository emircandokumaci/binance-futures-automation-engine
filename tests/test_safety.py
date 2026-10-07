import pytest
from app.safety import enforce_phase_one_safety
from app.settings import Settings


def test_phase_one_accepts_paper_only():
    enforce_phase_one_safety(Settings(database_url='postgresql://x:x@localhost/x'))


def test_phase_one_refuses_live():
    cfg = Settings(database_url='postgresql://x:x@localhost/x', trading_mode='live', live_trading_enabled=True)
    with pytest.raises(RuntimeError):
        enforce_phase_one_safety(cfg)
