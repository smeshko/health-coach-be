# TASK-004: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for e1-p4-local-dev-runner`

## Goal

Confirm the plan is fully implemented and production-ready, with a concrete, non-circular check for every
PLAN.md acceptance criterion. Stack is Python 3.13 / `uv` / `just` (no Flutter).

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked.
- [ ] **Lint:** `uv run ruff check .` passes with no issues.
- [ ] **Tests:** `uv run pytest` passes (the E1 scaffold suite is green; this phase adds no app code).
- [ ] **justfile parses:** `just --list` exits 0 (no syntax errors).

### Per PLAN.md acceptance criterion (1:1)

- [ ] **AC1 — bare `just` and `just --list` list every recipe** — `just` with no args and `just --list`
      both print: `install`, `run`, `test`, `lint`, `fmt`, `migrate`, `seed`, `bootstrap`, `db-reset`,
      `env`; the `_default` recipe is hidden (`_` prefix). Check:
      `diff <(just 2>&1) <(just --list 2>&1)` is empty, and
      `for r in install run test lint fmt migrate seed bootstrap db-reset env; do just --list | grep -qw "$r" || echo "MISSING $r"; done`
      prints nothing.
- [ ] **AC2 — core recipes work against the E1 scaffold now** — `just --show run` prints exactly
      `uv run uvicorn app.main:app --reload`; `just --show install` → `uv sync`; `just --show lint` →
      `uv run ruff check .`; `just --show test` → `uv run pytest`; `just --show fmt` → `uv run ruff format .`.
      Then actually run `just install`, `just lint`, `just test` (all exit 0). Manual: `just run` then
      `curl -s localhost:8000/health` returns `200` (serves E1·P2 health).
- [ ] **AC3 — forward recipes invoke the correct future commands** — `just --show migrate` →
      `uv run alembic upgrade head`; `just --show seed` contains `scripts/build_db.py`,
      `scripts/derive_constants.py`, and `scripts/seed_app_db.py` (each via `uv run python`);
      `just --show bootstrap` shows the `install`→`migrate`→`seed` chain; `just --show db-reset` shows a
      shebang single-block recipe resolving `DB="${APP_DB_PATH-app.db}"` and `rm -f --`ing
      `"$DB" "$DB-wal" "$DB-shm"` followed by `migrate`. (Forward-command tails asserted via `--show`/`-n`,
      NOT run end-to-end — Alembic/E4 scripts land later.)
- [ ] **AC4 — `.env` bootstrap is non-clobbering** — in a temp dir with `.env.example` present and `.env`
      absent, `just env` creates `.env` (byte-equal to `.env.example`); with a sentinel `.env` present,
      re-running `just env` leaves it unchanged (`diff` empty) and prints the "kept existing .env" notice.
      Guard: `grep -E 'test +-?f +\.env|\[ +-f +\.env' justfile` confirms the `if-missing` guard exists.
- [ ] **AC5 — README "Local development" section** — `grep -n "## Local development" README.md` matches;
      the section documents **two flows** — the E1-now `just install` → `just env`/set `.env` → `just run`
      → `curl /health` order (no `migrate`, completes today) and the post-E2/E4 full flow inserting
      `just migrate`/`just bootstrap`; every recipe name appears in the README recipe reference:
      `for r in install run test lint fmt migrate seed bootstrap db-reset env; do grep -qw "$r" README.md || echo "MISSING-IN-README $r"; done`
      prints nothing; the forward recipes are annotated with E2/E4 (`grep -nE "E2|E4" README.md` in the
      section).
- [ ] **AC6 — no Docker/litestream/migrate-on-startup introduced** (scoped to **this phase's surface**, not
      the whole repo — existing architecture/epic docs already mention litestream/Docker, round-1 #3):
      `grep -iE "litestream" justfile` returns nothing; `grep -icE "docker" justfile` is `0`; in `README.md`
      the only `docker`/`litestream` mention permitted is the single negative "Docker is not used for local
      dev (deployment-only, E12)" note (`grep -inE "docker|litestream" README.md` shows only that line);
      `git status --short` lists no new `Dockerfile`/`docker-compose.yml`/`compose.yaml`/litestream config;
      and `git diff` introduces no migrate-on-startup (the app boot path is untouched by this phase).

### Cross-cutting

- [ ] **README ↔ justfile parity** — every recipe documented in README exists in `justfile` and vice versa
      (the two `for`-loop greps in AC1/AC5 cover both directions).
- [ ] **`db-reset` is safe** — it is a single shebang shell block (`grep -n '#!/usr/bin/env bash' justfile`
      and `grep -n 'set -euo pipefail' justfile` present in the `db-reset` body), resolves
      `DB="${APP_DB_PATH-app.db}"` (`-`, not `:-`), refuses empty (`[ -z` / `[ -n` check) and `baseline.db`,
      and `rm -f --`s only `"$DB" "$DB-wal" "$DB-shm"` (no `*.db` glob:
      `grep -nE 'rm .*\*\.db|rm .*\*' justfile` is empty). Behaviour: (a) unset `APP_DB_PATH` + sentinel
      `app.db`/`-wal`/`-shm` → removed; (b) `APP_DB_PATH=` → non-zero exit, nothing deleted;
      (c) `APP_DB_PATH=/tmp/coachtest.db` + sentinels → removed; (d) `APP_DB_PATH=baseline.db` → refused,
      nothing deleted. (The trailing `just migrate` may fail pre-E2 — assert the `rm` ran first.)
- [ ] **No app/source code changed** — this phase only adds `justfile`, a README section, and (at most)
      an appended `.env.example` var; `git status --short` shows no edits under `app/` or `tests/`.
- [ ] `PLAN.md` acceptance criteria all met.
