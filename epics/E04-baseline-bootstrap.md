# E4 — Baseline ETL & Bootstrap

| | |
|---|---|
| **Status** | 🔵 ready for dev |
| **Phases** | 3 |
| **Depends on** | E2, E3 |
| **Unblocks** | day-one valid rollups for E6/E10/E11 |
| **Primary refs** | [`DB.md`](../docs/architecture/DB.md) §0, §6, §7 · [`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §3, §6 |

---

## 1. Summary & goal

The **offline build step**. Parse the Apple Health `export.xml` into the read-only **`baseline.db`**
corpus, **derive the constants** into `profile.yaml`, and **seed the trailing ~90 days** of whitelisted
samples into `app.db` so the **first** `/brief/weekly` has valid 7/28-day rollups and 30-day HRV/RHR
baselines on day one ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §3 Bootstrap;
[`DB.md`](../docs/architecture/DB.md) §6). After bootstrap, `app.db` grows from `/sync` forward and
`baseline.db` is never consulted again.

> `baseline.db` lives at `../db/` (the corpus: ~3.5M records, 925 workouts, 2019→2026). It is regenerated
> wholesale (`DROP TABLE …` then re-parse) and **never opened at runtime**
> ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §6).

## 2. Requirements

- **R1** — `build_db.py` re-parses `export.xml` into `baseline.db` as a raw ETL dump (no PKs/`uuid`, TEXT
  timestamps as Apple emits), **idempotent** via `DROP TABLE …` each run
  ([`DB.md`](../docs/architecture/DB.md) §0; [`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §6).
- **R2** — Constant derivation computes zones (`compute_zones.py`) and the athlete/threshold/nutrition
  constants and writes them to **`profile.yaml`** (the E3 schema), stamping `meta.derived_from`,
  `computed_at`, `constitution_version` ([`DB.md`](../docs/architecture/DB.md) §5, §6;
  [`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §6 deterministic computations).
- **R3** — The seed copies the **trailing ~90 days** of whitelisted samples into `app.db` ingest tables
  with **`origin = 'seed'`**, a near-straight copy modulo `uuid`/`origin` and the
  `date_components`→`date` rename ([`DB.md`](../docs/architecture/DB.md) §1, §6).
- **R4** — **Type whitelist** finalized: the activity/recovery types **and** the dietary types
  (`HKQuantityTypeIdentifierDietary*`) **and** `body_mass` — only whitelisted types are stored
  ([`DB.md`](../docs/architecture/DB.md) §1, §7 open item).
- **R5** — **Seed↔sync reconciliation**: live `'sync'` rows are authoritative; a one-time reconciliation
  drops `'seed'` rows for any day fully covered by synced data
  ([`DB.md`](../docs/architecture/DB.md) §7 open item — decide and implement).

## 3. What to implement (by phase)

### E4·P1 — build_db.py → baseline.db
- Stream-parse `export.xml` (records, workouts, workout statistics, activity summary) into `baseline.db`.
- Raw dump shape; idempotent wholesale rebuild; safe to re-run.
- A small summary report (counts per table) for sanity.

### E4·P2 — Derive constants → profile.yaml
- `compute_zones.py`: Z1–Z5 bpm bounds from maxHR/RHR.
- Derive `max_hr`, `rhr_baseline`, `hrv_baseline_ms`, `easy_hr_cap`, `cadence_target/current` and the
  nutrition block; write a **valid** `profile.yaml` (passes E3 validation).
- Stamp `meta`.

### E4·P3 — 90-day seed + reconciliation
- Copy trailing ~90 days of whitelisted samples → `app.db` (`records`/`workouts`/`workout_statistics`/
  `activity_summary`) with `origin='seed'`.
- Apply the finalized type whitelist (R4) incl. dietary + `body_mass`.
- Implement seed↔sync reconciliation (R5) as a callable run after the first live syncs.

## 4. Acceptance criteria

- [ ] Running `build_db.py` twice yields an identical `baseline.db` (idempotent), with non-zero counts
      across the four tables.
- [ ] Derivation writes a `profile.yaml` that **passes E3's validator**, with zones contiguous/monotonic
      and `meta` stamped.
- [ ] After seeding, `app.db` ingest tables hold ~90 days of `origin='seed'` rows; types outside the
      whitelist are absent; dietary + `body_mass` types are present.
- [ ] A simulated first `/sync` overlapping the seed window leaves `'sync'` rows authoritative and drops
      fully-covered `'seed'` days (reconciliation).
- [ ] `baseline.db` is never opened by any runtime code path (only by the build scripts).

## 5. Expected outcome

Day-one readiness: a populated `profile.yaml` and a seeded `app.db` so the first weekly/daily briefs have
valid rollups and baselines before any live sync.

## 6. Validation

- ETL test on a small fixture `export.xml` (counts + shape).
- Derivation test: zones from known maxHR/RHR; profile validates.
- Seed test: 90-day window bounds, `origin` flag, whitelist filtering; reconciliation drops the right
  seed rows and keeps sync rows.

## 7. Out of scope

The live `/sync` ingest path (E5), `daily_metrics` computation (E6). E4 only **builds and seeds**.
