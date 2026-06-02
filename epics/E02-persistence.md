# E2 — Persistence Layer (`app.db`)

| | |
|---|---|
| **Status** | 🔵 ready for dev |
| **Phases** | 3 |
| **Depends on** | E1 |
| **Unblocks** | E4, E5, E6, E10, E11 |
| **Primary refs** | [`DB.md`](../docs/architecture/DB.md) §0–§4 · [`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §3 |

---

## 1. Summary & goal

Create the **runtime database** `app.db` — SQLAlchemy models + Alembic migrations + WAL — covering all
**nine tables** from [`DB.md`](../docs/architecture/DB.md): four ingest, one derived cache, two
coaching-state inputs, two brief-cache outputs. `app.db` is the **only** database the running API reads or
writes; `baseline.db` is a build input and must never be opened at runtime
([`DB.md`](../docs/architecture/DB.md) §0).

## 2. Requirements

- **R1** — **SQLite in WAL mode**, small and backed up; Alembic-owned, never dropped
  ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §1 Persistence; [`DB.md`](../docs/architecture/DB.md) §0).
- **R2** — All timestamps stored as **ISO-8601 TEXT carrying the offset HealthKit emits per sample** (it
  varies — never hard-code `+0300`). Period keys (`date`, `iso_week`) derived through the **Europe/Sofia tz
  database** (DST-aware) ([`DB.md`](../docs/architecture/DB.md) §0; [`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §4).
- **R3** — **Exactly 9 tables, no `profile` table** — constants live in `profile.yaml` (E3), not the DB
  ([`DB.md`](../docs/architecture/DB.md) §0, §5).
- **R4** — Ingest tables structurally **mirror `baseline.db`** plus two additions: a unique `uuid`
  (idempotency) and an `origin` flag (`'seed'` | `'sync'`) ([`DB.md`](../docs/architecture/DB.md) §1).
- **R5** — Uniqueness/indexing exactly as specified: `records.uuid` UNIQUE + `(type,start_date)` +
  `(start_date)`; `workouts.uuid` UNIQUE; `workout_statistics(workout_id,type)`; `strength_tests.iso_week`
  UNIQUE; `plans.iso_week` UNIQUE; `suggestions.date` UNIQUE ([`DB.md`](../docs/architecture/DB.md) §1–§4).

## 3. What to implement (by phase)

### E2·P1 — DB engine, WAL & Alembic init
- SQLAlchemy engine + session factory against `app.db`; **WAL pragma** on connect.
- Alembic configured to target `app.db` **only** (never `baseline.db`).
- Timestamp convention helpers + **Europe/Sofia** period-key helpers (`date`, `iso_week`) used by all
  later epics.
- Declarative base + naming conventions for stable migration autogen.

### E2·P2 — Ingest tables
- `records` — `id` PK, `uuid` UNIQUE (nullable for seed), `type`, `unit`, `value`, `value_text`,
  provenance, `creation_date`/`start_date`/`end_date`, `origin`. Indexes per R5.
- `workouts` — `uuid` UNIQUE, `activity_type`, duration/distance/energy (+units), `effort_score` (RPE 1–10,
  nullable), `physical_effort` (METs, nullable), provenance, dates, `origin`.
- `workout_statistics` — FK → `workouts(id)`, `type`, dates, `sum`/`average`/`minimum`/`maximum`, `unit`;
  index `(workout_id, type)`.
- `activity_summary` — `date` PK (upsert by date), move/exercise/stand/move-time + goals.

### E2·P3 — Derived & coaching-state tables
- `daily_metrics` — `date` PK; sleep/HRV/RHR, `hrv_30d_mean`/`hrv_30d_sd`/`rhr_30d_mean`, steps,
  active_energy, `z1_min..z5_min`, nutrition intake (`kcal_in`, `protein_in_g`, `carbs_in_g`, `fat_in_g`,
  `fiber_in_g`, `sodium_in_mg`, `water_in_l`), `body_weight`, `hard_day`, `readiness_score` (nullable),
  `band`, `computed_at`.
- `checkins` — `date` PK; `gi_symptoms`, `illness`, `knee_pain` (0–10), `created_at`/`updated_at`.
- `strength_tests` — `id` PK, `date`, `iso_week` UNIQUE, `max_pushups`, `max_pullups`, `created_at`.
- `plans` — `id` PK, `iso_week` UNIQUE, `payload` (JSON), `rationale`, `inputs_snapshot` (JSON), `model`,
  `constitution_version`, `created_at`.
- `suggestions` — `id` PK, `date` UNIQUE, `readiness_score`, `band`, `safety_gate_tripped`, `gate_reason`,
  `payload` (JSON), `inputs_snapshot` (JSON), `model`, `constitution_version`, `created_at`.

## 4. Acceptance criteria

- [ ] `alembic upgrade head` builds a fresh `app.db` containing **exactly** the 9 tables, in WAL mode.
- [ ] `alembic downgrade base` then `upgrade head` round-trips cleanly.
- [ ] Inserting a duplicate `uuid` into `records`/`workouts` is rejected by the UNIQUE constraint;
      duplicate `iso_week` in `plans`/`strength_tests` and duplicate `date` in `suggestions` are rejected.
- [ ] No `profile` table exists; constants are not stored in the DB.
- [ ] Models round-trip every column type (REAL/INTEGER/TEXT) with ISO-8601 TEXT timestamps preserved
      verbatim.
- [ ] Period-key helpers return correct `date`/`iso_week` across a DST boundary (EET↔EEST).

## 5. Expected outcome

A migrated, WAL-mode `app.db` with every table the three endpoints read/write — the storage substrate for
E4 (seed), E5 (ingest), E6 (derived), E10/E11 (brief cache).

## 6. Validation

- Migration up/down/up test on a temp file DB.
- Constraint tests (unique uuid/iso_week/date).
- Period-key helper unit tests incl. a DST transition and a travel offset.

## 7. Out of scope

Writing data (E5), computing `daily_metrics` values (E6), `profile.yaml` (E3), seeding from `baseline.db`
(E4).
