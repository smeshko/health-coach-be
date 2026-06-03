# Plan: E5·P1 — Sync wire models & type whitelist

Status: draft
Risk: small
Created: 2026-06-03

> Epic **E5 — Sync / Ingest (`POST /sync`)**, phase **P1** (the first of three). Source of truth:
> [`epics/E05-sync-ingest.md`](../../../epics/E05-sync-ingest.md) (§1 summary, §2 **R1** camelCase wire
> models / **R2** `RecordType` + quantity/category / **R3** whitelist / **R7** objective-only check-in, §3
> **E5·P1**, §4 acceptance, §6 validation, §7 out-of-scope) · grounded in
> [`docs/architecture/MODELS.md`](../../../docs/architecture/MODELS.md) **"Conventions"** (camelCase wire /
> snake_case Python via `alias_generator`; **"Nulls vs absent"** — optional = `null` or omitted), **"Enums →
> `RecordType`"** (the exact value list incl. the seven `dietary_*` and `body_mass`), and the **"POST /sync"**
> section (`SyncRequest`, `HealthRecord`, `Workout`, `WorkoutStat`, `ActivitySummary`, `DailyCheckin`,
> `StrengthTest`, `SyncResponse` — field-for-field) and
> [`docs/architecture/DB.md`](../../../docs/architecture/DB.md) **§1** (ingest tables; "only the whitelisted
> types … are stored"; `body_mass` is the single live-weight source — **no body-weight field on the
> check-in**).
>
> **Depends on E1·P1** (`app/api/schemas/base.py` `CamelModel` — `alias_generator=to_camel`,
> `populate_by_name=True`, **`serialize_by_alias=True`**; the `T | None = None` null-vs-absent convention)
> and **E4·P3** (`app/core/healthkit.py` — the finalized `HK…Identifier` whitelist `WHITELISTED_TYPES` +
> `is_whitelisted`, shared at runtime). This phase is **MODELS + whitelist filter only** — the idempotent
> upsert / DB writes / `daily_metrics` recompute are **E5·P2 / E5·P3**.

## Goal

