# Local-dev runner for the Coach App backend — just `uv` + `just`, no containers.
# Bare `just` lists every recipe. See the README "Local development" section.
#
# Note: no file-wide `dotenv-load` — that would promote a developer's local .env into
# every recipe's env and make `just test` non-deterministic. Only `db-reset` reads .env
# (scoped), to resolve the same DB path the app/Alembic use before deleting it.

# List all recipes (runs when `just` is invoked with no arguments).
_default:
    @just --list

# Install / sync dependencies (uv-managed, Python 3.13).
install:
    uv sync

# Run the dev server with auto-reload (production/E12 uses the bare entry point).
run:
    uv run uvicorn app.main:app --reload

# Run the test suite.
test:
    uv run pytest

# Lint the project.
lint:
    uv run ruff check .

# Format the project.
fmt:
    uv run ruff format .

# --- Lifecycle (forward-declared; light up as E2/E4 land) --------------------

# Apply DB migrations. (E2·P1 — runnable once Alembic lands.)
migrate:
    uv run alembic upgrade head

# Build + derive + seed the local DB from the offline sources. (E4 — runnable once the scripts land.)
seed:
    uv run python scripts/build_db.py
    uv run python scripts/derive_constants.py
    uv run python scripts/seed_app_db.py

# Full first-run bootstrap: install, migrate, then seed. (E2+E4.)
bootstrap: install migrate seed

# Delete the local app.db (+ -wal/-shm) for the configured APP_DB_PATH, then re-migrate.
db-reset:
    #!/usr/bin/env bash
    set -euo pipefail
    # Resolve APP_DB_PATH through the app's OWN pydantic-settings (a tiny BaseSettings that
    # reuses Settings.model_config), so .env parsing, case-insensitive env matching, and
    # process-env > .env precedence are IDENTICAL to runtime — there is no "format/case the
    # app accepts but db-reset doesn't" gap. The shared forbidden-DB guard runs before any rm.
    # Only this recipe reads .env, so `just test` stays deterministic.
    DB="$(uv run python - <<'PY'
    import sys
    from pydantic_settings import BaseSettings
    from app.core.settings import Settings, _db_target_basename, _FORBIDDEN_DB_BASENAMES

    class _Resolver(BaseSettings):
        model_config = Settings.model_config
        app_db_path: str = "app.db"

    path = _Resolver().app_db_path.strip()
    if not path:
        sys.exit("db-reset: APP_DB_PATH is empty; refusing")
    if _db_target_basename(path) in _FORBIDDEN_DB_BASENAMES:
        sys.exit(f"db-reset: refusing to delete the read-only build DB ({path})")
    print(path)
    PY
    )" || exit 1
    rm -f -- "$DB" "$DB-wal" "$DB-shm"
    just migrate

# --- Environment -------------------------------------------------------------

# Create .env from .env.example (only when .env is absent; never overwrites).
env:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -f .env ]; then
        echo "env: kept existing .env"
    else
        cp .env.example .env
        echo "env: created .env from .env.example — set API_TOKEN before running"
    fi
