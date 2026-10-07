from pathlib import Path


def test_housekeeping_only_targets_telemetry_tables():
    text = Path('app/housekeeping.py').read_text()
    assert 'reconciliation_snapshots' in text
    assert 'system_events' in text
    assert 'paper_positions' not in text
    assert 'shadow_candidates' not in text
    assert 'legacy_calibration_records' not in text