Ship the camelCase `POST /sync` request/response Pydantic models (`SyncRequest`, `HealthRecord`, `Workout`,
`WorkoutStat`, `ActivitySummary`, `DailyCheckin`, `StrengthTest`, `SyncResponse`) plus a shared wire-level
type-whitelist filter (reusing E4's `app/core/healthkit.py`) that rejects/ignores non-whitelisted record
types — exactly matching MODELS.md "POST /sync" + "Enums".

## Scope

- **`app/api/schemas/sync.py`** (TASK-001, TASK-002) — all `/sync` wire models, each inheriting the E1·P1
  `CamelModel` base (so the wire is camelCase, Python stays snake_case, and `model_dump_json()` emits
  camelCase without `by_alias=True`):
  - **`RecordType`** (TASK-001) — a `str, enum.Enum` whose **values are the exact MODELS.md "Enums →
    `RecordType`" snake_case strings**: `heart_rate`, `heart_rate_variability_sdnn`, `resting_heart_rate`,
    `sleep_analysis`, `step_count`, `active_energy_burned`, `basal_energy_burned`, `physical_effort`,
    `vo2_max`, `body_mass`, `running_speed`, `running_power`, `running_cadence`, `running_stride_length`,
    `running_ground_contact_time`, `running_vertical_oscillation`, `respiratory_rate`, and the seven dietary
    types `dietary_energy_consumed`, `dietary_protein`, `dietary_carbohydrates`, `dietary_fat_total`,
    `dietary_fiber`, `dietary_sodium`, `dietary_water`.
  - **`HealthRecord`** (TASK-001) — handles **both** quantity samples (`value` + `unit`) and **category**
    samples (`category`, e.g. sleep stage). Fields per MODELS.md "HealthRecord": `uuid: str`,
    `type: RecordType`, `start: datetime`, `end: datetime`, `value: float | None = None`,
    `unit: str | None = None`, `category: str | None = None`, `source: str | None = None`,
    `metadata: dict | None = None`. Optionals are `T | None = None` (accept omission **and** explicit
    `null` per MODELS "Nulls vs absent").
  - **`WorkoutStat`** (TASK-002) — `{ type: str, value: float, unit: str }` (`type` ∈ `avg_hr` `max_hr`
    `avg_speed` `max_speed` `avg_power` `avg_cadence`).
  - **`Workout`** (TASK-002) — `uuid: str`, `type: str` (HealthKit activity type — free string, e.g.
    `boxing`/`running`), `start: datetime`, `end: datetime`, `durationS: float`, `distanceM: float | None`,
    `activeEnergyKcal: float | None`, `effortScore: int | None`, `zoneMinutes: dict[str, float] | None`,
    `statistics: list[WorkoutStat] = []`.
  - **`ActivitySummary`** (TASK-002) — `date: date`, `activeEnergyKcal: float`, `exerciseMinutes: int`,
    `standHours: int`, `steps: int | None = None`.
  - **`DailyCheckin`** (TASK-002) — **objective-only**: `date: date`, `giSymptoms: bool`,
    `kneePain: int` (0–10, validated), `illness: bool`. **No body-weight field** (weight is a `body_mass`
    record — DB.md §1; MODELS DailyCheckin).
  - **`StrengthTest`** (TASK-002) — `date: date`, `maxPushups: int`, `maxPullups: int`.
  - **`SyncRequest`** (TASK-002) — `records: list[HealthRecord] = []`, `workouts: list[Workout] = []`,
    `activitySummary: list[ActivitySummary] = []`, `checkin: DailyCheckin | None = None`,
    `strengthTest: StrengthTest | None = None`.
  - **`SyncResponse`** (TASK-002) — `recordsUpserted: int`, `recordsDuplicate: int`, `workoutsUpserted: int`,
    `activityDaysUpserted: int`, `checkinSaved: bool`, `strengthTestSaved: bool`, `serverTime: datetime`.
- **`app/core/healthkit.py`** (TASK-003) — **extended, not duplicated**. Add the bridge between the wire
  snake_case `RecordType` and the existing `HK…Identifier` `WHITELISTED_TYPES` frozenset (E4·P3), plus a
  wire-level filter:
  - `RECORD_TYPE_TO_HK: dict[str, str]` — maps each `RecordType` **value** (e.g. `resting_heart_rate`) to its
    `HK…Identifier` (e.g. `HKQuantityTypeIdentifierRestingHeartRate`). The single mapping point so the wire
    enum and the storage whitelist never drift.
  - `def is_record_type_whitelisted(record_type: str) -> bool` — `True` iff the wire `type` maps to an
    `HK…Identifier` in the existing `WHITELISTED_TYPES` (derives membership **from** E4's frozenset; adds no
    second list).
  - `def filter_whitelisted_records(records: Iterable[HealthRecord]) -> list[HealthRecord]` — drops records
    whose `type` is not whitelisted-for-storage; pure (no DB/IO), so `/sync` (E5·P2) calls it before the
    upsert. (`Workout` / `ActivitySummary` are **not** `type`-whitelisted — DB.md §1 gates `records.type`
    only.)
- **Tests** (TASK-001 `tests/api/schemas/test_sync_models.py`; TASK-003 extends
  `tests/core/test_healthkit.py`):
  - **Round-trip camelCase** — a `HealthRecord` / `SyncResponse` `model_dump_json()` emits **camelCase** keys
    (`activeEnergyKcal`, `recordsUpserted`, …); parsing accepts **both** camelCase and snake_case input.
  - **Quantity vs category** — a quantity sample (`value`+`unit`, `category=None`) and a category sample
    (`category="asleepDeep"`, `value=None`) both validate.
  - **Dietary + `body_mass` accepted** — `type: "dietary_protein"` and `type: "body_mass"` parse.
  - **Non-whitelisted filtered** — `is_record_type_whitelisted` is `False` for a recognised-but-unstored
    `RecordType` value if any (see Decisions) and `filter_whitelisted_records` drops it; an **unknown** wire
    string (not a `RecordType` value) raises a Pydantic validation error.
  - **Optional null-vs-absent** — every optional field accepts **omission** and explicit `null` (parametrised).
  - **Objective-only check-in** — `DailyCheckin` has **no** weight/bodyMass field; `kneePain` outside 0–10 is
    rejected.

## Out of Scope

- **The `POST /sync` route, idempotent upsert, and `SyncResponse` count derivation** — **E5·P2** (epic §3
  E5·P2). This phase defines the response *model* but does not populate it from DB writes.
- **Check-in / strength-test upsert, ISO-week derivation, and the `daily_metrics` recompute fan-out** —
  **E5·P3** (epic §3 E5·P3). The models exist here; the persistence + recompute hook are later.
- **The `records` / `workouts` / `activity_summary` / `checkins` / `strength_tests` SQLAlchemy tables** —
  owned by **E2·P2 / E2·P3**; this phase maps **onto** them but defines no ORM models or migrations.
- **Defining the `HK…Identifier` whitelist set itself** — owned by **E4·P3** (`app/core/healthkit.py`
  `WHITELISTED_TYPES`). This phase **reuses** it and only adds the wire↔HK bridge + the record filter; it
  does not re-list or alter the storage whitelist.
- **Auth on `/sync` (`unauthorized` envelope)** — the bearer dependency is **E1·P2**; wired onto the route in
  **E5·P2**. No endpoint here, so no auth here.
- **Dropped stack** — Postgres/pgvector, Celery, Redis, Supabase, streaming, RAG/`vecs` (ARCHITECTURE §1).
  Pure Pydantic models + a pure-Python filter.

## Research Summary

The `/sync` wire contract is fully specified in [`MODELS.md`](../../../docs/architecture/MODELS.md) "POST
/sync": eight models with **camelCase** field names on the wire (Swift `Codable`-friendly), Python snake_case
behind the E1·P1 `CamelModel` `alias_generator` — so this phase is a faithful transcription, not a design.
The `RecordType` **enum** (MODELS "Enums") is **snake_case wire values** (`resting_heart_rate`,
`dietary_protein`, `body_mass`, …); the E4·P3 storage whitelist (`app/core/healthkit.py`) is keyed by
**`HK…Identifier`** strings — so the one genuine design decision is the **bridge** (`RECORD_TYPE_TO_HK` map +
`is_record_type_whitelisted`) that derives wire-type acceptance **from** the existing frozenset, keeping a
single source of truth (DB.md §1 "only the whitelisted types … are stored"). `HealthRecord` is the one model
with real shape logic — it carries **both** quantity (`value`+`unit`) and category (`category`) samples, so
those fields are all optional `T | None = None` (MODELS HealthRecord; "Nulls vs absent"). `DailyCheckin` is
**objective-only** with **no** body-weight field — weight arrives as a `body_mass` record (MODELS
DailyCheckin; DB.md §1 callout). Timestamps are `datetime` carrying the device's actual offset (MODELS
"Conventions → Timestamps"); dates are `YYYY-MM-DD` (`datetime.date`).

