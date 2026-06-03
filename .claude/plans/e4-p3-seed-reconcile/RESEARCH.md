# Research: E4·P3 — 90-day seed + reconciliation

Curated findings only — no raw conversation transcripts. Grounds the plan in
[`epics/E04-baseline-bootstrap.md`](../../../epics/E04-baseline-bootstrap.md) (§1, §2 R3/R4/R5, §3 E4·P3,
§4, §6, §7), [`docs/architecture/DB.md`](../../../docs/architecture/DB.md) §0, §1, §6, §7, and
[`docs/architecture/ARCHITECTURE.md`](../../../docs/architecture/ARCHITECTURE.md) §3, §6. **Depends on**
**E4·P1** (`baseline.db` raw corpus + `scripts/build_db.py`), **E2·P2** (the four `app.db` ingest models +
their `ingest_tables` Alembic revision), and **E2·P1** (`app/database/engine.py`, `app/core/time.py`
Europe/Sofia period-key helpers). This is the **final E4 phase**.

## Key Files & Directories

- `scripts/seed_app_db.py` — **new** (this phase): the offline seed build step. Copies the trailing ~90
  days of **whitelisted** samples from the read-only `baseline.db` (E4·P1) into the four `app.db` ingest
  tables with `origin='seed'`, `uuid=NULL`. CLI with `--baseline`/`--app-db`/`--now`/`--days` overrides so
  tests never touch the real corpus. Plain `sqlite3` + `app.core.time` (period helpers) + the whitelist
  module; **no** FastAPI/SQLAlchemy/Alembic; opens `baseline.db` **read-only**.
- `scripts/reconcile_seed.py` — **new** (this phase): the one-time seed↔sync reconciliation. A callable
  `reconcile_seed(conn)` run **after** the first live syncs that drops `origin='seed'` rows for any
  Europe/Sofia day **fully covered** by `origin='sync'` data, keeping all `'sync'` rows and partially-
  covered seed days. CLI `--app-db` override. Operates on `app.db` only — never opens `baseline.db`.
- `app/core/healthkit.py` — **new** (this phase, R4): the finalized HealthKit **type whitelist** (the exact
  `HK…Identifier` set) — the single source of truth for which sample `type`s are stored. **Shared with E5**
  (`/sync` filters incoming samples through the same set), so it lives in `app/` (importable at runtime),
  not `scripts/`. Pure data + helpers (`is_whitelisted(type)`, the frozenset constants); no DB/IO.
- `app/core/time.py` — **existing** (E2·P1): `period_date(dt) -> "YYYY-MM-DD"`, `iso_week(dt)`,
  `to_sofia(dt)`, all through `zoneinfo.ZoneInfo("Europe/Sofia")`, **DST-aware**, and they **reject naive
  datetimes**. The seed window bounds and the reconciliation's "which day is this row" both derive the day
  key through these helpers (DB.md §0 — period keys via Europe/Sofia, never a fixed offset). **Reused, not
  re-implemented.**
- `app/database/models/` — **existing** (E2·P2): `records`/`workouts`/`workout_statistics`/
  `activity_summary` SQLAlchemy models — the **target schema** the seed writes into (`records`/`workouts`
  add `uuid` + `origin`; `activity_summary` adds no `origin` and renames `date_components`→`date`;
  `workout_statistics` keeps no `origin`).
- `../db/baseline.db` — the read-only corpus (E4·P1 output) in the sibling `../db/` dir. Read **read-only**.
- `tests/scripts/test_seed_app_db.py`, `tests/scripts/test_reconcile_seed.py`,
  `tests/core/test_healthkit.py` — **new**: unit the whitelist set, an end-to-end seed over a tiny synthetic
  `baseline.db` + a migrated temp `app.db`, and the reconciliation rule over a seeded+synced temp `app.db`.

## Architecture Facts

- **The seed is a near-straight copy** (DB.md §1, §6; ARCHITECTURE §3): `baseline.db`'s four tables
  structurally **mirror** the `app.db` ingest tables, so the copy is column-for-column **modulo** exactly
  three deltas:
  1. add `uuid` → **`NULL`** for every seed row (DB.md §1 `records.uuid` "NULL for seeded rows");
  2. add `origin` → **`'seed'`** — but `origin TEXT NOT NULL` exists **only on `records` and `workouts`**
     (DB.md §1, lines 84 & 103). `activity_summary` has **no `origin`** (it is one row per Sofia day,
     upserted by the `date` PK) and `workout_statistics` has **no `origin`** (keyed to its parent workout);
  3. `activity_summary.date_components` → **`date`** (the rename happens at the seed, DB.md §1, §6).
  `effort_score`/`physical_effort` exist on `app.db.workouts` but **not** in `baseline.db`, so they are
  left **NULL** for seed rows (E2·P2 made them nullable; DB.md §1).
