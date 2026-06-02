# Validation Summary — e2-p2-ingest-tables

**Rounds:** 3 (stopped on approve)
**Plan status at validation:** draft
**Run on:** 2026-06-03

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 2        | 2       | 0        | 0        |
| 2     | 1        | 1       | 0        | 0        |
| 3     | 0        | 0       | 0        | 0        |

## Applied

### Round 1
- PLAN.md:Scope/Decisions/Acceptance, TASK-003, TASK-004 — declared `activity_summary.date` explicitly
  `NOT NULL` (a non-`WITHOUT ROWID` TEXT PRIMARY KEY is NULL-tolerant in SQLite, which would silently break
  the date upsert key); added a `PRAGMA table_info → notnull=1` assertion and a `date=NULL` insert-rejection
  test, mapped 1:1 in TASK-004 (round-1 #1).
- PLAN.md:Acceptance, TASK-002, TASK-004 — added a `workouts` NULL-uuid **seedability** acceptance criterion
  (two `uuid=NULL` rows must both insert — the E4 seed path) mirroring the `records` NULL-tolerance check,
  so a migration making `workouts.uuid` NOT NULL fails final validation instead of silently breaking seed
  (round-1 #2).

### Round 2
- TASK-004 — added a concrete `workout_statistics` columns/types mapping (`PRAGMA table_info` asserting `id`
  PK, `workout_id` INTEGER NOT NULL, `type` TEXT NOT NULL, dates TEXT, `sum`/`average`/`minimum`/`maximum`
  REAL, `unit` TEXT) so the existing PLAN.md column-set criterion is covered 1:1, not just the FK/index/
  orphan checks (round-2 #1).

### Round 3
- None — Codex returned **approve** with no material findings.

## Deferred

- None.

## Rejected

- None.