## Decisions

- **Models live in `app/api/schemas/sync.py`, one module, inheriting `CamelModel`** (NOTES; E1·P1). All
  eight `/sync` models are one cohesive wire contract; co-locating them in `app/api/schemas/sync.py` mirrors
  the E1·P1 schemas package layout and lets every model share the camelCase base in one import. `CamelModel`
  already sets `serialize_by_alias=True`, so raw `model_dump_json()` emits camelCase **without** a
  `by_alias=True` at the call site (E1·P1 TASK-004) — the route in E5·P2 gets correct wire JSON for free.
- **`RecordType` values are the MODELS snake_case strings, not the `HK…Identifier`s** (MODELS "Enums").
  The wire enum is what the Swift client sends/receives; MODELS "Enums → `RecordType`" lists snake_case
  values (`resting_heart_rate`, `dietary_protein`, `body_mass`). The storage whitelist's `HK…Identifier`
  form (E4·P3) is an **internal** detail; the two are bridged by `RECORD_TYPE_TO_HK` (see next), never
  conflated. This keeps the wire contract exactly as MODELS specifies while reusing E4's frozenset as the
  single storage authority.
- **Bridge the wire enum to E4's whitelist via a `RECORD_TYPE_TO_HK` map in `app/core/healthkit.py` — reuse,
  don't duplicate** (NOTES "reuse the shared HK type whitelist module"; DB.md §1). The wire-level filter
  derives membership **from** `WHITELISTED_TYPES` (`record_type → HK identifier ∈ WHITELISTED_TYPES`), so
  there is exactly **one** list of stored types. The map lives in `healthkit.py` (next to the set it bridges)
  so E5·P2's `/sync` and any future caller import one module. Adding a wire type without whitelisting it (or
  vice-versa) is then caught by a completeness test, not silent drift.