- **Trailing ~90 days window** (epic R3, §3 E4·P3; DB.md §6): copy only samples whose **Europe/Sofia day**
  falls in the trailing window so the first `/brief/weekly` has valid 7/28-day rollups and 30-day HRV/RHR
  baselines on day one (ARCHITECTURE §3 Bootstrap). The window end is "now" (Europe/Sofia); the start is
  `now − ~90 days`. **Day boundaries are Europe/Sofia** — the cut is on the **period_date** of each sample's
  `start_date`, not on a raw UTC instant, so a sample at `2026-03-04 00:30 +0200` counts as the Sofia day
  `2026-03-04` (DB.md §0; ARCHITECTURE §4). A small `SEED_DAYS` constant (default 90) controls the width.
- **Type whitelist — finalized exact set** (R4; DB.md §1, §7 open item). **Only** these `type`s are stored;
  everything else in `baseline.db` is skipped at copy. Activity / recovery:
  - `HKQuantityTypeIdentifierHeartRate`
  - `HKQuantityTypeIdentifierHeartRateVariabilitySDNN`
  - `HKQuantityTypeIdentifierRestingHeartRate`
  - `HKCategoryTypeIdentifierSleepAnalysis`
  - `HKQuantityTypeIdentifierStepCount`
  - `HKQuantityTypeIdentifierActiveEnergyBurned`
  - `HKQuantityTypeIdentifierBasalEnergyBurned`
  - `HKQuantityTypeIdentifierPhysicalEffort` (METs proxy)
  - `HKQuantityTypeIdentifierVO2Max`
  - `HKQuantityTypeIdentifierBodyMass` (body weight — single live-weight source, DB.md §1 callout)
  - `HKQuantityTypeIdentifierRunningSpeed`
  - `HKQuantityTypeIdentifierRunningStrideLength`
  - `HKQuantityTypeIdentifierRunningVerticalOscillation`
  - `HKQuantityTypeIdentifierRunningGroundContactTime`
  - `HKQuantityTypeIdentifierRunningPower`
  - `HKQuantityTypeIdentifierStepCount` covers cadence-derived step counts; the running-cadence/step-rate
    identifier varies by export version, so a named `CADENCE_TYPE` (`HKQuantityTypeIdentifierRunningSpeed`
    or the export's cadence id) is **confirmed against the real corpus**, not hard-guessed (matches E4·P2's
    `CADENCE_TYPE` resolution).
  - Dietary intake (DB.md §1 "Dietary intake (NEW)"; the `HKQuantityTypeIdentifierDietary*` family):
    `HKQuantityTypeIdentifierDietaryEnergyConsumed`, `HKQuantityTypeIdentifierDietaryProtein`,
    `HKQuantityTypeIdentifierDietaryCarbohydrates`, `HKQuantityTypeIdentifierDietaryFatTotal`,
    `HKQuantityTypeIdentifierDietaryFiber`, `HKQuantityTypeIdentifierDietarySodium`,
    `HKQuantityTypeIdentifierDietaryWater`.
  - The whitelist gates **`records`** (the per-sample table) by `type`. **`workouts`** are not `type`-keyed
    samples — every whitelisted-window workout session is seeded (with its `workout_statistics` children);
    `activity_summary` rings are per-day, also seeded by window. Whitelisting applies to `records.type`.
- **`origin='seed'` + `uuid=NULL`** (DB.md §1): seed rows carry no HealthKit UUID. The E2·P2 schema made
  `records.uuid` / `workouts.uuid` **UNIQUE but nullable**, and SQLite treats multiple `NULL`s as distinct,
  so all seed rows coexist under the unique index while a later live `'sync'` UUID is still deduped.
