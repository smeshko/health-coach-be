# Plan: E1·P4 — Local dev runner (justfile)

Status: in-progress
Branch: feature/e1-p4-local-dev-runner
Risk: small
Created: 2026-06-03

> Epic **E1 — Foundation & API Skeleton**, phase **P4** (Local dev runner). Source of truth:
> [`epics/E01-foundation.md`](../../../epics/E01-foundation.md) §3 "E1·P4" + §4 acceptance. Grounded in
> [`docs/architecture/ARCHITECTURE.md`](../../../docs/architecture/ARCHITECTURE.md) §1 (single synchronous
> `uvicorn` process; Docker/litestream are **optional deployment**, not local dev). Builds on **E1·P1**
> (the `uv` project + `uv run uvicorn app.main:app` entry point + canonical `.env.example`) and **E1·P2**
> (so `just run` serves `GET /health`). Forward recipes target commands defined in **E2·P1**
> (`uv run alembic upgrade head`) and **E4** (`scripts/build_db.py`, `scripts/derive_constants.py`,
> `scripts/seed_app_db.py`).

## Goal

Ship a repo-root `backend/justfile` (plus a `.env` bootstrap and a README "Local development" section) that
makes local development turnkey **without Docker** — wrapping the E1·P1 `uvicorn` entry point and
forward-declaring the migrate/seed/bootstrap recipes that light up as E2/E4 land.

## Scope

- A **`justfile`** at the repo root (`backend/justfile`) with a `_default` recipe (`@just --list`) so bare
  `just` lists every recipe with no args.
- **Core recipes that work against the E1 scaffold today** (runnable + testable now):
  - `install` → `uv sync`
  - `run` → `uv run uvicorn app.main:app --reload` (the E1·P1 entry point, with dev `--reload`)
  - `test` → `uv run pytest`
  - `lint` → `uv run ruff check .`
  - `fmt` → `uv run ruff format .`
- **Forward-declared lifecycle recipes** — authored now, calling the correct future commands; documented as
  depending on E2/E4 and not expected to fully run until those epics land:
  - `migrate` → `uv run alembic upgrade head` (E2·P1)
  - `seed` → the E4 bootstrap scripts (`uv run python scripts/build_db.py`,
    `scripts/derive_constants.py`, `scripts/seed_app_db.py`)
  - `bootstrap` → chains `install` → `migrate` → `seed`
  - `db-reset` → removes the local `app.db`/`app.db-wal`/`app.db-shm` (gitignored) then re-runs `migrate`