- **`RecordType` covers MODELS "Enums" verbatim, including types not in E4's storage whitelist (e.g.
  `respiratory_rate`, `running_cadence`)** (MODELS "Enums"; DB.md §1). MODELS lists `respiratory_rate` and
  `running_cadence` in `RecordType`; E4·P3's `WHITELISTED_TYPES` is the *stored* subset (it has no
  `RespiratoryRate`; `running_cadence` resolves to E4's `CADENCE_TYPE`). So the **enum** accepts them on the
  wire (valid `type`), but `is_record_type_whitelisted` returns the storage answer per E4's frozenset — a
  recognised wire type can still be **filtered from storage**. This is precisely the "accepted on the wire,
  ignored for storage if non-whitelisted" behaviour the epic R3 asks for, and gives the whitelist test a real
  recognised-but-unstored case. (If E4's `WHITELISTED_TYPES` in fact covers every `RecordType`, the test uses
  an **unknown wire string** rejected by the enum as the "non-whitelisted/rejected" case instead — either way
  the rejection path is exercised; TASK-003 asserts the actual relationship.)
- **`HealthRecord` makes quantity/category fields all optional** (MODELS HealthRecord; "Nulls vs absent").
  A quantity sample carries `value`+`unit` (`category` null); a category sample carries `category` (`value`
  null) — so `value`, `unit`, `category` are each `T | None = None`. No cross-field "exactly one of" validator
  is added (MODELS does not mandate it and category samples may also carry a `value`); the model stays a
  faithful transcription. `source` / `metadata` are likewise optional.
- **`DailyCheckin` is objective-only with `kneePain` bounded 0–10 and no weight field** (epic R7; MODELS
  DailyCheckin; DB.md §1). The check-in is `date`/`giSymptoms`/`kneePain`/`illness` only — body weight comes
  from the `body_mass` HealthRecord (single live-weight source), so adding a weight tap would create dedup
  ambiguity. `kneePain` is constrained to `0–10` (`Field(ge=0, le=10)`) per MODELS ("integer 0–10").
- **`Workout.type` and `WorkoutStat.type` are free `str`, not enums** (MODELS Workout/WorkoutStat). MODELS
  types `Workout.type` as a free "HealthKit activity type" string (`running`, `boxing`,
  `functional_strength`, …) — open-ended, so a `str` (not an enum) matches the contract. `WorkoutStat.type`
  is documented with a fixed 6-value set but MODELS shows it as a bare string in the JSON; it is kept `str`
  to match the wire and avoid rejecting a forward-compatible stat type (the epic lists no validation on it).
- **`zoneMinutes` is `dict[str, float] | None`, not a typed `Zone` map** (MODELS Workout). MODELS types it
  `object<Zone, number> | null`; modelling the keys as a plain `str→float` dict accepts the `z1…z5` payload
  without coupling this wire model to the `Zone` enum (defined elsewhere for briefs) and keeps `/sync`
  tolerant of an extra/absent zone key. Defaulted `None` (optional per the JSON `null`).

## Risks

- **Field name or casing drift from MODELS "POST /sync"** → the Swift client can't (de)serialise. Mitigation:
  every field name is transcribed field-for-field from the MODELS table; a round-trip test asserts the
  **actual** wire JSON keys are camelCase (`activeEnergyKcal`, `recordsUpserted`, `durationS`, …) via raw
  `model_dump_json()`, and that both casings parse on input (MODELS "Conventions → Casing").
- **The whitelist gets duplicated and drifts from E4·P3** → `/sync` stores types the seed wouldn't (or drops
  ones it keeps). Mitigation: the wire filter derives membership **from** E4's existing `WHITELISTED_TYPES`
  via `RECORD_TYPE_TO_HK` (no second list); a completeness test asserts every `RecordType` value has a map
  entry and that `is_record_type_whitelisted` agrees with `is_whitelisted` on the mapped identifier (NOTES;
  DB.md §1).
