# Plan: Backend persistence integrity (Phase 19.5)

Status: done
Branch: fix/phase-19-5-persistence-integrity
Risk: medium
Epic: 19 — Make the numbers trustworthy (audit wave 2, iOS repo docs/artifacts/epics/19-trustworthy-numbers.md)
Phase: 19.5 — Backend persistence integrity
Created: 2026-07-13

## Goal
Three independent persistence fixes, each a wire-up of an existing pattern:
1. The readiness/band snapshot is written with a bare `UPDATE` that silently no-ops when no
   `daily_metrics` row exists for the brief day (a brief requested before that day synced).
2. The post-commit `profile.yaml` write is un-retried — a transient failure permanently
   diverges the cached plan from its constants.
3. `workouts.start_date` has no index, yet every hot query filters workouts by date range.

## Scope
- `app/core/daily_adjuster.py` — replace the bare `update(DailyMetrics)…` in `_persist_brief`
  with an idiomatic `sqlite insert(...).on_conflict_do_update(index_elements=["date"], …)`
  (the exact precedent is `daily_metrics_engine.py:_upsert_daily_metrics`) so the readiness
  snapshot lands even when the row is absent (other columns stay NULL / preserved).
- `app/api/routes/weekly.py` — wrap `write_profile(pending)` in a small bounded retry; on
  final failure log a loud error (surfaced for reconciliation) and re-raise. Sync handler, so
  a brief `time.sleep` backoff is safe.
- `app/database/models/workouts.py` + `alembic/versions/0005_*` — add
  `Index(None, "start_date")` (mirroring `records.py`) and a `0005` migration off head `0004`
  (`op.create_index(op.f("ix_workouts_start_date"), "workouts", ["start_date"])`).

## Out of Scope
- A durable pending-profile-write queue that re-applies on the next request (a bounded retry
  is the epic's stated minimal fix; a persistent fs failure is logged for manual reconcile).
- Backend deterministic-invariant repair (Phase 19.4, merged) and runtime max-HR (Phase 19.6).

## Research Summary
Grounded (file:line) in the Phase 19.4 research pass. Upsert precedent:
`daily_metrics_engine.py:715` (`on_conflict_do_update(index_elements=["date"])`, same table +
PK). `daily_metrics.date` is the single-col PK; all other columns are nullable, so a
snapshot-only insert is valid. Hot `start_date` scans: `daily_metrics_engine.py:233/565`,
`aggregates.py:366`. No existing index in the ORM/migrations (only the offline build script).
Alembic head is `0004` (after 19.4).

## Decisions
- **D1 — Readiness snapshot via `on_conflict_do_update` on the `date` PK**, mirroring the
  engine's `_upsert_daily_metrics`; only `readiness_score`/`band` are written, so the metrics
  engine's `PRESERVED_COLUMNS` semantics are unaffected.
- **D2 — Bounded retry (not a durable queue) for `write_profile`**; loud error + re-raise on
  exhaustion so a persistent divergence is visible, not silent.
- **D3 — In-model `Index` + a `0005` migration**, mirroring `records.py`, so
  `alembic check`/`compare_metadata` stays clean.

## Acceptance Criteria
- [x] A brief for a day with NO `daily_metrics` row persists its readiness snapshot (a row is
  created with `readiness_score`/`band` set) — failing-then-passing shown.
- [x] A brief for a day WITH a metrics row updates the snapshot without clobbering the row's
  other columns (preserved).
- [x] A transient `write_profile` failure is retried and succeeds; a persistent failure logs
  an error and re-raises (pinned by a test).
- [x] `workouts.start_date` is indexed: migration `0005` creates `ix_workouts_start_date`,
  the ORM carries the `Index`, and `compare_metadata` is clean after `upgrade head`.
- [x] `just test` green; `just lint` clean.

## Tasks
- [x] TASK-001: readiness snapshot upsert (no silent drop)
- [x] TASK-002: bounded retry for the post-commit profile.yaml write
- [x] TASK-003: workouts.start_date index + migration 0005
- [x] TASK-004: Final validation
