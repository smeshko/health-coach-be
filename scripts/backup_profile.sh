#!/bin/sh
# Snapshot profile.yaml — the runtime-mutated coaching constants (HR zones / thresholds),
# rewritten monthly by the recompute and stored NOWHERE ELSE. litestream replicates only
# SQLite, so it cannot cover this YAML file; this job is its backup.
#
# Run periodically from launchd (deploy/launchd/com.coachapp.profile-backup.plist). Writes a
# timestamped copy into PROFILE_BACKUP_DIR (point it at an iCloud Drive or external-SSD path so
# the copy is offsite / survives the laptop dying) and keeps the most recent 48 snapshots.
set -eu

PROFILE_FILE="${PROFILE_PATH:-profile.yaml}"
: "${PROFILE_BACKUP_DIR:?PROFILE_BACKUP_DIR must be set (e.g. an iCloud Drive or external-SSD path)}"

if [ ! -f "$PROFILE_FILE" ]; then
  echo "[backup-profile] $PROFILE_FILE missing — nothing to back up" >&2
  exit 0
fi

mkdir -p "$PROFILE_BACKUP_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"
dest="$PROFILE_BACKUP_DIR/profile-$stamp.yaml"
cp "$PROFILE_FILE" "$dest"

# Retain the newest 48 snapshots; prune older ones.
ls -t "$PROFILE_BACKUP_DIR"/profile-*.yaml 2>/dev/null | tail -n +49 | while IFS= read -r old; do
  rm -f "$old"
done

# Optional: also push offsite to the same B2 bucket (requires awscli; uncomment + set PROFILE_S3_URI).
# [ -n "${PROFILE_S3_URI:-}" ] && aws s3 cp "$dest" "$PROFILE_S3_URI/profile-$stamp.yaml" \
#   --endpoint-url "${LITESTREAM_ENDPOINT:?}"

echo "[backup-profile] wrote $dest"
