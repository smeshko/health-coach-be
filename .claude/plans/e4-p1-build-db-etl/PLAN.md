# Plan: E4·P1 — build_db.py → baseline.db

Status: draft
Risk: medium
Created: 2026-06-03

> Epic **E4 — Baseline ETL & Bootstrap**, phase **P1**. Source of truth:
> [`epics/E04-baseline-bootstrap.md`](../../../epics/E04-baseline-bootstrap.md) (§1 summary, §2 **R1**,
> §3 **E4·P1**, §4 acceptance, §6 validation, §7 out-of-scope) · grounded in
> [`docs/architecture/DB.md`](../../../docs/architecture/DB.md) **§0** (two-DB split by lifecycle;
> ISO-8601 TEXT timestamps as Apple emits), **§1** (the four mirrored ingest tables, column by column,
> and the `uuid`/`origin`/`effort_score`/`date_components→date` **deltas** that `baseline.db` does
> **not** carry), **§6** (build paths; wholesale rebuild), **§7** (decision 1; open items) and
> [`docs/architecture/ARCHITECTURE.md`](../../../docs/architecture/ARCHITECTURE.md) **§3** (raw ETL dump:
> no PKs / no `uuid`) and **§6** (`../../db/baseline.db` is the build input, regenerable from
> `export.xml` via `build_db.py`, never opened at runtime). Curated findings in
> [`RESEARCH.md`](./RESEARCH.md).
>
> **This is an OFFLINE BUILD SCRIPT, not FastAPI runtime.** It lives at `scripts/build_db.py` (outside
> `app/`), uses only stdlib `sqlite3` + `xml.etree.ElementTree`, and writes the read-only corpus
> `baseline.db` in the **sibling** `../db/` directory. `baseline.db` is **never opened at runtime**.

## Goal

Add an offline `scripts/build_db.py` that **streams** Apple Health `export.xml` (memory-bounded
`iterparse` + `elem.clear()`) into the read-only corpus `../db/baseline.db` as a raw ETL dump — four
tables mirroring the `app.db` ingest shape (raw, minus the runtime `uuid`/`origin`/`effort_score`
deltas) — via an **idempotent wholesale rebuild** (`DROP TABLE IF EXISTS …` then recreate), and print a
per-table row-count summary report for sanity.

## Scope

- **`scripts/build_db.py`** — new offline ETL script (stdlib only; no `app/` / FastAPI / SQLAlchemy /
  Alembic import). Defaults to reading `../db/export.xml` and writing `../db/baseline.db` (relative to the
  repo root per DB.md §6 / ARCHITECTURE §6), with `--xml`/`--db` CLI overrides so tests never touch the
  real 1.5 GB corpus. Structure (kept small, testable functions):
  - **Streaming parse (TASK-001):** `iter_health_elements(xml_path)` (or equivalent) uses
    `ET.iterparse(xml_path, events=("end",))`, dispatches on `elem.tag` for `Record` / `Workout` /
    `ActivitySummary`, reads `<WorkoutStatistics>` children inside each `Workout`'s `end` event, and calls
    `elem.clear()` after every processed element. **No** `ET.parse()` / `fromstring()` / whole-file
    `.read()` — the DOM is never materialized (epic R1; ARCHITECTURE §6; DB.md §0).
  - **Schema + writes (TASK-002):** `init_schema(conn)` does `DROP TABLE IF EXISTS records/workouts/
    workout_statistics/activity_summary;` then `CREATE TABLE …` for the four **raw** tables; batched
    `executemany` inserts (a `BATCH` flush threshold) keep memory bounded; helper `to_float`/`to_int`
    coercion (NULL on blank/non-numeric, mirroring the existing dump). `workouts.id` is a local
    `INTEGER PRIMARY KEY AUTOINCREMENT` used **only** as the `workout_statistics.workout_id` FK target
    (records have **no** PK; DB.md §1, ARCHITECTURE §3). Re-run drops + recreates → idempotent (epic R1).
  - **Summary report (TASK-003):** `summarize(conn) -> dict[str, int]` returns per-table
    `SELECT COUNT(*)` for the four tables; `main()` prints it (`records=… workouts=… workout_statistics=…
    activity_summary=…`) after a build for a quick sanity check (epic §3 E4·P1; §4 "non-zero counts").
