#!/bin/sh
# Coach App backend container entrypoint (E12·P2).
#
# (1) Apply Alembic migrations to the volume-mounted `app.db` (the DB lives on a mounted
#     volume that does not exist at build time, so migrations run on START, not at build).
# (2) `exec` ONE `uvicorn app.main:app` process so it becomes the container's main process
#     (PID 1) and receives signals (SIGTERM/SIGINT) cleanly — no lingering shell, no
#     `--workers`, no scheduler.
#
# Config is 100% env-driven via the E1 `Settings` (API_TOKEN / APP_DB_PATH / MODEL_ID /
# CONSTITUTION_VERSION / PROFILE_PATH / LANGFUSE_*). `create_app()` validates settings at
# import, so a missing required var fails the boot fast.
set -eu

# Call the venv binaries DIRECTLY (not `uv run`), so the migrate step is a clean
# foreground call and `exec uvicorn` makes uvicorn itself the container's main process
# (PID 1) — one process, signals handled directly, no `uv run` launcher lingering as a
# parent (which would otherwise show as a second "uvicorn app.main:app" command).
VENV="${UV_PROJECT_ENVIRONMENT:-/app/.venv}"

echo "[entrypoint] applying Alembic migrations to ${APP_DB_PATH:-/data/app.db}"
"${VENV}/bin/alembic" upgrade head

# Seed the runtime profile.yaml onto the durable /data volume on first boot only when
# absent (never clobbers a recomputed file). Subprocess form keeps this `set -eu`/exec flow
# intact; a missing seed source fails loudly (a real image defect).
echo "[entrypoint] seeding profile.yaml on the durable volume if absent"
sh /app/scripts/seed_profile.sh

echo "[entrypoint] starting uvicorn app.main:app on 0.0.0.0:8000 (single process)"
exec "${VENV}/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8000
