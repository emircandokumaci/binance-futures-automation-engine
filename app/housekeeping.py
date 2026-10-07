from __future__ import annotations

import psycopg


def run_housekeeping(database_url: str) -> dict:
    """Prune high-volume operational telemetry only; never delete trade/calibration history."""
    with psycopg.connect(database_url) as conn:
        recon = conn.execute("DELETE FROM reconciliation_snapshots WHERE ts < NOW() - INTERVAL '30 days'").rowcount
        events = conn.execute("DELETE FROM system_events WHERE ts < NOW() - INTERVAL '180 days'").rowcount
    return {
        'reconciliation_snapshots_deleted': recon,
        'system_events_deleted': events,
    }