- **`tests/fixtures/health_export_small.xml`** — new tiny synthetic `export.xml` (valid HealthKit shape:
  a handful of `Record`s incl. one HKCategoryType sleep enum, ≥1 `Workout` with ≥1 child
  `WorkoutStatistics`, ≥2 `ActivitySummary` days) with **known** per-table counts for deterministic tests.
- **`tests/scripts/test_build_db.py`** — new: ETL over the fixture asserts (a) **exact per-table counts**,
  (b) **column shape** per table (`PRAGMA table_info` — raw columns, no `uuid`/`origin`/`effort_score`,
  `activity_summary` has `date_components`, `records` has no PK), (c) **timestamp fidelity** (a stored
  `start_date` equals the raw Apple string with its offset), (d) `value` numeric vs `value_text` carrying
  a category enum, (e) the `summarize()` report matches the table counts.
- **`tests/scripts/test_build_db_idempotent.py`** — new: running the build **twice** over the same fixture
  yields an identical `baseline.db` (per-table counts stable; total row count unchanged → no duplication;
  the second run's table contents equal the first's).
- **`tests/scripts/test_build_db_streaming.py`** — new: the parse is **memory-bounded by construction** —
  assert the source uses `iterparse` and `elem.clear()` and does **not** call `ET.parse`/`ET.fromstring`/
  whole-file `.read()` (structural/source assertion, since measuring RSS over 1.5 GB is impractical).

## Out of Scope

- **Constant derivation → `profile.yaml`** (`compute_zones.py`, zones, thresholds, nutrition, `meta`
  stamp) — that is **E4·P2** (epic §3 E4·P2, R2). This phase only builds `baseline.db`.
- **The 90-day seed into `app.db`** and **seed↔sync reconciliation** — **E4·P3** (epic §3 E4·P3, R3/R5).
  Including the `origin='seed'` flag, the type whitelist (R4), and the `date_components`→`date` rename,
  which all live at the *seed copy*, not in the raw corpus (DB.md §1, §6; epic §7).
- **Type-whitelist filtering** — `baseline.db` stores the **full** raw corpus (all `Record` types); the
  whitelist (incl. `HKQuantityTypeIdentifierDietary*` + `body_mass`) applies only at the E4·P3 seed
  (epic §3, §7; DB.md §1).
- **Runtime additions** — `records.uuid`/`origin`, `workouts.uuid`/`origin`/`effort_score`/
  `physical_effort`, and the `activity_summary.date` PK are **`app.db`-only** (E2·P2). `baseline.db` is
  the raw dump *without* them (DB.md §1 callout; ARCHITECTURE §3).
- **`workout_events` table** — the prior `../db/build_db.py` writes it, but it is **not** among DB.md §1's
  four mirrored ingest tables and not in the E4·P1 task list — excluded here (RESEARCH Uncertainty).
- **Running the build against the real 1.5 GB `../db/export.xml`** — a manual op; CI/tests use the small
  fixture only. The real corpus is never read by the test suite.
- **Dropped stack** — Postgres/pgvector, Celery, Redis, Supabase, streaming HTTP, RAG/`vecs`
  (ARCHITECTURE §1). This script is plain `sqlite3` + stdlib `ElementTree`.

## Research Summary

`baseline.db` is the **read-only historical corpus** — a raw ETL dump regenerated **wholesale** by
`build_db.py` (`DROP TABLE …` then re-parse `export.xml`) and **never opened at runtime**; the runtime
reads `app.db` only (DB.md §0, §3, §7 decision 1; ARCHITECTURE §3, §6). Its four tables —`records`,
`workouts`, `workout_statistics`, `activity_summary`— **structurally mirror** the `app.db` ingest tables
so the E4·P3 seed is a near-straight copy, but in **raw** form: **no `uuid`, no `origin`, no
`effort_score`/`physical_effort`** (runtime-only additions, DB.md §1 callout), **no PK on `records`**, and
`activity_summary` keeps Apple's **`date_components`** (the `→date` rename happens at the seed, DB.md §1,
§6). Timestamps are stored as **ISO-8601 TEXT exactly as Apple emits**, offset preserved (DB.md §0). The
corpus is large (~3.5M records / 925 workouts / 1,346 activity-summary days, 2019→2026; ARCHITECTURE §6),
so the parser **must stream** — `xml.etree.ElementTree.iterparse(events=("end",))` with `elem.clear()`
after each element, never `ET.parse()` of the whole DOM (epic R1, §1). The existing `../db/health.db`
(which DB.md §3 / ARCHITECTURE §3 say `baseline.db` is **renamed from**) and the prior `../db/build_db.py`
pin the exact raw schema + the `<Record>`/`<Workout>`/`<WorkoutStatistics>`/`<ActivitySummary>` → table
mapping mirrored here. Full curated findings, element→column map, and the open items (`workout_events`,
`total_distance` backfill, path resolution) in [`RESEARCH.md`](./RESEARCH.md).

