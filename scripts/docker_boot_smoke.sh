#!/usr/bin/env bash
# Container build-and-boot smoke for the single `api` image (E12·P2 TASK-003).
#
# Builds the image, boots ONE container on a tmp volume with a real API_TOKEN, and asserts:
#   - GET /health → 200 (the unauthenticated liveness probe)
#   - the auth gate: /probe → 401 without the token, 200 with it
#   - EXACTLY ONE `uvicorn app.main:app` process (no --workers / no worker children)
#   - migrations applied on start (the alembic_version table exists in /data/app.db)
#   - the container runs as a non-root user
#   - fail-fast: a run WITHOUT API_TOKEN exits non-zero (env-driven config) rather than serving
# Then tears everything down. Exits 0 on success, non-zero on the first failed assertion.
#
# Usage:  bash scripts/docker_boot_smoke.sh   (run from the repo root; requires a docker daemon)
set -euo pipefail

IMAGE="coach-app-api:smoke"
NAME="coach-app-smoke-$$"
VOL="coach-app-smoke-vol-$$"
TOKEN="smoke-api-token-0123456789"
PASS=0
FAIL=0

cleanup() {
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker volume rm "$VOL" >/dev/null 2>&1 || true
}
trap cleanup EXIT

check() {  # check "<label>" "<actual>" "<expected>"
    if [ "$2" = "$3" ]; then
        echo "  PASS: $1 ($2)"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $1 (got '$2', expected '$3')"
        FAIL=$((FAIL + 1))
    fi
}

# In-container HTTP probe via python+urllib (the slim image has no curl/pgrep).
http_code() {  # http_code "<path>" ["<auth-token>"]
    local path="$1" token="${2:-}"
    docker exec "$NAME" python -c "
import sys, urllib.request, urllib.error
req = urllib.request.Request('http://127.0.0.1:8000${path}')
${token:+req.add_header('Authorization', 'Bearer ${token}')}
try:
    print(urllib.request.urlopen(req, timeout=3).status)
except urllib.error.HTTPError as e:
    print(e.code)
except Exception:
    print('000')
" 2>/dev/null || echo "000"
}

echo "== 1. docker build =="
docker build -t "$IMAGE" . >/dev/null
echo "  PASS: build exited 0"; PASS=$((PASS + 1))

echo "== 2. boot the container =="
docker run -d --name "$NAME" -e API_TOKEN="$TOKEN" -e APP_DB_PATH=/data/app.db \
    -v "$VOL":/data "$IMAGE" >/dev/null
# Wait for liveness (in-container).
up=0
for _ in $(seq 1 40); do
    if [ "$(http_code /health)" = "200" ]; then up=1; break; fi
    sleep 1
done
check "container came up" "$up" "1"
if [ "$up" != "1" ]; then echo "--- logs ---"; docker logs "$NAME" 2>&1 | tail -20; exit 1; fi

echo "== 3. assertions =="
check "GET /health" "$(http_code /health)" "200"
check "/probe without token" "$(http_code /probe)" "401"
check "/probe with token" "$(http_code /probe "$TOKEN")" "200"

# EXACTLY one uvicorn process (host-side docker top — no in-container pgrep needed).
procs="$(docker top "$NAME" 2>/dev/null | grep -c 'uvicorn app.main:app' || true)"
check "exactly one uvicorn process (no workers)" "$procs" "1"

# Migrations applied on start: the alembic_version table exists with a stamped revision.
migrated="$(docker exec "$NAME" python -c "
import sqlite3
try:
    c = sqlite3.connect('/data/app.db')
    print(1 if c.execute(\"select count(*) from alembic_version\").fetchone()[0] >= 1 else 0)
except Exception:
    print(0)
" 2>/dev/null || echo 0)"
check "migrations applied (alembic_version stamped)" "$migrated" "1"

# Non-root user.
check "runs as non-root user" "$(docker exec "$NAME" id -un 2>/dev/null)" "app"

# Fresh-volume profile.yaml seed (Phase 19.7): the entrypoint seeds the baked default onto
# the durable /data volume on first boot, and load_profile() (via ENV PROFILE_PATH) reads it.
seeded="$(docker exec "$NAME" /app/.venv/bin/python -c "
import os
from app.core.profile import load_profile
try:
    ok = os.path.isfile('/data/profile.yaml') and bool(load_profile().meta.constitution_version)
    print(1 if ok else 0)
except Exception:
    print(0)
" 2>/dev/null || echo 0)"
check "profile.yaml seeded on the durable volume and loads (Phase 19.7)" "$seeded" "1"

echo "== 4. fail-fast without API_TOKEN =="
ff_exit=0
ff_out="$(docker run --rm -e APP_DB_PATH=/data/app.db "$IMAGE" 2>&1)" || ff_exit=$?
# Assert BOTH a non-zero exit AND that the failure is the missing API_TOKEN (the pydantic
# validation error names the field) — so an unrelated crash can't false-pass this check.
if [ "$ff_exit" != "0" ] && printf '%s' "$ff_out" | grep -qi "api_token"; then
    echo "  PASS: missing API_TOKEN → non-zero exit ($ff_exit), did not serve (validation error names api_token)"
    PASS=$((PASS + 1))
else
    echo "  FAIL: missing API_TOKEN did not fail-fast on the token (exit $ff_exit)"
    FAIL=$((FAIL + 1))
fi

echo "== summary: ${PASS} passed, ${FAIL} failed =="
[ "$FAIL" -eq 0 ]
