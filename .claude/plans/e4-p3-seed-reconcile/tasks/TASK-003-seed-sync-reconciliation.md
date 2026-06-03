# TASK-003: Seed-sync reconciliation

Depends on: TASK-002
Suggested commit: `feat(scripts): seed-sync reconciliation (drop seed rows on fully-synced days)`

## Goal

Add `scripts/reconcile_seed.py` — a one-time, idempotent reconciliation (run after the first live syncs) that
drops `origin='seed'` rows for any Europe/Sofia day fully covered by `'sync'` data, keeping `'sync'` rows and
partially-covered seed days.

## Files

- `scripts/reconcile_seed.py` — **new** (offline maintenance; plain `sqlite3` + `app.core.time`; opens **only
  `app.db`**, never `baseline.db`):
  - `reconcile_seed(conn) -> dict[str, int]`:
    - **Rule** (the phase's decision): a Sofia day **D is "fully covered" iff ≥1 `origin='sync'` row exists
      whose Sofia day is D** → drop **all** `origin='seed'` rows on D in the **origin-bearing** tables. Days
      with no sync row keep their seed rows; **`'sync'` rows are never deleted**.
    - **Scope = `records` + `workouts` only.** `activity_summary` has **no `origin`** and is upserted by the
      `date` PK (DB.md §1), so a live `/sync` for a day already overwrote that day's seed row — there is
      nothing to delete; it is **excluded** from reconciliation. `workout_statistics` has no `origin` either
      — it follows its parent workout.
    - Day key: `period_date(start_date)` (Sofia, via `app/core/time.py`) for `records`/`workouts`.
    - Compute `covered_days = { Sofia-day of every 'sync' row in records ∪ workouts }`, then:
      - `workouts`: for each seed (`origin='seed'`) workout whose Sofia day ∈ covered_days, **delete its
        child `workout_statistics` first** (FK has no `ON DELETE CASCADE`, `foreign_keys=ON`; round-1 #2),
        then delete the workout.
      - `records`: delete `origin='seed'` rows whose Sofia day ∈ covered_days.
    - Return per-table deleted counts (`records`, `workouts`, `workout_statistics`).
  - `main(argv)` — `argparse` `--app-db` (default `app.core.settings` `app_db_path`); opens `app.db`, runs
    `reconcile_seed`, prints the per-table deleted-row report.
- `tests/scripts/test_reconcile_seed.py` — **new**: on a temp migrated `app.db`, insert **seed** rows (via
  TASK-002's `seed` or direct inserts) across several Sofia days, then insert **`'sync'`** rows overlapping
  **some** of those days (a "fully covered" day) but **not** others (a "partial" day with seed only). Run
  `reconcile_seed`; assert the criteria below.

## Acceptance

- [ ] **Fully-covered seed days dropped** — after reconciliation, no `origin='seed'` row remains in `records`
      or `workouts` on any Sofia day that has ≥1 `origin='sync'` row.
- [ ] **`'sync'` rows untouched** — every `origin='sync'` row present before reconciliation is still present
      after (count + identity unchanged).
- [ ] **Partial-day seed rows kept** — `origin='seed'` rows on a Sofia day with **no** sync row survive.
- [ ] **`workout_statistics` follows its parent** — a seed `workout` deleted on a covered day has its child
      `workout_statistics` deleted **first** (no orphaned stats, no FK error); stats under a kept seed
      workout remain.
- [ ] **`activity_summary` untouched** — reconciliation does not query/delete `activity_summary` (it has no
      `origin`; the date-PK upsert already resolved seed/sync).
- [ ] **Idempotent** — a second `reconcile_seed(conn)` run deletes 0 rows (returns all-zero counts).

## Steps

### RED
- [ ] `tests/scripts/test_reconcile_seed.py`: build a temp migrated `app.db`; seed rows on days D1 (will be
      sync-covered) and D2 (seed-only); insert `'sync'` rows on D1 only; run `reconcile_seed`; assert D1 seed
      rows gone, D2 seed rows kept, all `'sync'` rows present, orphaned stats removed; run again → 0 deletes.
      (Fails — script doesn't exist.)

### GREEN
- [ ] Implement `reconcile_seed` (compute covered Sofia days from `'sync'` `records`/`workouts` via
      `app/core/time`, delete `origin='seed'` rows on those days in `records`/`workouts`, deleting child
      `workout_statistics` **before** their parent seed workouts; `activity_summary` excluded) and
      `main`/`argparse`. Smallest code to pass.

### REFACTOR
- [ ] Factor the covered-day computation + per-table delete into small helpers; keep the `origin` filter
      explicit so `'sync'` rows can never be touched; ensure the run is a single transaction and idempotent.

## Notes

This **resolves DB.md §7's open item** ("drops `'seed'` rows for any day fully covered by synced data —
*Needs a decision*"). The decided rule: **fully covered iff ≥1 `'sync'` row that Sofia day** → drop the whole
day's seed (live HealthKit supersedes the seed estimate for a day it synced); a day with **no** sync row keeps
its seed (partial = not covered). **Per-type** coverage was rejected (would mix seed+sync for the same metric
on one day; the epic frames coverage per **day**). `workout_statistics` has **no `origin`** — it is removed by
deleting its parent seed `workout`, never by an `origin` filter (DB.md §1). The op is **one-time after the
first syncs** and **idempotent**: once a covered day's seed is gone, a re-run deletes 0. It opens **only
`app.db`** — `baseline.db` is not touched here (DB.md §0; ARCHITECTURE §6). Day keys come from E2·P1's
`period_date` (Europe/Sofia), never a fixed offset (DB.md §0).
