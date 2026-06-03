# TASK-002: Copy trailing 90 days from baseline.db to app.db with origin=seed

Depends on: TASK-001
Suggested commit: `feat(scripts): seed trailing 90d from baseline.db into app.db (origin=seed)`

## Goal

Add `scripts/seed_app_db.py` — an offline build step that copies the trailing ~90 days of **whitelisted**
samples from the read-only `baseline.db` into `app.db`'s four ingest tables with `uuid=NULL`,
`origin='seed'`, and the `date_components`→`date` rename, idempotently.

## Files

- `scripts/seed_app_db.py` — **new** (offline; plain `sqlite3` + `app.core.healthkit` + `app.core.time`; no
  FastAPI/SQLAlchemy/Alembic):
  - `SEED_DAYS = 90`.
  - `seed(baseline_path, app_db_path, now, days=SEED_DAYS) -> dict[str, int]`:
    - Open `baseline.db` **read-only** (e.g. `sqlite3.connect("file:…?mode=ro", uri=True)`) and `app.db`
      read-write.
    - Compute the window: `end = period_date(now)`, `start = period_date(now − timedelta(days-1))` (or
      derive the inclusive lower bound the same Sofia way); a sample is **in-window** iff
      `period_date(start_date)` (Sofia, from `app/core/time.py`) is in `[start … end]`. `now` is a
      tz-aware datetime (Europe/Sofia) — pass it to the period helpers (which reject naive).
    - **Idempotency first** (for the origin-bearing tables): delete the child `workout_statistics` of seed
      workouts **first** (the FK has no `ON DELETE CASCADE`, `foreign_keys=ON`), then `DELETE FROM workouts
      WHERE origin='seed'`, then `DELETE FROM records WHERE origin='seed'`. `activity_summary` is NOT deleted
      here — it re-seeds via a `date`-PK **upsert** (below), so a re-run overwrites the same date rows.
    - **`records`**: select rows from `baseline.db.records` where `is_whitelisted(type)` **and** the row is
      in-window; insert into `app.db.records` copying every shared column + `uuid=NULL`, `origin='seed'`.
    - **`workouts`** (+ **`workout_statistics`**): for each in-window `baseline.db.workouts` row, insert into
      `app.db.workouts` (`uuid=NULL`, `origin='seed'`, `effort_score=NULL`, `physical_effort=NULL`), capture
      `cur.lastrowid`, then insert its child `baseline.db.workout_statistics` rows into `app.db` with
      `workout_id` = the new id. `workout_statistics` has **no `origin`** (DB.md §1) — it inherits its
      parent's seed status.
    - **`activity_summary`**: it has **no `origin` column** (DB.md §1) and is keyed by `date`. For each
      in-window `baseline.db.activity_summary` row, **upsert** into `app.db.activity_summary` mapping
      `date_components` → `date` (already a Sofia date) plus the rings/goals via `INSERT … ON CONFLICT(date)
      DO UPDATE …` (or `INSERT OR REPLACE`) — **no `origin`**. The date-PK upsert is what makes the re-seed
      idempotent and lets a later `/sync` overwrite the day by date.
    - Return per-table inserted/upserted counts.
  - `main(argv)` — `argparse`: `--baseline` (default sibling `../db/baseline.db`), `--app-db` (default
    `app.core.settings` `app_db_path`), `--now` (ISO date/datetime, default today Europe/Sofia via
    `app/core/time.py`), `--days` (default 90). Calls `seed`, prints the per-table report.
- `tests/scripts/test_seed_app_db.py` — **new**: build a tiny synthetic `baseline.db` (a few whitelisted +
  one non-whitelisted `records`, ≥1 in-window + ≥1 out-of-window sample incl. **DST-boundary near-midnight**
  rows, ≥1 workout with a child stat, ≥1 activity_summary day) and a temp `app.db` migrated with the E2·P2
  `ingest_tables` revision; run `seed(...)` with a fixed `--now`/`--days`; assert the criteria below. Helper
  to apply the E2·P2 Alembic migration (or create the four tables) on the temp `app.db`.

## Acceptance

- [ ] **Window bounds (Europe/Sofia, incl. DST)** — only samples whose Sofia `period_date(start_date)` is in
      `[period_date(now) − days + 1 … period_date(now)]` are seeded; an out-of-window sample is absent. A
      near-midnight `+0200` (winter) and `+0300` (summer) sample each land on the correct Sofia day and the
      correct side of the window.
- [ ] **`origin='seed'` + `uuid IS NULL`** — every seeded `records`/`workouts` row has `origin='seed'` and
      `uuid IS NULL`. (`activity_summary` has no `origin` — DB.md §1 — so it is not flagged.)
- [ ] **Whitelist filtering** — dietary types **and** `body_mass` records are present in seeded `records`; a
      non-whitelisted `type` (e.g. `…EnvironmentalAudioExposure`) is absent.
- [ ] **Three-delta copy** — seeded `activity_summary.date` equals the source `date_components` Sofia date
      (column renamed, addressable by the `date` PK; no `origin` column written); a seeded stat row's
      `workout_id` equals the inserted `workouts.id`; seed workouts have `effort_score`/`physical_effort` NULL.
- [ ] **Idempotent** — running `seed(...)` twice into the same `app.db` yields identical seeded rows (counts
      stable, no duplication, incl. the `activity_summary` date-PK upsert).

## Steps

### RED
- [ ] `tests/scripts/test_seed_app_db.py`: build the synthetic `baseline.db` + migrated temp `app.db`; call
      `seed(baseline, app_db, now=<fixed Sofia dt>, days=90)`; assert window/DST bounds, `origin`/`uuid`,
      whitelist present-vs-absent, the `date` rename + stats FK + NULL effort columns, and idempotency
      (call twice → identical rows). (Fails — script doesn't exist.)

### GREEN
- [ ] Implement `seed` (read-only baseline open, Sofia window via `app/core/time.period_date`, whitelist via
      `app.core.healthkit.is_whitelisted`, the four-table copy with the three deltas, the delete-then-recopy
      idempotency) and `main`/`argparse`. Smallest code to pass.

### REFACTOR
- [ ] Extract small per-table copy helpers; keep the `origin='seed'`/`uuid=NULL` constants explicit; ensure
      the baseline connection is opened read-only and closed. Batched inserts where natural.

## Notes

The copy is a **near-straight mirror** modulo exactly three deltas: `uuid`(=NULL), `origin`(='seed'),
`date_components`→`date` (DB.md §1, §6). **`origin` exists only on `records` + `workouts`** (DB.md §1):
`activity_summary` has no `origin` (it is one row per Sofia day, **upserted by the `date` PK**) and
`workout_statistics` has none (it inherits its parent workout). `effort_score`/`physical_effort` have no
`baseline.db` source → NULL on seed workouts (E2·P2 made them nullable; `/sync` backfills later —
ARCHITECTURE §6). The window is cut on **Europe/Sofia days** via E2·P1's `period_date` — never a fixed
`+03:00` (DB.md §0). The whitelist gates only `records.type`; `workouts`/`activity_summary` are seeded by
window. Idempotency: for `records`/`workouts` it is delete-`origin='seed'`-then-recopy (deleting child
`workout_statistics` **before** their parent workouts — the FK has no `ON DELETE CASCADE`, `foreign_keys=ON`,
round-1 #2); `activity_summary` re-seeds via its date-PK upsert. Tests use a tiny synthetic `baseline.db` +
a migrated temp `app.db` in `tmp_path` — never the real `../db/baseline.db`. `baseline.db` is opened
**read-only** and `app/` never imports this script (ARCHITECTURE §6; DB.md §0).