## Decisions

- **Offline script at `scripts/build_db.py`, stdlib-only (`sqlite3` + `xml.etree.ElementTree`), no `app/`
  import** — `baseline.db` is a build artifact that is *never opened at runtime* (DB.md §0; ARCHITECTURE
  §3, §6), so it must not pull in FastAPI / SQLAlchemy / Alembic / the runtime config. A plain script keeps
  the corpus build fully decoupled from the runtime and from Alembic's `app.db`-only migration chain
  (E2·P1). A test asserts no `app/` module references `baseline.db` and the script imports nothing from
  `app`.
- **Four raw tables only, mirroring `app.db` ingest minus the runtime deltas** — DB.md §1 lists exactly
  `records`/`workouts`/`workout_statistics`/`activity_summary` as the mirrored set; `baseline.db` carries
  them **without** `uuid`/`origin`/`effort_score`/`physical_effort` and **without** a `records` PK, and
  keeps `activity_summary.date_components` (ARCHITECTURE §3 "raw ETL dump: no PKs, no `uuid`"; DB.md §1, §6).
  Mirroring (vs. a divergent shape) is what makes the E4·P3 seed a near-straight copy (DB.md §1).
- **`workouts.id` is a local `INTEGER PRIMARY KEY AUTOINCREMENT`, kept *only* as the FK target for
  `workout_statistics.workout_id`** — `<WorkoutStatistics>` is a child of `<Workout>` and must key back to
  its parent; a local autoincrement id is the join key. This is **not** the runtime `uuid` (which
  `baseline.db` deliberately omits); `records` and `activity_summary` get **no** surrogate PK. On
  ARCHITECTURE §3's literal "raw ETL dump: **no PKs**, no `uuid`": that rule targets the **sample** tables
  (`records` carries no PK at all; `activity_summary` keys by `date_components` with no surrogate) — it
  rules out *runtime* surrogate/`uuid` keys, not a build-local join column. `workouts.id` exists solely so
  the child `workout_statistics` rows can reference their parent within the same build; it is mechanically
  required (a parent↔child relation has to be keyed) and the existing reference dump `../db/health.db` does
  exactly this. So the dump still has **no `uuid`, no `origin`, no `records` PK**, faithfully raw
  (ARCHITECTURE §3; DB.md §1) — round-1 #1.
- **Idempotent via `DROP TABLE IF EXISTS …` then recreate every run** — epic R1 / §4 require a safe re-run
  yielding an identical `baseline.db`; dropping + recreating guarantees no stale rows survive a re-parse
  and the corpus is reproducible from `export.xml` alone (DB.md §0, §7 decision 1). **`workouts.id` stays
  stable across rebuilds** because `DROP TABLE workouts` also clears that table's `sqlite_sequence` row, so
  the recreated AUTOINCREMENT table restarts ids at 1 and a deterministic re-parse (same input order)
  re-assigns the same ids — hence `workout_statistics.workout_id` is stable too. The idempotency contract
  is scoped to per-table **counts + contents** (incl. these ids), **not** byte-identity of the file:
  `ANALYZE` writes nondeterministic `sqlite_stat*` tables and SQLite's free-page layout isn't byte-stable,
  so a byte-level diff would be a false negative (round-1 #2, #4).
- **No type-whitelist filtering / no `origin` flag in `baseline.db`** — the corpus is the **full** raw
  history; the whitelist (R4) and `origin='seed'` apply only when E4·P3 copies the trailing 90 days into
  `app.db` (epic §3, §7; DB.md §1, §6). Filtering here would lose history the constant-derivation step
  (E4·P2) may need.
- **`<Record value>` → both a coerced REAL `value` (NULL when non-numeric) and the raw `value_text`** —
  quantity types are numeric but category types carry an enum string (e.g.
  `HKCategoryValueSleepAnalysisAsleepCore`) a REAL column can't hold (DB.md §1 `records.value`/
  `value_text`; mirrors `../db/health.db`). Store both so neither sleep stages nor numeric values are lost.
