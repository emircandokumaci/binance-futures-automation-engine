#!/usr/bin/env bash
set -euo pipefail
MODE="${1:-daily}"
case "$MODE" in daily|weekly) ;; *) echo "mode must be daily or weekly" >&2; exit 2;; esac
PROJECT=/opt/jarvis/futures-engine
BASE=/opt/jarvis/backups/futures
DEST="$BASE/$MODE"
STAMP=$(TZ=Europe/Istanbul date +%Y%m%d-%H%M%S)
mkdir -p "$DEST"
DBFILE="$DEST/jarvis-futures-db-$STAMP.dump"
cd "$PROJECT"
docker compose exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$DBFILE"
test -s "$DBFILE"
sha256sum "$DBFILE" > "$DBFILE.sha256"
if [ "$MODE" = weekly ]; then
  git bundle create "$DEST/jarvis-futures-code-$STAMP.bundle" --all
  sha256sum "$DEST/jarvis-futures-code-$STAMP.bundle" > "$DEST/jarvis-futures-code-$STAMP.bundle.sha256"
  {
    echo "timestamp=$STAMP"
    echo "git_commit=$(git rev-parse HEAD)"
    echo "docker_images=$(docker compose images --format json | sha256sum | awk '{print $1}')"
    echo "secrets_included=false"
  } > "$DEST/manifest-$STAMP.txt"
fi
# Small local retention: Drive is the long-term target.
find "$BASE/daily" -type f -mtime +14 -delete 2>/dev/null || true
find "$BASE/weekly" -type f -mtime +70 -delete 2>/dev/null || true
# Optional Drive upload. It activates automatically after a one-time rclone OAuth remote named jarvisdrive is configured.
if command -v rclone >/dev/null 2>&1 && rclone listremotes 2>/dev/null | grep -qx 'jarvisdrive:'; then
  REMOTE="jarvisdrive:Jarvis Futures Backups/$( [ "$MODE" = daily ] && echo Daily || echo Weekly )"
  rclone copy "$DEST" "$REMOTE" --include "*-$STAMP.*" --transfers 2 --checkers 4 --drive-chunk-size 16M
  echo "drive_upload=ok" > "$DEST/last-upload-$MODE.status"
else
  echo "drive_upload=pending_server_oauth" > "$DEST/last-upload-$MODE.status"
fi
printf 'backup_ok mode=%s file=%s size=%s\n' "$MODE" "$DBFILE" "$(stat -c%s "$DBFILE")"
