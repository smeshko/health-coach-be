# Research: E4·P1 — build_db.py → baseline.db

Curated findings only — no raw conversation transcripts. Grounds the plan in
[`epics/E04-baseline-bootstrap.md`](../../../epics/E04-baseline-bootstrap.md) (§1, §2 R1, §3 E4·P1, §4,
§6, §7), [`docs/architecture/DB.md`](../../../docs/architecture/DB.md) §0, §1, §6, §7, and
[`docs/architecture/ARCHITECTURE.md`](../../../docs/architecture/ARCHITECTURE.md) §3, §6.

## Key Files & Directories

- `scripts/build_db.py` — **new** (this phase): the offline ETL build script. NOT part of the FastAPI
  runtime (`app/...`). Parses Apple Health `export.xml` → the read-only corpus `baseline.db`.
- `../db/` — the **sibling** directory (relative to the `backend/` repo root) that holds the corpus and
  build inputs. Confirmed contents (read-only, inspected this phase):
  - `../db/export.xml` — the 1.5 GB Apple Health export (HealthKit Export Version 14). The build input.
  - `../db/health.db` — the **existing** ETL dump (1.4 GB). DB.md §3 / ARCHITECTURE §3, §6 say
    `baseline.db` is **renamed from `health.db`** — this build writes `../db/baseline.db` and its schema
    must mirror the existing dump (the source of truth for the raw shape).
  - `../db/build_db.py` — a **prior, standalone** ETL script (in the sibling dir, not the repo). It is the
    reference for the raw schema, the `iterparse` streaming approach, batched inserts, and the
    `total_distance` backfill. The new `scripts/build_db.py` is the repo-managed re-home of this logic.
- `tests/scripts/` — **new**: pytest tests over a small synthetic fixture `export.xml` (no big-file load).
- `tests/fixtures/health_export_small.xml` — **new**: a tiny hand-written `export.xml` (a handful of
  `Record` / `Workout` (with child `WorkoutStatistics`) / `ActivitySummary` elements) for deterministic,
  fast ETL tests.

## Architecture Facts

- **`baseline.db` is a raw ETL dump, regenerated wholesale, never opened at runtime** — DB.md §0, §3, §7
  decision 1; ARCHITECTURE §3, §6. The runtime reads `app.db` only. So this script lives outside `app/`
  and the test suite must prove no runtime/`app/` code imports or opens `baseline.db`.
- **Raw shape vs. runtime ingest** (DB.md §0, §1, §6; ARCHITECTURE §3): `baseline.db` structurally
  **mirrors** the four `app.db` ingest tables (`records`, `workouts`, `workout_statistics`,
  `activity_summary`) but in **raw** form — **no `uuid`, no `origin`, no `effort_score`/`physical_effort`**
  (those are runtime-only additions to `app.db`, DB.md §1 callout), **no PKs on `records`**, and
  `activity_summary` keeps Apple's **`date_components`** (the `→ date` rename happens only at the E4·P3
  seed copy, DB.md §1, §6). TEXT timestamps are stored **exactly as Apple emits them** (e.g.
  `"2016-05-18 16:45:52 +0300"`), offset preserved (DB.md §0).
- **Four tables** for this phase (epic §3 E4·P1; DB.md §1): `records`, `workouts`, `workout_statistics`,
  `activity_summary`. The prior `../db/build_db.py` also writes a `workout_events` table, but neither the
  phase spec nor DB.md §1 lists it among the mirrored tables — it is **out of scope** here (see Decisions).
- **Streaming is mandatory** — the corpus is ~3.5M records / 925 workouts / 1,346 activity-summary days,
  2019→2026 (ARCHITECTURE §6; epic §1). The parser MUST use `xml.etree.ElementTree.iterparse` with
  `events=("end",)` and call `elem.clear()` after each processed element to bound memory. **Never**
  `ET.parse()` / load the whole DOM.
- **Idempotent, wholesale rebuild** — `DROP TABLE IF EXISTS …` then recreate every run; re-running yields
  an identical `baseline.db` (epic R1, §4; DB.md §0, §7 decision 1). A safe re-run is the core contract.
- **Element → table mapping** (confirmed from `export.xml` DTD + samples, and `../db/health.db` schema):
  | XML element | Table | Notable attribute → column |
  |---|---|---|
  | `<Record>` | `records` | `type`,`unit`,`value`(→REAL `value` + raw `value_text`),`sourceName`,`sourceVersion`,`device`,`creationDate`,`startDate`,`endDate` |
  | `<Workout>` | `workouts` | `workoutActivityType`→`activity_type`,`duration`(+`durationUnit`),`totalDistance`(+unit),`totalEnergyBurned`(+unit),provenance,dates |
  | `<WorkoutStatistics>` (child of `<Workout>`) | `workout_statistics` | `type`,`startDate`,`endDate`,`sum`,`average`,`minimum`,`maximum`,`unit` → FK `workout_id` |
  | `<ActivitySummary>` | `activity_summary` | `dateComponents`→`date_components`,`activeEnergyBurned`(+goal+unit),`appleExerciseTime`(+goal),`appleStandHours`(+goal, INTEGER),`appleMoveTime`(+goal) |
