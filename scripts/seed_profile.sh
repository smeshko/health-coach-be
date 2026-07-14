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
    #
    # Seed ATOMICALLY (mirrors write_profile's mkstemp+os.replace): copy to a temp file in
    # the SAME dir, then `mv` (atomic rename on one filesystem). A bare `cp` is not atomic —
    # a SIGKILL/OOM mid-copy would leave a TRUNCATED $PROFILE_PATH, and the `[ ! -f ]` guard
    # would then permanently skip re-seeding it (the corrupt file "exists"), 500-ing every
    # recompute. With temp+rename, an interrupted seed leaves only the temp file, so the next
    # boot re-seeds cleanly (self-heal). set -e still fails loudly on a missing source.
    tmp="$(mktemp "${PROFILE_PATH}.seed.XXXXXX")"
    trap 'rm -f "$tmp"' EXIT
    cp "$SEED_PROFILE" "$tmp"
    mv "$tmp" "$PROFILE_PATH"
    trap - EXIT
    echo "[entrypoint] seeded baked profile.yaml → $PROFILE_PATH (fresh volume)"
else
    echo "[entrypoint] profile.yaml already present at $PROFILE_PATH — leaving it untouched"
fi
