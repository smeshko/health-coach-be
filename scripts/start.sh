#!/bin/sh
# Native (macOS home-server) start script for the Coach App backend.
#
# Boot order, hardened for "app.db is the only durable copy and the phone never re-pushes
# history" (RELEASE-READINESS-TODO.md):
#   1. restore app.db from the litestream replica if it is missing (disk loss / fresh host)
#   2. REFUSE TO BOOT EMPTY — never let Alembic create+serve a blank DB (silent data hole)
#   3. (optional) restore profile.yaml from its snapshot dir if missing (litestream can't cover YAML)
#   4. alembic upgrade head
#   5. reconcile seed<->sync overlap (idempotent; no-op until there is overlap)
#   6. exec the server UNDER litestream so app.db's WAL streams to B2 the whole time it runs
#
# Config comes from the process environment (set by the launchd plist, or exported manually).
# Required: APP_DB_PATH, API_TOKEN, and the LITESTREAM_*/AWS_* vars litestream.yml expands.
set -eu

VENV="${UV_PROJECT_ENVIRONMENT:-.venv}"
LITESTREAM_CONFIG="${LITESTREAM_CONFIG:-litestream.yml}"
: "${APP_DB_PATH:?APP_DB_PATH must be set}"

# Bind loopback-only by default: with a cloudflared tunnel (or any local reverse proxy) the
# ingress connects to 127.0.0.1, so the API is NOT exposed on the LAN. Override BIND_HOST
# (e.g. 0.0.0.0 or a tailnet IP) only if something other than a local proxy must reach it.
BIND_HOST="${BIND_HOST:-127.0.0.1}"
BIND_PORT="${BIND_PORT:-8000}"

# 1. Restore from the replica if app.db is absent. litestream won't overwrite an existing DB;
#    -if-replica-exists makes "no replica yet" a clean no-op (so the very first boot of a
#    freshly-seeded DB proceeds instead of erroring under `set -e`).
if [ ! -f "$APP_DB_PATH" ]; then
  echo "[start] $APP_DB_PATH missing — attempting litestream restore"
  litestream restore -if-replica-exists -config "$LITESTREAM_CONFIG" "$APP_DB_PATH" || true
fi

# 2. Never boot empty. If the DB is STILL absent, refuse — do not let `alembic upgrade head`
#    materialise a blank DB and serve it. The iOS app only sends go-forward deltas, so a
#    silent empty boot is a permanent, unrecoverable data hole. First-ever deploy must seed
#    app.db first (`just bootstrap`).
if [ ! -f "$APP_DB_PATH" ]; then
  echo "[start] FATAL: $APP_DB_PATH does not exist and no replica restored it." >&2
  echo "[start] Refusing to create an empty database. Seed it first (just bootstrap)" >&2
  echo "[start] or fix the litestream replica config, then restart." >&2
  exit 1
fi

# 3. profile.yaml holds runtime-mutated coaching constants and lives nowhere else; litestream
#    only replicates SQLite. If it is missing and a snapshot dir is configured, restore the
#    newest snapshot (see scripts/backup_profile.sh). Otherwise the loader fails loud — fine.
PROFILE_FILE="${PROFILE_PATH:-profile.yaml}"
if [ ! -f "$PROFILE_FILE" ] && [ -n "${PROFILE_BACKUP_DIR:-}" ]; then
  latest="$(ls -t "$PROFILE_BACKUP_DIR"/profile-*.yaml 2>/dev/null | head -1 || true)"
  if [ -n "$latest" ]; then
    echo "[start] restoring profile.yaml from $latest"
    cp "$latest" "$PROFILE_FILE"
  fi
fi

# 4. Migrate the restored/seeded DB.
echo "[start] alembic upgrade head -> $APP_DB_PATH"
"${VENV}/bin/alembic" upgrade head

# 5. Reconcile seed<->sync overlap: drop seed rows on Europe/Sofia days the phone has since
#    synced (real-uuid sync rows supersede NULL-uuid seed estimates). Idempotent.
echo "[start] reconcile seed<->sync"
"${VENV}/bin/python" scripts/reconcile_seed.py

# 6. Serve under litestream supervision: ONE process tree, app.db's WAL streamed continuously,
#    and the server stops if litestream stops (and litestream stops when uvicorn exits, so
#    launchd KeepAlive restarts the whole tree cleanly).
echo "[start] starting uvicorn on ${BIND_HOST}:${BIND_PORT} under litestream replicate -exec"
exec litestream replicate -config "$LITESTREAM_CONFIG" \
  -exec "${VENV}/bin/uvicorn app.main:app --host ${BIND_HOST} --port ${BIND_PORT}"
