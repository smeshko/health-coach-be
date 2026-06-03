# Plan: E4·P3 — 90-day seed + reconciliation

Status: draft
Risk: medium
Created: 2026-06-03

> Epic **E4 — Baseline ETL & Bootstrap**, phase **P3** (the **final** E4 phase). Source of truth:
> [`epics/E04-baseline-bootstrap.md`](../../../epics/E04-baseline-bootstrap.md) (§1 summary, §2 **R3**
> seed / **R4** whitelist / **R5** reconciliation, §3 **E4·P3**, §4 acceptance, §6 validation, §7
> out-of-scope) · grounded in [`docs/architecture/DB.md`](../../../docs/architecture/DB.md) **§0** (two-DB
> split by lifecycle; ISO-8601 TEXT timestamps; **Europe/Sofia** period keys), **§1** (the four ingest
> tables column-by-column — the `uuid`/`origin` additions, the `date_components`→`date` rename, and the
> **whitelisted-type list** incl. dietary + `body_mass`), **§6** (bootstrap: copy the trailing ~90 days with
> `origin='seed'`), **§7** (decisions 2/8; the **two open items this phase resolves** — the exact whitelist
> set and the seed↔sync reconciliation rule) and
> [`docs/architecture/ARCHITECTURE.md`](../../../docs/architecture/ARCHITECTURE.md) **§3** (Bootstrap) and
> **§6** (`baseline.db` is a build input, never opened at runtime). Curated findings in
> [`RESEARCH.md`](./RESEARCH.md).
>
> **Depends on E4·P1** (`baseline.db` raw corpus), **E2·P2** (the four `app.db` ingest models + their
> `ingest_tables` Alembic revision — the seed's **target schema**), and **E2·P1** (`app/core/time.py`
> Europe/Sofia period-key helpers; `app/database/engine.py`). The **seed** and **reconciliation** are
> OFFLINE build/maintenance scripts in `scripts/` (not FastAPI runtime); the one runtime-shared piece is the
> **type whitelist** module in `app/core/` (reused by E5 `/sync`). `baseline.db` is **never opened at
> runtime**.

## Goal

Finish E4: ship the finalized HealthKit **type whitelist** (`app/core/healthkit.py`, shared with E5), an
offline **seed** (`scripts/seed_app_db.py`) that copies the trailing ~90 days of whitelisted samples from
`baseline.db` into `app.db`'s ingest tables with `origin='seed'`/`uuid=NULL`, and a one-time **seed↔sync
reconciliation** (`scripts/reconcile_seed.py`) that drops seed rows for any Europe/Sofia day fully covered by
synced data — so the first `/brief/weekly` has valid 7/28-day rollups and 30-day HRV/RHR baselines on day one.

## Scope

- **`app/core/healthkit.py`** (TASK-001) — the finalized type whitelist (R4; DB.md §1, §7). A
  `frozenset[str]` `WHITELISTED_TYPES` = the exact `HK…Identifier` set (activity/recovery + dietary +
  `body_mass`; see RESEARCH "Type whitelist — finalized exact set"), split into named subsets
  (`ACTIVITY_RECOVERY_TYPES`, `DIETARY_TYPES`) for readability and a named `CADENCE_TYPE` constant to be
  confirmed against the corpus. `is_whitelisted(type_: str) -> bool`. **Pure data + helpers — no DB/IO**, so
  E5 `/sync` and the seed share one source of truth. Lives in `app/core/` (runtime-importable); does **not**
  open `baseline.db`.