- **Timestamps stored as TEXT verbatim (offset preserved), never normalized to a `DATETIME`/UTC** — DB.md
  §0: ISO-8601 TEXT carrying the per-sample offset Apple emits; they sort correctly and stay debuggable.
  A test asserts a stored `start_date` is byte-equal to the fixture's raw Apple string.
- **Streaming asserted structurally, not by RSS measurement** — `iterparse` + `elem.clear()` bound memory
  by construction (epic R1; ARCHITECTURE §6); measuring resident memory over the 1.5 GB file in CI is
  impractical and flaky, so the test asserts the *approach* (uses `iterparse`/`clear`, no
  `ET.parse`/`fromstring`/whole-file `read`) — a reliable proxy for memory-boundedness.
- **`--xml`/`--db` CLI overrides with `../db/` defaults** — the real input is the sibling
  `../db/export.xml` → `../db/baseline.db` (DB.md §6; ARCHITECTURE §6), but tests must run against the
  small fixture without touching the corpus, so paths are parameterizable (RESEARCH Uncertainty).
- **Keep the `total_distance` backfill from the prior script** — a deterministic post-parse `UPDATE` that
  fills `workouts.total_distance` from the matching `workout_statistics` row when Apple omits the top-level
  attribute (recent watchOS stashes it in the child). It is part of producing a usable raw corpus and is
  idempotent (drop+recreate+reparse reproduces it); it is a REFACTOR detail, not an acceptance criterion.

## Risks

- **Parser loads the whole DOM (`ET.parse`) → OOM on the 1.5 GB corpus** — mitigation: use
  `ET.iterparse(events=("end",))` + `elem.clear()` after each element; `tests/scripts/
  test_build_db_streaming.py` asserts the source uses `iterparse`/`clear` and contains **no** `ET.parse`/
  `ET.fromstring`/whole-file `.read()` (epic R1; ARCHITECTURE §6; DB.md §0).
- **Memory grows because parsed rows accumulate in Python before insert** — mitigation: batched
  `executemany` with a flush threshold (`BATCH`); buffers are cleared on flush so peak memory is bounded by
  one batch, not the corpus (RESEARCH Constraints).
- **Non-idempotent re-run (stale rows survive / rows duplicated)** — mitigation: `DROP TABLE IF EXISTS …`
  then `CREATE` each run; `test_build_db_idempotent.py` runs the build twice and asserts per-table counts
  are stable, the total row count is unchanged (no duplication), and the second run's table contents equal
  the first's (epic R1, §4).