- **`.env` handling**: an `env` recipe that copies the canonical `.env.example` (owned by E1·P1) to `.env`
  **only if `.env` is missing** (never clobber, never commit a real `.env` — it's gitignored).
- A README **"Local development"** section with **two clearly separated flows**: (a) the **E1-now**
  clean-checkout flow that boots the scaffold today — `just install` → `just env` (set `.env`) →
  `just run` → `curl /health`; and (b) the **full flow after E2/E4** that inserts `just migrate` (and
  `just bootstrap`) once those epics land. Plus a one-line description per recipe and which recipes depend on
  which epics. (The two-flow split prevents documenting a first-run path that can't complete pre-E2 —
  round-1 #1.)

## Out of Scope

- **Docker / litestream / migrate-on-startup** — deployment-only, lives in **E12·P2**. This phase must not
  introduce a `Dockerfile`, compose file, litestream config, or any startup migration (ARCHITECTURE §1: the
  app is a single `uvicorn` process; Docker is optional and deferred).
- The underlying app/DB code the forward recipes call: the Alembic config (E2·P1) and the bootstrap scripts
  (E4·P1/P2/P3) are authored in their own phases; this phase only references their commands.
- Editing the canonical `.env.example` content beyond what E1·P1 already ships (E1·P1 owns it; this phase
  consumes it). If a variable is genuinely required for `just run`/`just migrate` and is missing from the
  E1·P1 `.env.example`, append it here — but do not rewrite the file.
- CI wiring, pre-commit hooks, task runners other than `just`.

## Research Summary

ARCHITECTURE §1 fixes the runtime as **one synchronous Python 3.13 `uvicorn` process** with an `app.db`
SQLite file; Docker is "optional (a single `api` container)" and `litestream` is the **deployment** backup
path — both explicitly deferred to E12, so local dev needs neither. The canonical local entry point set in
E1·P1 is `uv run uvicorn app.main:app`; this phase's `run` recipe wraps it with `--reload`. The forward
recipes mirror commands already specified by later phases: E2·P1's plan uses **`uv run alembic upgrade
head`** against `app.db` (URL derived from `settings.app_db_path`), and E4 defines the offline bootstrap
scripts **`scripts/build_db.py`** (E4·P1), **`scripts/derive_constants.py`**/`compute_zones.py` (E4·P2),
and **`scripts/seed_app_db.py`**/`reconcile_seed.py` (E4·P3). `app.db*` is gitignored (`.gitignore` lines
`*.db`/`*.db-wal`/`*.db-shm`), so `db-reset` only ever deletes local untracked files. `.env` is gitignored
too; E1·P1 owns the committed `.env.example`.

## Decisions

- **`justfile` (not a Makefile or shell scripts)** — the epic mandates `just` by name (E1·P4 title + §4
  acceptance). `just` is already on the dev box (`just 1.51.0`); recipes are self-documenting via
  `just --list` and forward recipes are inspectable via `just --show <recipe>` / `just -n <recipe>` even
  before the underlying tools exist — which is how this phase's acceptance is made observable without E2/E4.
- **`_default` recipe runs `@just --list`** — `just` invoked with no arguments runs the first recipe; making
  the first recipe a `_default` that lists satisfies "bare `just` lists recipes" (E1 §4). The `_` prefix
  hides it from its own listing.
- **`run` adds `--reload`; the bare `uvicorn app.main:app` stays the canonical/production invocation** —
  `--reload` is a dev-only convenience (auto-restart on edit); production/E12 uses the plain entry point.
  The recipe wraps, not replaces, the E1·P1 convention.
- **Forward recipes are authored now and call the exact future commands, but are not expected to fully run
  until E2/E4** — keeping them present (and asserting they invoke the right command via `--show`/dry-run)
  means E2/E4 only need to add code, not wire ergonomics. The README and a `justfile` comment flag the epic
  each depends on, so a developer running them early gets a clear "not ready yet" rather than confusion.
- **`env` recipe copies `.env.example` → `.env` only when `.env` is absent; never overwrites** — `.env`
  holds secrets (the API token) and is gitignored; clobbering it would destroy a developer's local config.
  Idempotent and safe to re-run.
- **`db-reset` is a single-shell-block (shebang) recipe that resolves the DB path from `APP_DB_PATH`
  (unset → `app.db`), refuses an empty/`baseline.db` path, then `rm -f --`s that file + its `-wal`/`-shm`
  siblings and re-migrates** — `settings.app_db_path` is the source of truth for the runtime DB (E1·P1) and
  the Alembic target (E2·P1), so hard-coding `app.db` would delete the wrong file when a developer overrides
  `APP_DB_PATH`. Two operational subtleties make this a **shebang recipe** (`#!/usr/bin/env bash`, one
  shell), not multiple recipe lines: (a) `just` runs each plain recipe line in its own process, so `DB=…`
  set on one line would not survive to the guard/`rm` on the next; one shell block keeps them together. (b)
  The fallback uses `${APP_DB_PATH-app.db}` (**unset** → `app.db`) **not** `${APP_DB_PATH:-app.db}`, so an
  **explicitly empty** `APP_DB_PATH` stays empty and is caught by an explicit `[ -z "$DB" ]` refusal rather
  than silently collapsing to `app.db`. Body: `set -euo pipefail`; `DB="${APP_DB_PATH-app.db}"`; refuse if
  empty; refuse if `$DB` basename is `baseline.db` (a read-only build input, ARCHITECTURE §3);
  `rm -f -- "$DB" "$DB-wal" "$DB-shm"` (explicit siblings, never a glob, `--` stops option parsing); then
  `just migrate`. No-op when files are absent; all three artifacts are gitignored
  (`*.db`/`*.db-wal`/`*.db-shm`) so nothing tracked is ever touched (round-1 #2, round-2 #1). Verified: the
  recipe deletes the configured DB, refuses empty `APP_DB_PATH` and `baseline.db`.
- **No Docker/litestream in this phase** — ARCHITECTURE §1 marks them optional/deployment; the epic NOTES
  put them in E12·P2. Local dev is just `uv` + `just`.

## Risks

- **Forward recipes mislead a developer into thinking E2/E4 features work** — mitigation: each forward
  recipe carries an inline `# (E2)` / `# (E4)` comment and an `@echo` note where useful; the README's recipe
  table states the owning epic; acceptance only asserts the recipe **exists and invokes the right command**
  (via `just --show`/`just -n`), not that it succeeds end-to-end.
- **`db-reset` deleting a tracked or wrong file** — mitigation: it is a single shebang shell block that
  resolves `DB="${APP_DB_PATH-app.db}"` (unset→fallback; explicit-empty refused), refuses `baseline.db`, and
  `rm -f --`s only `"$DB" "$DB-wal" "$DB-shm"` (all gitignored), never a glob; final-validation greps the
  recipe for the shebang/`set -euo pipefail`/`-z` empty-check/`baseline.db` guard/`rm -f --` and runs
  behaviour checks for unset, explicit-empty, and a custom `APP_DB_PATH` (round-1 #2, round-2 #1).
- **`env` recipe clobbering an existing `.env`** — mitigation: guarded by a `test ! -f .env` (copy only when
  missing); re-running is a no-op that prints a "kept existing .env" notice.
- **Duplicating E12 deployment surface** — mitigation: final-validation scopes the check to **this phase's
  surface** (no `Dockerfile`/compose/litestream files in `git status`; no `docker`/`litestream` refs in
  `justfile`; only the allowed single negative "Docker not used locally" note in the README) — **not** a
  repo-wide grep, since existing architecture/epic docs already mention litestream/Docker (round-1 #3).
- **Recipe drift from the real entry point/commands** — mitigation: `run` uses the exact `app.main:app`
  target from E1·P1, `migrate` uses `alembic upgrade head` from E2·P1, and `seed` uses the E4 script paths;
  acceptance greps for these literals.

## Acceptance Criteria

- [ ] `just` with **no arguments** lists all recipes (the `_default` recipe runs `@just --list`); `just
      --list` shows: `install`, `run`, `test`, `lint`, `fmt`, `migrate`, `seed`, `bootstrap`, `db-reset`,
      `env`.
- [ ] **Core recipes work against the E1 scaffold now**: `just install` runs `uv sync`; `just lint` runs
      `uv run ruff check .`; `just test` runs `uv run pytest`; `just fmt` runs `uv run ruff format .`; and
      `just run` invokes `uv run uvicorn app.main:app --reload` (serving `/health` from E1·P2). Verified by
      `just --show <recipe>` / `just -n <recipe>` dry-run and (for `install`/`lint`/`test`) actual runs.
- [ ] **Forward recipes exist and invoke the correct (future) commands**: `just --show migrate` →
      `uv run alembic upgrade head`; `just --show seed` → the E4 bootstrap scripts
      (`scripts/build_db.py`/`derive_constants.py`/`seed_app_db.py`); `just --show bootstrap` chains
      `install`→`migrate`→`seed`; `just --show db-reset` removes `app.db`/`-wal`/`-shm` then re-migrates.
      (Asserted via `--show`/`-n` because the underlying tools/scripts land in E2/E4.)
- [ ] **`.env` bootstrap**: `just env` copies `.env.example` → `.env` when `.env` is absent and is a no-op
      (does not overwrite) when `.env` already exists; a real `.env` is never committed (gitignored).
- [ ] **README "Local development"** section exists with two separated flows: the **E1-now** boot path
      (`just install` → `just env`/set `.env` → `just run` → `curl /health`) that completes on today's
      scaffold, and the **post-E2/E4 full flow** that inserts `just migrate`/`just bootstrap`; lists each
      recipe with one line, and notes which recipes depend on E2/E4.
- [ ] **No Docker/litestream/migrate-on-startup introduced** — no `Dockerfile`/compose/litestream files; the
      `justfile` contains no `docker`/`litestream` references (grep is empty).

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [x] TASK-001: justfile with core dev recipes (install, run, test, lint, fmt)
- [x] TASK-002: Forward-declared lifecycle recipes (migrate, seed, bootstrap, db-reset) and .env handling
- [ ] TASK-003: README Local development section
- [ ] TASK-004: Final Validation