- `<Record value>` carries either a numeric quantity **or** a category enum (e.g.
  `HKCategoryValueSleepAnalysisAsleepCore`) that a REAL column can't hold — so store the **raw string** in
  `value_text` and a parsed-or-NULL float in `value` (DB.md §1 `records.value`/`value_text`; mirrors
  `../db/health.db`).
- `<WorkoutStatistics>` is a **child** of `<Workout>`, so it is read inside the workout's `end` event
  (via `elem.findall("WorkoutStatistics")`) and keyed to that workout's local autoincrement `id`. Apple
  also emits `<MetadataEntry>`/`<WorkoutEvent>`/`<WorkoutRoute>` children — ignored here.
- Existing `../db/health.db` schema (the raw target this build mirrors): `records(type,unit,value,
  value_text,source_name,source_version,device,creation_date,start_date,end_date)`;
  `workouts(id PK AUTOINCREMENT, activity_type,duration,duration_unit,total_distance,total_distance_unit,
  total_energy_burned,total_energy_burned_unit,source_name,source_version,device,creation_date,start_date,
  end_date)`; `workout_statistics(workout_id,type,start_date,end_date,sum,average,minimum,maximum,unit)`;
  `activity_summary(date_components,active_energy_burned,active_energy_burned_goal,
  active_energy_burned_unit,apple_exercise_time,apple_exercise_time_goal,apple_stand_hours,
  apple_stand_hours_goal,apple_move_time,apple_move_time_goal)`.

## Constraints

- **Offline, not runtime.** No FastAPI / SQLAlchemy / Alembic / `app/...` dependency. Plain `sqlite3` +
  `xml.etree.ElementTree` from the stdlib. `baseline.db` is **never** registered with Alembic and never
  opened by `app/` (DB.md §0, §3; ARCHITECTURE §6).
- **No type-whitelist filtering here.** `baseline.db` is the **full** raw corpus; the type whitelist (R4)
  and `origin='seed'` apply only at the E4·P3 seed copy into `app.db` (epic §3, §7; DB.md §1, §6).
- **Memory-bounded.** `iterparse` + `elem.clear()`; batched `executemany` inserts; do not accumulate all
  rows in memory. The test suite asserts the *approach* (no `ET.parse`/`fromstring` of the whole tree;
  `iterparse` + `clear` present) rather than trying to measure RSS over the 1.5 GB file.
- **Idempotent.** A second run over the same input produces byte-stable table **contents** (same per-table
  counts, no duplication). `DROP TABLE IF EXISTS` guarantees no stale rows survive a schema/parse change.
- **No big-file dependency in tests.** All tests use the small synthetic fixture; the 1.5 GB
  `../db/export.xml` is never read by CI.

## Useful Commands

```bash
# build (offline, manual) — writes ../db/baseline.db from ../db/export.xml
uv run python scripts/build_db.py            # default in/out paths (sibling ../db/)
uv run python scripts/build_db.py --xml <in.xml> --db <out.db>   # explicit paths (tests use this)

# lint + tests (no big-file load — fixture only)
uv run ruff check .
uv run pytest tests/scripts

# prove the runtime never touches baseline.db / no DOM load
grep -REn "baseline\.db" app && echo LEAK || echo clean
grep -REn "ET\.parse|fromstring|\.read\(\)" scripts/build_db.py   # must be empty (streaming only)
```

## Uncertainty

- **`workout_events`** — the prior `../db/build_db.py` writes it, but it is not in DB.md §1's mirrored
  ingest set nor the phase task list. **Resolved:** out of scope for E4·P1 (four tables only). A later
  phase can add it if a derived metric needs it; flagged in PLAN.md Out of Scope.
- **`total_distance` backfill** — the prior script backfills `workouts.total_distance` from
  `workout_statistics` when the top-level attr is NULL. **Resolved:** keep it (it is a faithful,
  deterministic part of producing a usable raw corpus and does not break idempotency), but it is a small
  REFACTOR detail, not an acceptance criterion. Idempotency tests run the full build (incl. backfill)
  twice and compare.
- **File path resolution** — defaults point at the sibling `../db/` (relative to repo root) per DB.md §6 /
  ARCHITECTURE §6; the script exposes `--xml`/`--db` overrides so tests never touch the real corpus.
  **Resolved:** default-path constants + CLI overrides.

## References

- `epics/E04-baseline-bootstrap.md` §1, §2 (R1), §3 (E4·P1), §4, §6, §7
- `docs/architecture/DB.md` §0 (two-DB shape, TEXT timestamps), §1 (the four mirrored tables + the
  `uuid`/`origin`/rename deltas), §6 (build paths / wholesale rebuild), §7 (decision 1; open items)
- `docs/architecture/ARCHITECTURE.md` §3 (raw ETL dump: no PKs/`uuid`), §6 (`../../db/baseline.db` is the
  build input; regenerable from `export.xml` via `build_db.py`; never opened at runtime)
- `../db/build_db.py` (prior reference implementation), `../db/health.db` (existing raw schema),
  `../db/export.xml` (HealthKit Export Version 14 DTD + samples)