- **`workouts.id`/`workout_statistics.workout_id` drift across rebuilds** (AUTOINCREMENT counters not
  reset) → the idempotency content-equality check fails even though no data changed — mitigation: `DROP
  TABLE workouts` clears that table's `sqlite_sequence` row, so the recreated table restarts ids at 1; the
  idempotency test compares full table **contents incl. ids** across two runs and asserts equality, proving
  ids are stable (round-1 #2). The test compares table contents, **not** the raw file bytes (which aren't
  stable — `ANALYZE`/`sqlite_stat*`/free-page layout), so it isn't a false-failure on nondeterministic
  file layout (round-1 #4).
- **Schema drifts from `app.db` ingest or leaks a runtime delta into the raw dump** — e.g. accidentally
  adding `uuid`/`origin`/`effort_score`, a `records` PK, or renaming `date_components`→`date` — mitigation:
  `test_build_db.py` asserts the exact `PRAGMA table_info` column set per table — raw columns only, no
  `uuid`/`origin`/`effort_score`/`physical_effort`, `records` has no PK, `activity_summary` keeps
  `date_components` (DB.md §1 callout; ARCHITECTURE §3).
- **Timestamps normalized / offset dropped** — mitigation: store the raw Apple string as TEXT verbatim and
  assert a stored `start_date` equals the fixture's raw `+HHMM`-bearing value (DB.md §0).
- **Category records (sleep stages, stand state) lost because `value` is non-numeric** — mitigation: store
  the raw string in `value_text` and a coerced-or-NULL float in `value`; a fixture sleep-analysis record
  asserts `value_text` holds the enum and `value` is NULL (DB.md §1).
- **`workout_statistics` rows orphaned / mis-keyed to the wrong workout** — mitigation: read
  `<WorkoutStatistics>` children inside the parent `<Workout>` `end` event and key them to that workout's
  `lastrowid`; the fixture asserts the stat row's `workout_id` matches the inserted workout and the count
  is correct.
- **Runtime accidentally opens `baseline.db`** (violating "never opened at runtime") — mitigation: a test
  asserts no `app/` module references `baseline.db` (`grep -REn "baseline\.db" app` empty) and
  `scripts/build_db.py` imports nothing from `app` (DB.md §0, §3; ARCHITECTURE §3, §6).
- **Build reads the real 1.5 GB corpus during tests → slow/flaky CI** — mitigation: all tests use the small
  fixture via `--xml`/`--db`; the suite never points at `../db/export.xml`.

## Acceptance Criteria

- [ ] **Idempotent rebuild** — running `scripts/build_db.py` **twice** over the same input yields an
      identical `baseline.db`: per-table counts are stable, the total row count is unchanged (no
      duplication), and the second run's four-table contents equal the first's
      (`tests/scripts/test_build_db_idempotent.py`). (epic R1, §4; DB.md §0)
- [ ] **Non-zero counts across the four tables** — after a build over the fixture, each of `records`,
      `workouts`, `workout_statistics`, `activity_summary` has the **exact** expected (>0) row count
      (`tests/scripts/test_build_db.py`). (epic §4; §3 E4·P1)
- [ ] **Raw column shape (no runtime deltas)** — `PRAGMA table_info` shows: `records` has the raw columns
      (`type`,`unit`,`value`,`value_text`,`source_name`,`source_version`,`device`,`creation_date`,
      `start_date`,`end_date`) with **no `id`/PK, no `uuid`, no `origin`**; `workouts` has `activity_type`/
      duration/distance/energy(+units)/provenance/dates with **no `uuid`/`origin`/`effort_score`/
      `physical_effort`** (a local autoincrement `id` is allowed **solely** as the `workout_statistics`
      FK target — the build-local parent↔child join key, not a runtime surrogate/`uuid`, so the raw-dump
      "no PKs / no `uuid`" rule still holds for `records`/`activity_summary`; round-1 #1);
      `workout_statistics` has `workout_id`/`type`/dates/`sum`/`average`/`minimum`/`maximum`/`unit`;
      `activity_summary` keeps **`date_components`** (not `date`) + the rings (+goals, stand-hours INTEGER).
      (`tests/scripts/test_build_db.py`). (DB.md §0, §1; ARCHITECTURE §3)
- [ ] **TEXT timestamp fidelity** — a stored `start_date` is byte-equal to the fixture's raw Apple string
      including the emitted offset (no UTC normalization) (`tests/scripts/test_build_db.py`). (DB.md §0)
- [ ] **Category vs. quantity `value`** — a fixture HKCategoryType sleep-analysis record stores its enum in
      `value_text` with `value` NULL, while a quantity record stores a numeric `value`
      (`tests/scripts/test_build_db.py`). (DB.md §1)
- [ ] **`workout_statistics` keyed to its parent workout** — a fixture stat row's `workout_id` matches the
      inserted workout's id (correct child→parent association) (`tests/scripts/test_build_db.py`). (DB.md §1)
- [ ] **Summary report = per-table counts** — `summarize(conn)` returns a mapping whose four values equal
      the actual `COUNT(*)` per table, and `main()` prints it after a build
      (`tests/scripts/test_build_db.py`). (epic §3 E4·P1; §4)
- [ ] **Memory-bounded streaming (by construction)** — the parser uses `ET.iterparse` + `elem.clear()` and
      the source contains **no** `ET.parse`/`ET.fromstring`/whole-file `.read()`
      (`tests/scripts/test_build_db_streaming.py`). (epic R1; ARCHITECTURE §6; DB.md §0)
- [ ] **Offline / never opened at runtime** — `scripts/build_db.py` imports nothing from `app` and no
      `app/` module references `baseline.db` (`! grep -REn "baseline\.db" app`; an import-scan test). (DB.md
      §0, §3; ARCHITECTURE §3, §6)
- [ ] **No dropped-stack leakage** — `! grep -REn "psycopg|pgvector|celery|redis|supabase|vecs" scripts`
      (the script is stdlib-only). (ARCHITECTURE §1)
- [ ] `uv run ruff check .` and `uv run pytest tests/scripts` pass.

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [ ] TASK-001: export.xml streaming parser
- [ ] TASK-002: Write baseline.db tables (idempotent DROP and recreate)
- [ ] TASK-003: Summary report of per-table counts
- [ ] TASK-004: Final Validation
