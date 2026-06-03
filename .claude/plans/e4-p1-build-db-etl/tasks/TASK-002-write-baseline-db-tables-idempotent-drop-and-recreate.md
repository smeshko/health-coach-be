# TASK-002: Write baseline.db tables (idempotent DROP and recreate)

Depends on: TASK-001
Suggested commit: `feat(scripts): write baseline.db raw tables with idempotent rebuild`

## Goal

Wire the TASK-001 stream into `../db/baseline.db`: create the four **raw** ingest-mirroring tables via
`DROP TABLE IF EXISTS … ; CREATE TABLE …` and batch-insert the parsed rows, so a re-run wholesale rebuilds
an identical corpus (idempotent).

## Files

- `scripts/build_db.py` — extend with the schema + write layer:
  - `init_schema(conn)` — `executescript` that does `DROP TABLE IF EXISTS records/workouts/
    workout_statistics/activity_summary;` then `CREATE TABLE` for the four **raw** tables (mirroring
    `../db/health.db`, the existing dump):
    - `records(type TEXT NOT NULL, unit TEXT, value REAL, value_text TEXT, source_name TEXT,
      source_version TEXT, device TEXT, creation_date TEXT, start_date TEXT NOT NULL, end_date TEXT)` —
      **no `id`/PK, no `uuid`, no `origin`**.
    - `workouts(id INTEGER PRIMARY KEY AUTOINCREMENT, activity_type TEXT NOT NULL, duration REAL,
      duration_unit TEXT, total_distance REAL, total_distance_unit TEXT, total_energy_burned REAL,
      total_energy_burned_unit TEXT, source_name TEXT, source_version TEXT, device TEXT, creation_date TEXT,
      start_date TEXT NOT NULL, end_date TEXT)` — `id` is the **local FK target only** (no `uuid`/`origin`/
      `effort_score`/`physical_effort`).
    - `workout_statistics(workout_id INTEGER NOT NULL, type TEXT NOT NULL, start_date TEXT, end_date TEXT,
      sum REAL, average REAL, minimum REAL, maximum REAL, unit TEXT)` — FK → `workouts(id)`.
    - `activity_summary(date_components TEXT NOT NULL, active_energy_burned REAL,
      active_energy_burned_goal REAL, active_energy_burned_unit TEXT, apple_exercise_time REAL,
      apple_exercise_time_goal REAL, apple_stand_hours INTEGER, apple_stand_hours_goal INTEGER,
      apple_move_time REAL, apple_move_time_goal REAL)` — keeps Apple's **`date_components`**.
  - `build(xml_path, db_path)` — open the connection, set bulk pragmas (`journal_mode=OFF`,
    `synchronous=OFF`, `temp_store=MEMORY`), `init_schema`, then consume `iter_health_elements`: buffer
    records / workout-statistics / activity-summaries and flush via `executemany` at a `BATCH` threshold.
    Insert each `Workout` immediately (`cur.lastrowid` → `workout_id` for its child statistics). Commit,
    build indexes (mirror the existing dump's indexes), run the `total_distance` backfill `UPDATE`,
    `ANALYZE`, close. Returns the per-table counts (consumed by TASK-003).
  - `main(argv)` — `argparse` with `--xml` (default `../db/export.xml`) / `--db` (default
    `../db/baseline.db`), resolved relative to the repo root; calls `build` then prints the report.
- `tests/scripts/test_build_db.py` — new: ETL the fixture through `build(fixture_xml, tmp_db)` and assert
  exact per-table counts, the **raw column shape** per table (`PRAGMA table_info`), timestamp fidelity,
  the `value`/`value_text` split, and `workout_statistics.workout_id` keys to its parent workout.
- `tests/scripts/test_build_db_idempotent.py` — new: run `build(...)` **twice** into the same `--db`; assert
  per-table counts stable, total rows unchanged (no duplication), and the second run's four-table contents
  equal the first's.

## Acceptance

- [ ] After `build(fixture, tmp_db)`, the four tables exist with the **exact** raw column sets above — no
      `uuid`/`origin`/`effort_score`/`physical_effort`, `records` has **no PK**, `activity_summary` has
      `date_components` (verified by `PRAGMA table_info`).
- [ ] Each of the four tables has the exact (>0) expected row count for the fixture.
- [ ] A stored `start_date` equals the fixture's raw Apple string (offset preserved, no normalization).
- [ ] A sleep-analysis record has its enum in `value_text` with `value` NULL; a quantity record has a
      numeric `value`.
- [ ] A `workout_statistics` row's `workout_id` equals the inserted workout's `id`.
- [ ] Running `build` twice into the same DB path yields stable counts, an unchanged total row count, and
      identical four-table contents **including `workouts.id` / `workout_statistics.workout_id`** (the
      AUTOINCREMENT ids are stable because `DROP TABLE` resets `sqlite_sequence`); the comparison is over
      table contents, not raw file bytes (round-1 #2, #4).

## Steps

### RED
- [ ] `tests/scripts/test_build_db.py`: `build(fixture, tmp_db)`, then assert counts + `PRAGMA table_info`
      column sets (raw, no deltas) + timestamp/`value_text`/FK-keying checks. (Fails — `build`/schema not
      implemented.)
- [ ] `tests/scripts/test_build_db_idempotent.py`: call `build` twice on the same `tmp_db`, compare counts,
      total rows, and full table **contents incl. ids** (`SELECT *` ordered) — assert equality. Compare
      table contents, **not** raw file bytes (`ANALYZE`/`sqlite_stat*`/free-page layout aren't byte-stable).
      (Fails.)

### GREEN
- [ ] Implement `init_schema` (DROP+CREATE the four raw tables), `build` (batched inserts wiring
      TASK-001's generator), and `main`/`argparse`. Smallest code to pass.

### REFACTOR
- [ ] Mirror the existing dump's indexes + the `total_distance` backfill `UPDATE`; keep the four-table
      `DROP TABLE IF EXISTS` list authoritative so re-runs never leave stale rows. Keep flush thresholds so
      memory stays bounded.

## Notes

`baseline.db` is the **full** raw corpus — **no** type-whitelist filtering and **no** `origin` flag (those
are E4·P3's seed-into-`app.db` concerns; DB.md §1, §6). `workouts.id` exists **only** as the
`workout_statistics` FK target — it is *not* the runtime `uuid`, which `baseline.db` deliberately omits
(ARCHITECTURE §3 "raw ETL dump: no PKs, no `uuid`"). Idempotency is structural: `DROP TABLE IF EXISTS`
then re-parse from `export.xml`, so the corpus is fully reproducible. `DROP TABLE workouts` also clears
that table's `sqlite_sequence` row, so the recreated AUTOINCREMENT table restarts ids at 1 and a
deterministic re-parse re-assigns the same `workouts.id` / `workout_statistics.workout_id` — the
idempotency check compares table **contents incl. ids**, not raw file bytes (round-1 #2, #4). Tests use the
small fixture via `--xml`/`--db` — never the real 1.5 GB `../db/export.xml`.