- **Seed↔sync reconciliation rule** (R5; DB.md §7 open item — **this phase decides + implements it**): live
  `'sync'` rows are **authoritative**. A one-time `reconcile_seed(conn)` (run **after** the first live
  syncs) **drops `origin='seed'` rows for any Europe/Sofia day that is FULLY covered by `'sync'` data**, and
  **keeps** seed rows on a day with **no** sync row (partially covered = not covered). The precise, decidable
  definition (see PLAN Decisions): **a day D is fully covered iff ≥1 `'sync'` row exists whose Sofia day is
  D** (the live sync, being the on-device HealthKit truth for that day, supersedes the seed estimate for that
  whole day). Reconciliation **never deletes `'sync'` rows** and is **idempotent** (a second run deletes 0).
  - **Scope = the origin-bearing tables `records` + `workouts` only.** `activity_summary` has **no `origin`**
    and is **upserted by the `date` PK**, so a live `/sync` for a day already overwrote that day's seed row
    by date — there is nothing left to reconcile; it is **excluded**. `workout_statistics` has **no `origin`**
    either — its seed rows are removed by deleting their **parent seed `workout`**, deleting the child stats
    **first** because the E2·P2 FK has **no `ON DELETE CASCADE`** and E2·P1 sets `PRAGMA foreign_keys=ON`
    (deleting a parent with surviving children would raise `IntegrityError`).
- **Day key is computed from `start_date`** for `records`/`workouts` (the sample/session's Sofia day) via
  E2·P1's `period_date`. `activity_summary` is keyed by its literal `date` (already a Sofia date after the
  rename) but is not part of reconciliation (DB.md §0–§1).
- **Offline build step, `baseline.db` never opened at runtime** (ARCHITECTURE §3, §6; DB.md §0): the seed
  and the reconciliation are **build/maintenance** scripts in `scripts/`. The **whitelist** module is the
  one piece that is **runtime-shared** (E5 `/sync` reuses it), so it lives in `app/core/`. `baseline.db` is
  never opened by `app/` — only `scripts/seed_app_db.py` reads it, read-only, at build time.
- **After bootstrap** `app.db` grows from `/sync` forward and `baseline.db` is never consulted again
  (ARCHITECTURE §3; DB.md §6). The seed is one-time; the reconciliation is one-time-after-first-syncs.

## Constraints

- **Reuse, don't re-implement.** The seed writes into the **E2·P2** schema (do not redefine the models);
  day keys come from **E2·P1** `app/core/time.py` (do not re-derive Sofia boundaries); the whitelist is the
  **single** type source shared with E5 (do not duplicate the set in `/sync`).
- **`baseline.db` read-only, never registered with Alembic, never opened by `app/`** (DB.md §0; ARCHITECTURE
  §6). `app/` may import the whitelist module (pure data) but must not open `baseline.db`.
- **Europe/Sofia day boundaries** for the 90-day window cut and the reconciliation day grouping (DB.md §0).
  Never assume a fixed `+03:00` — a sample near midnight in winter (`+0200`) vs summer (`+0300`) must land on
  the correct Sofia day. A test exercises a DST boundary.
- **Idempotent** seed and reconciliation: re-running the seed wholesale-replaces the `'seed'` rows — for
  `records`/`workouts` delete `WHERE origin='seed'` then re-copy (child `workout_statistics` deleted before
  their parent workouts, no `ON DELETE CASCADE`); `activity_summary` re-seeds via its `date`-PK upsert — so
  a re-run yields the same seeded state; re-running the reconciliation deletes 0 additional rows.
- **Whitelist filtering is exact:** dietary types **and** `body_mass` are present after seeding; a
  non-whitelisted `type` (e.g. `HKQuantityTypeIdentifierEnvironmentalAudioExposure`) is **absent**.
- **No big-file dependency in tests.** Tests build a tiny synthetic `baseline.db` + a migrated temp `app.db`
  in `tmp_path`; the real `../db/baseline.db` is never read by CI.
- **Dropped stack** — Postgres/pgvector, Celery, Redis, Supabase, streaming, RAG/`vecs` (ARCHITECTURE §1).
  The seed/reconcile use plain `sqlite3`; the whitelist is pure Python data.

## Useful Commands

```bash
# seed (offline, manual) — reads ../db/baseline.db, writes the trailing 90d into ./app.db ingest tables
uv run python scripts/seed_app_db.py                              # default paths
uv run python scripts/seed_app_db.py --baseline <in.db> --app-db <out.db> --now 2026-06-02 --days 90

# reconcile (one-time, after the first live syncs)
uv run python scripts/reconcile_seed.py --app-db ./app.db

# lint + tests (fixture-only; no big-file load)
uv run ruff check .
uv run pytest tests/scripts/test_seed_app_db.py tests/scripts/test_reconcile_seed.py tests/core/test_healthkit.py

# prove the runtime never opens baseline.db (only build scripts do)
grep -REn "baseline\.db" app && echo LEAK || echo clean
```