- **`scripts/seed_app_db.py`** (TASK-002) — the offline seed (epic R3; DB.md §1, §6). Opens `baseline.db`
  **read-only** and the migrated `app.db`, then copies the trailing ~90 days of whitelisted samples into the
  four ingest tables:
  - **Window** = samples whose **Europe/Sofia `period_date`** (from `app/core/time.py`, applied to each
    sample's `start_date` / `activity_summary.date`) falls in `[period_date(now) − SEED_DAYS + 1 …
    period_date(now)]`. `--now` (default today Europe/Sofia) / `--days` (default `SEED_DAYS=90`) make it
    deterministic.
  - **`records`** — only rows whose `type` is whitelisted (incl. dietary + `body_mass`) and in-window →
    inserted with all copied columns, `uuid=NULL`, `origin='seed'`.
  - **`workouts`** — every in-window session → inserted with `uuid=NULL`, `origin='seed'`,
    `effort_score`/`physical_effort` `NULL` (absent in `baseline.db`); each new `workouts.id` maps its child
    `workout_statistics` rows (FK re-pointed to the new id). `workout_statistics` carries **no `origin`** — it
    inherits its parent's seed status.
  - **`activity_summary`** — every in-window day → inserted with the **`date_components`→`date`** rename (the
    value is already a Sofia date). It has **no `origin` column** (DB.md §1 — one row per day, **upserted by
    the `date` PK**); the seed writes it via `INSERT … ON CONFLICT(date) DO UPDATE` (upsert), **not** with an
    `origin` flag.
  - **Idempotent**: a re-run first deletes the origin-bearing seed rows — child `workout_statistics` of seed
    workouts first (no `ON DELETE CASCADE`; `foreign_keys=ON`), then `DELETE FROM workouts WHERE
    origin='seed'`, then `DELETE FROM records WHERE origin='seed'` — then re-copies; `activity_summary`
    re-seeds via its date-PK **upsert** (so a re-run overwrites the same date rows, no duplication).
  - CLI `--baseline` (default sibling `../db/baseline.db`) / `--app-db` (default `settings.app_db_path`) /
    `--now` / `--days`. Prints a per-table seeded-row count.
- **`scripts/reconcile_seed.py`** (TASK-003) — the one-time seed↔sync reconciliation (epic R5; DB.md §7). A
  callable `reconcile_seed(conn) -> dict[str,int]` plus a thin `--app-db` CLI:
  - **Rule** (the decision this phase makes): live `'sync'` rows are authoritative; a Sofia day **D is
    "fully covered" iff ≥1 `'sync'` row exists whose Sofia day is D**. For every such D, **delete the
    `origin='seed'` rows on D** in the **origin-bearing** ingest tables — `records` and `workouts` (deleting
    the child `workout_statistics` of those seed workouts **first**, since the FK has no `ON DELETE CASCADE`
    and `foreign_keys=ON`). Days with **no** sync row keep their seed rows; **`'sync'` rows are never
    deleted**.
  - **`activity_summary` is NOT reconciled** — it has **no `origin`** and is **upserted by the `date` PK**
    (DB.md §1), so a live `/sync` for a day already overwrote that day's seed row by date; there is nothing
    left to drop. Reconciliation scope is `records` + `workouts` (+ their stats).
  - Day key: `period_date(start_date)` (Europe/Sofia, via `app/core/time.py`) for `records`/`workouts`.
  - **Idempotent**: a second run deletes 0 rows (the covered seed days are already gone). Returns/prints the
    per-table deleted-row counts.
- **`tests/core/test_healthkit.py`** (TASK-001) — the whitelist contains every required identifier (each
  dietary type, `body_mass`, HR/HRV/RHR/sleep/steps/energy/METs/VO₂/running dynamics);
  `is_whitelisted` is True for an in-set type and False for a non-whitelisted one
  (`HKQuantityTypeIdentifierEnvironmentalAudioExposure`); the set is a `frozenset` (immutable).
- **`tests/scripts/test_seed_app_db.py`** (TASK-002) — build a tiny synthetic `baseline.db` + a migrated temp
  `app.db` in `tmp_path`; run the seed; assert: **window bounds** correct across a **Europe/Sofia DST
  boundary** (an in-window near-midnight sample is kept, an out-of-window one dropped, with the correct Sofia
  day); **`origin='seed'`** and **`uuid IS NULL`** on every seeded `records`/`workouts` row (the
  origin-bearing tables); **whitelist filtering** (dietary + `body_mass` present, a non-whitelisted `type`
  **absent**); `activity_summary.date` carries the renamed Sofia date and the row is addressable by the
  `date` PK (no `origin` column); a seeded `workout`'s `workout_statistics` FK points at the new
  `workouts.id`; **idempotent** re-run yields identical seeded rows (no duplication, incl. the
  `activity_summary` date-PK upsert).
- **`tests/scripts/test_reconcile_seed.py`** (TASK-003) — seed `records`/`workouts` + simulate a first
  `/sync` overlapping the seed window on a temp `app.db`; run `reconcile_seed`; assert: **seed rows on a
  fully-covered day are deleted** (incl. the child `workout_statistics` of a deleted seed workout);
  **`'sync'` rows are untouched**; **seed rows on a partially-covered day** (a day with **no** sync row) are
  **kept**; reconciliation is **idempotent** (second run deletes 0).

## Out of Scope

- **The live `/sync` ingest path** (idempotent `INSERT … ON CONFLICT(uuid) DO NOTHING` upsert,
  the `activity_summary` date-upsert, applying the whitelist to incoming wire samples, and the
  `daily_metrics` recompute) — **E5** (epic §7; DB.md §6). This phase only seeds + reconciles; it **defines**
  the whitelist E5 will reuse but does not implement `/sync`.
- **`daily_metrics` computation / the 7/28-day rollups / 30-day baselines** — **E6** (epic §7; DB.md §2). The
  seed exists *so* those rollups have data; it does not compute them.
- **Building `baseline.db`** (`export.xml` → corpus) — **E4·P1** (`scripts/build_db.py`); this phase only
  **reads** the corpus (epic §3 E4·P1).
- **Deriving `profile.yaml` constants** (`derive_constants.py` / `compute_zones.py`) — **E4·P2** (epic §3
  E4·P2). Independent of the seed.
- **Defining/altering the `app.db` ingest schema** — owned by **E2·P2**; this phase **writes into** it
  unchanged (no model edits, no new migration) (DB.md §1).
- **The Europe/Sofia period-key / timestamp helpers** — delivered in **E2·P1** (`app/core/time.py`); reused
  here, not re-implemented (DB.md §0).
- **Wiring the seed/reconcile into an automated deploy/CI step or a scheduler** — they are **manual,
  one-time** build/maintenance ops (ARCHITECTURE §3 "one-time, at deploy"; no scheduler — ARCHITECTURE §1).
- **Dropped stack** — Postgres/pgvector, Celery, Redis, Supabase, streaming, RAG/`vecs` (ARCHITECTURE §1).
  The scripts are plain `sqlite3`; the whitelist is pure Python data.

## Research Summary

`baseline.db` structurally **mirrors** the `app.db` ingest tables, so the 90-day seed is a near-straight copy
**modulo three deltas**: add `uuid` (`NULL` for seed rows), add `origin` (`'seed'`), and rename
`activity_summary.date_components`→`date` (DB.md §1, §6; ARCHITECTURE §3). The window is the **trailing ~90
days by Europe/Sofia day boundaries** — the cut is on each sample's **`period_date`** (E2·P1
`app/core/time.py`), never a fixed UTC offset, so a near-midnight winter/summer sample lands on the correct
Sofia day (DB.md §0). The **type whitelist** (R4; DB.md §1, §7 open item) is finalized here as the exact
`HK…Identifier` set (activity/recovery + the `HKQuantityTypeIdentifierDietary*` family + `body_mass`) and
lives in `app/core/healthkit.py` because it is **shared with E5** `/sync`. The **seed↔sync reconciliation**
(R5; DB.md §7 open item) is decided here: live `'sync'` rows are authoritative, and a Sofia day **fully
covered** (≥1 sync row that day) has its `'seed'` rows dropped, while partially-covered days keep theirs and
`'sync'` rows are never deleted. Everything is offline (`scripts/`) except the pure-data whitelist; the
runtime never opens `baseline.db` (ARCHITECTURE §6; DB.md §0). See [`RESEARCH.md`](./RESEARCH.md).

## Decisions

- **Type whitelist lives in `app/core/healthkit.py` (runtime), not `scripts/`** — the NOTES + DB.md §1 say
  it is **shared with E5**: `/sync` filters incoming wire samples through the **same** set, so it must be
  importable at runtime. It is **pure data** (a `frozenset` of `HK…Identifier` strings + `is_whitelisted`),
  opens no DB, so hosting it in `app/` does not violate "`baseline.db` never opened at runtime" (the seed
  script imports it; the corpus stays in `scripts/`-only territory). One source of truth prevents the seed
  and `/sync` whitelists from drifting (DB.md §1; ARCHITECTURE §6; epic R4).
- **Finalized exact whitelist set** (R4; DB.md §1, §7) — activity/recovery (`HeartRate`,
  `HeartRateVariabilitySDNN`, `RestingHeartRate`, `SleepAnalysis` [HKCategoryType], `StepCount`,
  `ActiveEnergyBurned`, `BasalEnergyBurned`, `PhysicalEffort`/METs, `VO2Max`, `BodyMass`, running
  speed/stride/vertical-oscillation/ground-contact/power), **plus** the `HKQuantityTypeIdentifierDietary*`
  family (`DietaryEnergyConsumed`, `Protein`, `Carbohydrates`, `FatTotal`, `Fiber`, `Sodium`, `Water`).
  **Only** whitelisted `record` types are stored (DB.md §1 "only the whitelisted types … are stored"). The
  exact running-**cadence** identifier varies by export version, so a named `CADENCE_TYPE` is confirmed
  against the corpus rather than hard-guessed (same resolution as E4·P2); `StepCount` is whitelisted
  regardless. The whitelist gates **`records.type`**; `workouts` (sessions) and `activity_summary` (per-day
  rings) are seeded by window, not `type`-filtered.
- **Window cut on Europe/Sofia `period_date`, not a raw UTC instant** — DB.md §0 derives period keys through
  the `Europe/Sofia` tz database; the 90-day boundary must respect Sofia days (winter `+0200`, summer
  `+0300`) so the first weekly/daily briefs' day-keyed rollups line up. Each sample's `start_date`
  (`records`/`workouts`) is mapped via E2·P1's `period_date`; `activity_summary.date` is already a Sofia
  date. `--now`/`--days` make the window deterministic and testable (incl. a DST-boundary test). Never assume
  `+03:00` (DB.md §0; ARCHITECTURE §4).
- **Three deltas only; `effort_score`/`physical_effort` left NULL for seed rows** — the copy is column-for-
  column except `uuid`(=NULL), `origin`(='seed'), and `date_components`→`date` (DB.md §1, §6). `app.db`'s
  `workouts.effort_score`/`physical_effort` have no `baseline.db` source, and E2·P2 made them nullable, so
  seed workouts carry NULL there — faithful, and `/sync` backfills real scores later (ARCHITECTURE §6
  "first sync backfills available scores").
- **`origin` lives only on `records` + `workouts`; `activity_summary` has none and is upserted by `date`,
  `workout_statistics` inherits its parent's** — DB.md §1 lists `origin TEXT NOT NULL` **only** on `records`
  and `workouts`. `activity_summary` is **one row per Sofia day, upserted by the `date` PK** (no per-row
  origin), and `workout_statistics` is keyed to a parent workout (no `origin`). So the seed sets `origin`
  only on `records`/`workouts`; `activity_summary` is seeded via a `date`-PK upsert; the seed/sync overlap on
  `activity_summary` is resolved **automatically** by that upsert (a live `/sync` overwrites the day's row by
  date), which is why reconciliation never touches it (round-1 #1; DB.md §1).
- **Deletes go child-before-parent (no `ON DELETE CASCADE`, `foreign_keys=ON`)** — E2·P2's
  `workout_statistics.workout_id → workouts(id)` FK has **no** `ON DELETE CASCADE`, and E2·P1's connect
  listener sets `PRAGMA foreign_keys=ON`, so deleting a seed workout with surviving stats children would
  raise `IntegrityError`. Both the seed-idempotency re-run and the reconciliation **delete the child
  `workout_statistics` rows first**, then the parent seed workouts (round-1 #2; E2·P2 FK).
- **Reconciliation rule — a Sofia day is "fully covered" iff ≥1 `'sync'` row exists that day** (resolves
  DB.md §7's open "*Needs a decision*") — live `'sync'` is the on-device HealthKit truth for a day it synced,
  so it **supersedes the seed estimate for that whole day**: drop all `origin='seed'` rows on that day.
  A day with **no** sync row keeps its seed rows (partially covered = not covered). The rule applies to the
  **origin-bearing** tables `records` + `workouts` only; **`activity_summary` is excluded** (it has no
  `origin` and its date-PK upsert already collapses seed/sync — see the `origin` decision above). This is the
  simplest **decidable, idempotent** rule that satisfies the epic's "keeps sync rows and partial-day seed
  rows" test (epic §4, §6). **Per-type** coverage (drop seed only for the metrics the sync replaced) was
  rejected: it leaves a day's rollup mixing seed+sync for the same metric, defeating "sync authoritative for
  that day", and the epic frames coverage **per day**, not per type (DB.md §7; epic R5).
- **Reconciliation never deletes `'sync'` rows and is idempotent** — it filters strictly on `origin='seed'`,
  and once a covered day's seed rows are gone a re-run finds nothing to delete (0 rows). A test asserts both
  (sync rows survive; second run deletes 0) (epic §4 "leaves 'sync' rows authoritative"; DB.md §7).
- **`workout_statistics` reconciled via its parent workout, not an `origin` filter** — the stats table has
  **no `origin`** column (E2·P2 / DB.md §1); it is keyed to a parent `workout`. Seed stats are written under
  seeded workouts and removed by deleting them **before** their **parent seed `workout`** (the FK has no
  `ON DELETE CASCADE`; round-1 #2), so they never orphan and never need an `origin` of their own (DB.md §1).
- **Idempotent seed via delete-`origin='seed'`-then-recopy** — a re-run wholesale-replaces the seed slice so
  re-running is safe and reproducible (mirrors E4·P1's wholesale-rebuild idempotency; epic determinism). It
  deletes only `origin='seed'` rows, never live `'sync'` data, so re-seeding after a sync is non-destructive
  to live rows (it would re-add seed rows that a later reconcile drops on covered days).
- **Offline scripts in `scripts/`, `baseline.db` read-only and never touched by `app/`** — ARCHITECTURE §6 /
  DB.md §0: the corpus is never opened at runtime. `seed_app_db.py` imports `app.core.healthkit` (whitelist)
  and `app.core.time` (period keys) but `app/` never imports the scripts or opens `baseline.db`; a check
  (`grep -REn "baseline\.db" app` → no hits) guards it. Plain `sqlite3` + stdlib; no FastAPI/SQLAlchemy/
  Alembic in the scripts.

## Risks

- **Window cut on a fixed offset instead of Europe/Sofia days** → a near-midnight sample lands on the wrong
  day, seeding ±1 day and skewing the first rollups — mitigation: the cut uses E2·P1's `period_date(dt)`
  (Sofia, DST-aware) on each sample's `start_date`; `test_seed_app_db.py` exercises a **DST boundary** (a
  winter `+0200` and a summer `+0300` near-midnight sample) and asserts each lands on the correct Sofia day
  and the correct side of the window (DB.md §0; ARCHITECTURE §4).
- **A non-whitelisted type leaks into the seed (or a whitelisted one is dropped)** → `app.db` stores data the
  engine never reads, or the briefs miss dietary/body-weight — mitigation: the copy filters `records.type`
  through `app.core.healthkit.is_whitelisted`; a test asserts dietary types **and** `body_mass` are present
  and a non-whitelisted `type` is **absent** after seeding (epic R4, §4; DB.md §1).
- **`uuid`/`origin` set wrong on seed rows** (non-NULL uuid, or `origin='sync'`) → seed rows collide on the
  UNIQUE(uuid) index or masquerade as live sync data, breaking reconciliation — mitigation: every seed
  `records`/`workouts` insert sets `uuid=NULL`, `origin='seed'`; a test asserts `uuid IS NULL AND
  origin='seed'` for **all** seeded `records`/`workouts` rows (DB.md §1; epic R3).
- **Seed tries to write a non-existent `activity_summary.origin` column** → an `OperationalError` on insert
  (DB.md §1 gives `activity_summary` no `origin`) — mitigation: the seed inserts `activity_summary` with the
  rings + the renamed `date` only (no `origin`), via a `date`-PK upsert; a test inserts/asserts the seeded
  row by its `date` PK and that the table has no `origin` column (round-1 #1; DB.md §1).
- **`activity_summary` not renamed (`date_components` left, or `date` empty)** → the day PK is wrong and the
  date-keyed rollups miss the rings — mitigation: the seed selects `date_components` from `baseline.db` and
  inserts it as `date`; a test asserts seeded `activity_summary.date` equals the source Sofia date and the
  row is addressable by that PK (DB.md §1, §6).
- **`workout_statistics` orphaned / mis-keyed after the copy** (FK still points at the old `baseline.db`
  workout id) → stats reference a non-existent workout — mitigation: insert each seed `workout`, capture its
  new `lastrowid`, and re-point its child stats' `workout_id`; a test asserts a seeded stat row's
  `workout_id` matches the inserted `workouts.id` (DB.md §1).
- **A parent seed `workout` delete fails because its `workout_statistics` children survive** (FK has no
  `ON DELETE CASCADE`, `foreign_keys=ON`) → `IntegrityError` on the seed re-run or the reconciliation —
  mitigation: both delete paths remove the child stats **before** the parent seed workouts; tests run the
  seed twice and run reconciliation over seeded+synced data and assert no `IntegrityError` and no orphaned
  stats (round-1 #2; E2·P2 FK).
- **Reconciliation deletes `'sync'` rows or keeps fully-covered seed rows** → live data lost, or stale seed
  duplicates a fully-synced day → double-counted rollups — mitigation: the delete is strictly
  `origin='seed' AND <day fully covered>`; tests assert fully-covered seed days are gone, sync rows survive,
  and partial-day seed rows remain (epic §4, §6; DB.md §7).
- **Reconciliation not idempotent** (a second run errors or deletes live rows) → re-running the maintenance
  op corrupts state — mitigation: it re-derives coverage from `origin` each run and deletes only remaining
  `origin='seed'` rows on covered days; a test runs it twice and asserts the second run deletes 0 (DB.md §7).
- **Seed not idempotent** (a re-run duplicates seed rows) — mitigation: the seed deletes `WHERE
  origin='seed'` (+ orphaned seed `workout_statistics`) before re-copying; a test runs the seed twice and
  asserts identical seeded rows / no duplication (epic determinism; mirrors E4·P1).
- **`baseline.db` opened at runtime / a script imported by `app/`** → violates the never-at-runtime rule —
  mitigation: the seed/reconcile live in `scripts/`, open `baseline.db` read-only (seed only), and `app/`
  never imports them; `grep -REn "baseline\.db" app` → no hits guards it (ARCHITECTURE §6; DB.md §0).
- **Tests read the real 1.5 GB corpus / a non-migrated `app.db`** → slow/flaky CI or wrong target schema —
  mitigation: tests build a tiny synthetic `baseline.db` and run the E2·P2 migration on a temp `app.db` in
  `tmp_path`; the real `../db/baseline.db` is never read (RESEARCH Constraints).

## Acceptance Criteria

- [ ] **Whitelist set finalized & complete** — `app.core.healthkit.WHITELISTED_TYPES` is a `frozenset`
      containing every activity/recovery identifier (HR, HRV SDNN, RHR, sleep analysis, steps, active +
      basal energy, PhysicalEffort, VO₂max, **`BodyMass`**, running speed/stride/vertical-osc/ground-
      contact/power) **and** every `HKQuantityTypeIdentifierDietary*` (energy/protein/carbs/fat/fiber/
      sodium/water); `is_whitelisted` is True for an in-set type and False for
      `HKQuantityTypeIdentifierEnvironmentalAudioExposure` (`tests/core/test_healthkit.py`). (epic R4; DB.md §1, §7)
- [ ] **90-day window bounds correct on Europe/Sofia days** — seeding over a synthetic `baseline.db` keeps
      samples whose **Sofia `period_date`** is within `[period_date(now) − days + 1 … period_date(now)]` and
      drops the rest, **including across a DST boundary** (a near-midnight `+0200`/`+0300` sample lands on the
      correct Sofia day and the correct side of the window) (`tests/scripts/test_seed_app_db.py`). (epic R3,
      §6; DB.md §0)
- [ ] **`origin='seed'` + `uuid=NULL` on seeded records/workouts** — after seeding, every seeded `records`
      and `workouts` row has `origin='seed'` and `uuid IS NULL`. (`activity_summary` has **no `origin`** —
      DB.md §1 — so it is seeded by its `date`-PK upsert, not flagged.)
      (`tests/scripts/test_seed_app_db.py`). (epic R3, §4; DB.md §1)
- [ ] **Whitelist filtering applied** — after seeding, **dietary** types and **`body_mass`** records are
      **present**, and a **non-whitelisted** `type` is **absent** from `records`
      (`tests/scripts/test_seed_app_db.py`). (epic R4, §4; DB.md §1)
- [ ] **Three-delta copy correct** — seeded `activity_summary.date` carries the renamed source Sofia date
      (no `date_components`; addressable by the `date` PK; the table has no `origin` column); a seeded
      `workout`'s `workout_statistics.workout_id` points at the new `workouts.id`;
      `effort_score`/`physical_effort` are NULL on seed workouts
      (`tests/scripts/test_seed_app_db.py`). (DB.md §1, §6)
- [ ] **Seed is idempotent** — running the seed twice into the same `app.db` yields identical seeded rows
      (no duplication; counts stable) (`tests/scripts/test_seed_app_db.py`). (epic determinism)
- [ ] **Reconciliation drops fully-covered seed days, keeps sync + partial-day seed rows** — with seed rows
      overlapping a simulated first `/sync`, `reconcile_seed` **deletes** `origin='seed'` rows in `records`
      and `workouts` (and the child `workout_statistics` of a deleted seed workout) on every Sofia day that
      has ≥1 `'sync'` row, **keeps** seed rows on days with **no** sync row, and **never deletes** `'sync'`
      rows; `activity_summary` is not reconciled (no `origin`; date-PK upsert) (`tests/scripts/
      test_reconcile_seed.py`). (epic R5, §4, §6; DB.md §7)
- [ ] **Reconciliation is idempotent** — a second `reconcile_seed` run over an already-reconciled `app.db`
      deletes 0 rows (`tests/scripts/test_reconcile_seed.py`). (DB.md §7)
- [ ] **Offline / never opened at runtime** — `! grep -REn "baseline\.db" app` (no `app/` module references
      the corpus); `scripts/seed_app_db.py` imports only `app.core.healthkit` + `app.core.time` from `app/`;
      `scripts/reconcile_seed.py` opens only `app.db`. (DB.md §0, §3; ARCHITECTURE §3, §6)
- [ ] **No dropped-stack leakage** — `! grep -REn "psycopg|pgvector|celery|redis|supabase|vecs" scripts`
      (the seed/reconcile are stdlib `sqlite3` only). (ARCHITECTURE §1)
- [ ] **Tests never read the real corpus** — tests build a synthetic `baseline.db` + a migrated temp `app.db`
      in `tmp_path`; `! grep -REn "\.\./db/baseline\.db|export\.xml" tests` finds no real-corpus reference.
      (RESEARCH Constraints)
- [ ] `uv run ruff check .` and `uv run pytest tests/core/test_healthkit.py tests/scripts/test_seed_app_db.py
      tests/scripts/test_reconcile_seed.py` pass.

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [ ] TASK-001: HealthKit type whitelist module
- [ ] TASK-002: Copy trailing 90 days from baseline.db to app.db with origin=seed (depends on TASK-001)
- [ ] TASK-003: Seed-sync reconciliation (depends on TASK-002)
- [ ] TASK-004: Final Validation
