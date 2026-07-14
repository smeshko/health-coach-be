#!/bin/sh
# Seed-branch demonstration for scripts/seed_profile.sh (Phase 19.7) — NO Docker daemon.
#
# Exercises BOTH branches of the first-boot seed the container entrypoint runs:
#   A. Fresh volume (no /data/profile.yaml) → the baked default is copied in, byte-equal.
#   B. Pre-existing durable file (a recomputed profile.yaml) → left UNTOUCHED, never clobbered.
#      A second run is a no-op (idempotent), proving a redeploy can't revert a successful write.
# Runs unprivileged (no root/sudo) and under `set -eu`, mirroring the non-root `app` user.
#
# Usage:  sh scripts/profile_seed_smoke.sh   (from the repo root)  → exits 0 iff both branches pass.
set -eu

HERE="$(CDPATH= cd "$(dirname "$0")" && pwd)"
SEED_SCRIPT="$HERE/seed_profile.sh"
PASS=0
FAIL=0

check() {  # check "<label>" "<condition-exit>"
    if [ "$2" = "0" ]; then
        echo "  PASS: $1"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $1"
        FAIL=$((FAIL + 1))
    fi
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# A fake baked default with known content (stands in for /app/profile.yaml).
DEFAULT="$WORK/baked-default.yaml"
printf 'seed_source: baked-default\nconstitution_version: v1\n' > "$DEFAULT"

echo "== branch A: fresh volume → seeded byte-equal to baked default =="
TARGET_A="$WORK/data-fresh/profile.yaml"   # parent dir does not exist yet
rc=0; SEED_PROFILE="$DEFAULT" PROFILE_PATH="$TARGET_A" sh "$SEED_SCRIPT" || rc=$?
check "seed_profile.sh exited 0 on a fresh path" "$rc"
[ -f "$TARGET_A" ]; check "target file was created" "$?"
cmp -s "$DEFAULT" "$TARGET_A"; check "seeded file is byte-equal to the baked default" "$?"

echo "== branch B: pre-existing durable file → left untouched (never clobbered) =="
TARGET_B="$WORK/data-existing/profile.yaml"
mkdir -p "$(dirname "$TARGET_B")"
printf 'seed_source: RECOMPUTED-DO-NOT-CLOBBER\nconstitution_version: v9\n' > "$TARGET_B"
SENTINEL="$(cat "$TARGET_B")"
rc=0; SEED_PROFILE="$DEFAULT" PROFILE_PATH="$TARGET_B" sh "$SEED_SCRIPT" || rc=$?
check "seed_profile.sh exited 0 on a pre-existing path" "$rc"
[ "$(cat "$TARGET_B")" = "$SENTINEL" ]; check "pre-existing file content is unchanged" "$?"

echo "== branch B (idempotent): a second run is still a no-op =="
rc=0; SEED_PROFILE="$DEFAULT" PROFILE_PATH="$TARGET_B" sh "$SEED_SCRIPT" || rc=$?
check "second run exited 0" "$rc"
[ "$(cat "$TARGET_B")" = "$SENTINEL" ]; check "content still unchanged after re-run" "$?"

echo "== summary: ${PASS} passed, ${FAIL} failed =="
[ "$FAIL" -eq 0 ]
