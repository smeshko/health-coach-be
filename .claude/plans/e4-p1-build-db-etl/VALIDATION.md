# Validation Summary — e4-p1-build-db-etl

**Rounds:** 2 (stopped on approve)
**Plan status at validation:** draft
**Run on:** 2026-06-03

> **codex unavailable — manual review.** Codex hit a hard usage/credits limit on every attempt across both
> rounds ("try again at 5:18 AM"). The `CODEX_DISABLE_IMAGE_GENERATION=1` / `OPENAI_IMAGE_MODEL=""` env fix
> was applied and the runtime got past the `gpt-image-2` bug — the failure was quota, not image-gen. Per
> the runbook fallback, both rounds are rigorous manual adversarial reviews challenging the same two axes
> (fidelity vs the cited architecture docs; internal coherence + final-validation coverage).

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 4        | 2       | 0        | 2        |
| 2     | 0        | 0       | 0        | 0        |

## Applied

### Round 1
- PLAN.md:Decisions, PLAN.md:Acceptance(Raw column shape) — explicitly reconciled the build-local
  `workouts.id` `INTEGER PRIMARY KEY AUTOINCREMENT` with ARCHITECTURE §3's literal "raw ETL dump: no PKs":
  it is the parent↔child FK-target join key for `workout_statistics` (mechanically required), **not** a
  runtime surrogate/`uuid`, and `records`/`activity_summary` still carry no PK — so the raw-dump rule holds
  (round-1 #1).
- PLAN.md:Decisions, PLAN.md:Risks, TASK-002 (acceptance, RED step, Notes) — made the idempotency-of-ids
  assumption explicit: `DROP TABLE` clears the table's `sqlite_sequence` row so the recreated AUTOINCREMENT
  `workouts.id` (and the FK `workout_statistics.workout_id`) restart at 1 and stay stable across rebuilds;
  the idempotency test compares table **contents incl. ids**, not raw file bytes (round-1 #2).

### Round 2
- None — manual re-review confirmed both round-1 applies are sufficient and consistent across PLAN ↔
  TASK-002, with no new defects and nothing introduced by the edits (approve).

## Deferred

- None.

## Rejected

- (round-1 #3) Add a `workout_events` table (the prior `../db/build_db.py` writes one) — DB.md §1's
  mirrored ingest set is exactly the four tables (`records`/`workouts`/`workout_statistics`/
  `activity_summary`) and the E4·P1 task list names only those; already documented as out of scope
  (PLAN.md Out of Scope + RESEARCH Uncertainty). Adding it would exceed scope.
- (round-1 #4) Assert the output `baseline.db` is byte-for-byte identical across runs — `ANALYZE` writes
  nondeterministic `sqlite_stat*` tables and SQLite's free-page layout isn't byte-stable, so a byte diff
  would be a false negative. The plan correctly scopes idempotency to per-table **counts + contents** (the
  epic R1/§4 sense of "identical `baseline.db`"); this reasoning is now baked into the Decisions/Risks.