- **An optional field rejects omission or explicit `null`** → valid payloads 422 (MODELS "Nulls vs absent"
  says both mean "not provided"). Mitigation: every optional is `T | None = None`; a parametrised test posts
  each optional **omitted** and as explicit `null` and asserts both parse (matches E1·P1 TASK-004's convention).
- **A body-weight field sneaks onto `DailyCheckin`** → two live-weight sources, dedup ambiguity (DB.md §1
  forbids it). Mitigation: `DailyCheckin` is exactly `date`/`giSymptoms`/`kneePain`/`illness`; a test asserts
  no `weight`/`bodyMass` field exists (`"weight" not in DailyCheckin.model_fields`) and that posting one is
  rejected by `extra="forbid"` (or ignored if not forbidding — see Decisions; the test pins the chosen
  behaviour).
- **`kneePain` accepts out-of-range values** → the safety gate (§6.2) mis-fires downstream. Mitigation:
  `Field(ge=0, le=10)`; a test asserts `kneePain=11` and `kneePain=-1` are rejected and `0`/`10` accepted
  (MODELS "integer 0–10").
- **A non-whitelisted / unknown record type slips through** → `/sync` would later store data the engine never
  reads. Mitigation: `filter_whitelisted_records` drops non-whitelisted recognised types; an **unknown** wire
  string is rejected by the `RecordType` enum at parse time. Both paths are tested (epic R3, §4).
- **`metadata` typed too strictly** → a real HealthKit passthrough object 422s. Mitigation: `metadata` is
  `dict | None = None` (free passthrough per MODELS "passthrough extras"); a test parses a record with a
  nested `metadata` object.

## Acceptance Criteria

- [ ] **All eight `/sync` models exist in `app/api/schemas/sync.py`, inherit `CamelModel`, and match MODELS
      field-for-field** — `SyncRequest`, `HealthRecord`, `Workout`, `WorkoutStat`, `ActivitySummary`,
      `DailyCheckin`, `StrengthTest`, `SyncResponse` import and instantiate; their `model_fields` match the
      MODELS "POST /sync" tables (`tests/api/schemas/test_sync_models.py`). (epic R1; MODELS "POST /sync")
- [ ] **Wire JSON is camelCase (round-trip)** — `HealthRecord(...).model_dump_json()` and
      `SyncResponse(...).model_dump_json()` emit camelCase keys (`activeEnergyKcal`, `recordsUpserted`,
      `durationS`, `giSymptoms`, `maxPushups`, `serverTime`); parsing accepts **both** camelCase **and**
      snake_case input (`tests/api/schemas/test_sync_models.py`). (epic R1; MODELS "Conventions → Casing")
- [ ] **`RecordType` enum is exactly the MODELS value set** — its values equal the MODELS "Enums →
      `RecordType`" list (incl. the seven `dietary_*` and `body_mass`); `body_mass`, `dietary_protein`,
      `sleep_analysis` parse on a `HealthRecord.type` (`tests/api/schemas/test_sync_models.py`). (epic R2;
      MODELS "Enums")
- [ ] **`HealthRecord` handles quantity *and* category samples** — a quantity record (`value`+`unit`,
      `category=None`) and a category record (`category="asleepDeep"`, `value=None`) both validate and
      round-trip (`tests/api/schemas/test_sync_models.py`). (epic R2; MODELS HealthRecord)
- [ ] **Optional fields accept omission *and* explicit `null`** — every `T | None = None` field (record
      `value`/`unit`/`category`/`source`/`metadata`; `ActivitySummary.steps`; `SyncRequest.checkin`/
      `strengthTest`; workout optionals) parses when **omitted** and when sent as `null`
      (`tests/api/schemas/test_sync_models.py`, parametrised). (MODELS "Nulls vs absent")
- [ ] **Check-in is objective-only with bounded knee pain** — `DailyCheckin` has **no** weight/`bodyMass`
      field (`"weight" not in DailyCheckin.model_fields`); `kneePain` ∈ 0–10 (11 and −1 rejected, 0 and 10
      accepted) (`tests/api/schemas/test_sync_models.py`). (epic R7; MODELS DailyCheckin; DB.md §1)
- [ ] **Whitelist filter shared with E4 — non-whitelisted rejected/ignored, no duplication** —
      `app/core/healthkit.is_record_type_whitelisted` / `filter_whitelisted_records` derive membership from
      E4's `WHITELISTED_TYPES` via `RECORD_TYPE_TO_HK`; every `RecordType` value has a map entry; a
      recognised-but-unstored type (or, if none, an unknown wire string) is **dropped/rejected**; a
      whitelisted type (`dietary_protein`, `body_mass`) is **kept** (`tests/core/test_healthkit.py`). (epic
      R3; DB.md §1)
- [ ] `uv run ruff check .` and `uv run pytest tests/api/schemas/test_sync_models.py
      tests/core/test_healthkit.py` pass.

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [ ] TASK-001: RecordType enum and HealthRecord model (quantity and category)
- [ ] TASK-002: Workout, WorkoutStat, ActivitySummary, DailyCheckin, StrengthTest, SyncRequest and SyncResponse models (depends on TASK-001)
- [ ] TASK-003: Whitelist filter shared with E4 (depends on TASK-001)
- [ ] TASK-004: Final Validation
