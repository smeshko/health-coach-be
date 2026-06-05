# syntax=docker/dockerfile:1
#
# Coach App backend — the single `api` container (ARCHITECTURE §1).
#
# ONE synchronous `uvicorn app.main:app` process over ONE `app.db` (SQLite/WAL) on a
# mounted volume. NO --workers, NO scheduler, NO Celery/cron. TLS + the private-network /
# Tailscale posture terminate at the EDGE — the container serves plain HTTP on :8000.
# Config is 100% environment-driven (no `.env` baked in; see `.env.docker.example`).
#
# uv-managed (ARCHITECTURE §1 Runtime = Python 3.13 + uv); installs from the committed
# `uv.lock` via `uv sync --frozen --no-dev` for a reproducible, dev-tool-free runtime.

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# Clean container logging + uv knobs (compiled bytecode, copy link-mode, the project
# venv at a stable path).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Cheapest-cache-first: install runtime deps from the COMMITTED lock before copying the
# app source, so this layer only re-resolves when pyproject/uv.lock change. `--frozen`
# fails on a stale lock (no silent re-resolve); `--no-dev` drops pytest/ruff/httpx;
# `--no-install-project` defers building the `app` wheel until the source is present.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# App source + the runtime inputs the app opens: `profile.yaml` (the constants source —
# must sit at /app so `app/core/profile.py`'s default `PROFILE_PATH = parents[2]/
# profile.yaml` resolves) and `alembic/`/`alembic.ini` (the entrypoint migrates the
# volume on start — added in the entrypoint below).
COPY app ./app
COPY alembic ./alembic
# `README.md` is referenced by pyproject's `readme = …`, so the hatchling wheel build needs it.
COPY alembic.ini profile.yaml README.md ./

# Install the project itself (the `app` package) into the venv now the source is present.
RUN uv sync --frozen --no-dev

EXPOSE 8000

# Single synchronous process — NO --workers, NO --reload (`--reload` is local-dev only).
# The migrate-on-start ENTRYPOINT + HEALTHCHECK + non-root USER + VOLUME land in TASK-002.
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
