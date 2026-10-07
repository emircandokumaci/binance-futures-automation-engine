#!/usr/bin/env bash
set -euo pipefail
cd /opt/jarvis/futures-engine
docker compose exec -T engine python -c "import os; from app.housekeeping import run_housekeeping; print(run_housekeeping(os.environ['DATABASE_URL']))"