## Uncertainty

- **"Fully covered" definition for reconciliation.** DB.md §7 leaves the rule open ("drops `'seed'` rows for
  any day fully covered by synced data — *Needs a decision*"). **Resolved (this phase decides):** a Sofia day
  D is **fully covered iff ≥1 `'sync'` row exists whose Sofia day is D** — i.e. the device synced that day,
  so its live HealthKit data is the authoritative truth for D and the seed estimate is dropped wholesale for
  D. A day with **no** sync row keeps its seed rows (partially covered = not covered at all). This is the
  simplest decidable, idempotent rule that satisfies the epic's "keeps sync rows and partial-day seed rows"
  test (epic §6). Per-`type` coverage (drop seed only for `type`s the sync replaced) was considered but
  rejected: it leaves a day's rollup mixing seed+sync for the same metric, defeating "sync is authoritative
  for that day", and the epic frames coverage **per day**, not per type. Documented as a Decision.
- **Whether the whitelist module lives in `app/` or `scripts/`.** **Resolved:** `app/core/healthkit.py` —
  the NOTES + DB.md §1 say it is **shared with E5** (`/sync` filters through the same set), so it must be
  importable at runtime; it is pure data (no `baseline.db` access), so it does not violate the
  never-open-baseline-at-runtime rule. The seed script imports it; E5's `/sync` will too.
- **Exact running-cadence `type`.** Varies by export version (same finding as E4·P2). **Resolved:** a named
  `CADENCE_TYPE` constant confirmed against the real corpus; the whitelist set + tests are agnostic to the
  exact string (the fixture inserts rows under whatever `CADENCE_TYPE` is set). Step count
  (`HKQuantityTypeIdentifierStepCount`) is whitelisted regardless.
- **Which tables carry `origin`.** **Resolved against DB.md §1:** `origin TEXT NOT NULL` is on **`records`
  (l.84) and `workouts` (l.103) only**. `activity_summary` (one row/day, upserted by `date` PK) and
  `workout_statistics` (keyed to a parent workout) have **none**. So: the seed sets `origin='seed'` only on
  `records`/`workouts`; `activity_summary` is seeded via a `date`-PK upsert (which also makes the re-seed
  idempotent and lets a later `/sync` overwrite the day); reconciliation scopes to `records`/`workouts`
  (excluding `activity_summary`). Seed `workout_statistics` are written under seeded workouts and removed by
  deleting their **parent seed `workout`** — child stats **first** (the E2·P2 FK has no `ON DELETE CASCADE`
  and `foreign_keys=ON`, so a parent delete with surviving children would raise `IntegrityError`) — never by
  an `origin` filter on the stats table.
- **Default `--baseline` / `--app-db` paths.** **Resolved:** default `--baseline` = sibling
  `../db/baseline.db` (E4·P1 output); default `--app-db` = the runtime `app.db` (the E1·P1
  `settings.app_db_path`); both CLI-overridable so tests use `tmp_path`. `--now` (default today Europe/Sofia)
  and `--days` (default 90) make the window deterministic for tests.

## References

- `epics/E04-baseline-bootstrap.md` §1, §2 (R3/R4/R5), §3 (E4·P3), §4, §6, §7
- `docs/architecture/DB.md` §0 (two-DB shape, TEXT timestamps, Europe/Sofia period keys), §1 (the four
  ingest tables + the `uuid`/`origin` additions + `date_components`→`date` rename + the whitelisted-type
  list incl. dietary + `body_mass`), §6 (bootstrap: seed trailing ~90 days with `origin='seed'`), §7
  (decision 2/8; the two open items this phase resolves — whitelist set + seed↔sync reconciliation)
- `docs/architecture/ARCHITECTURE.md` §3 (data model / Bootstrap), §6 (`baseline.db` is a build input,
  never opened at runtime; deterministic computations)
- `.claude/plans/e2-p2-ingest-tables/` (the four ingest models + constraints this seed targets),
  `.claude/plans/e2-p1-db-engine-alembic/` (`app/core/time.py` Europe/Sofia helpers; `app/database/engine.py`),
  `.claude/plans/e4-p1-build-db-etl/` (the `baseline.db` raw schema this seed reads)
