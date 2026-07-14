#!/bin/sh
# Seed the runtime profile.yaml onto the durable /data volume on FIRST boot (Phase 19.7).
#
# The recompute rewrites profile.yaml (the coaching constants) at PROFILE_PATH, which now
# lives on the durable /data volume (Dockerfile: ENV PROFILE_PATH=/data/profile.yaml). A fresh
# or empty volume has no such file yet, so on first boot we copy the image's baked default
# (/app/profile.yaml, the seed source + source-tree anchor) into place. The copy fires ONLY
# when the durable file is absent — an existing (recomputed) file is NEVER clobbered, so a
# redeploy can no longer revert a successful write.
#
# Idempotent and non-root-safe: /data is chown app:app and the baked default is app-readable,
# so the `cp` and later atomic writes (write_profile mkstemp in /data) succeed without root.
# The entrypoint calls this as a subprocess before `exec uvicorn`.
set -eu

PROFILE_PATH="${PROFILE_PATH:-/data/profile.yaml}"
SEED_PROFILE="${SEED_PROFILE:-/app/profile.yaml}"

mkdir -p "$(dirname "$PROFILE_PATH")"

if [ ! -f "$PROFILE_PATH" ]; then
    # A missing seed SOURCE is a real image defect — fail loudly (set -e) rather than boot
    # with no constants.
    cp "$SEED_PROFILE" "$PROFILE_PATH"
    echo "[entrypoint] seeded baked profile.yaml → $PROFILE_PATH (fresh volume)"
else
    echo "[entrypoint] profile.yaml already present at $PROFILE_PATH — leaving it untouched"
fi
