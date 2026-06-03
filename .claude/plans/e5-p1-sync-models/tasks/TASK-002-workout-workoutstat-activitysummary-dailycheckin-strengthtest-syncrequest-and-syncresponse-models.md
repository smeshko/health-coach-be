# TASK-002: Workout, WorkoutStat, ActivitySummary, DailyCheckin, StrengthTest, SyncRequest and SyncResponse models

Depends on: TASK-001
Suggested commit: `feat(sync): add remaining /sync request and response wire models`

## Goal

Add the remaining seven `/sync` wire models (`WorkoutStat`, `Workout`, `ActivitySummary`,
`DailyCheckin`, `StrengthTest`, `SyncRequest`, `SyncResponse`) to `app/api/schemas/sync.py`, all
inheriting `CamelModel`, matching MODELS "POST /sync" field-for-field.

## Files

- `app/api/schemas/sync.py` (extend) — add, each `(CamelModel)`:
  - `WorkoutStat` — `type: str`, `value: float`, `unit: str`.
  - `Workout` — `uuid: str`, `type: str`, `start: datetime`, `end: datetime`, `duration_s: float`,
    `distance_m: float | None = None`, `active_energy_kcal: float | None = None`,
    `effort_score: int | None = None`, `zone_minutes: dict[str, float] | None = None`,
    `statistics: list[WorkoutStat] = []`. (snake_case Python names → camelCase wire `durationS`,
    `distanceM`, `activeEnergyKcal`, `effortScore`, `zoneMinutes` via the alias generator.)
  - `ActivitySummary` — `date: date`, `active_energy_kcal: float`, `exercise_minutes: int`,
    `stand_hours: int`, `steps: int | None = None`.
  - `DailyCheckin` — `date: date`, `gi_symptoms: bool`, `knee_pain: int = Field(ge=0, le=10)`,
    `illness: bool`. **No weight/body-mass field.**
  - `StrengthTest` — `date: date`, `max_pushups: int`, `max_pullups: int`.
  - `SyncRequest` — `records: list[HealthRecord] = []`, `workouts: list[Workout] = []`,
    `activity_summary: list[ActivitySummary] = []`, `checkin: DailyCheckin | None = None`,
    `strength_test: StrengthTest | None = None`.
  - `SyncResponse` — `records_upserted: int`, `records_duplicate: int`, `workouts_upserted: int`,
    `activity_days_upserted: int`, `checkin_saved: bool`, `strength_test_saved: bool`,
    `server_time: datetime`.
- `tests/api/schemas/test_sync_models.py` (extend) — tests for the new models: camelCase wire keys,
  `DailyCheckin` objective-only + bounded `knee_pain`, `SyncRequest` defaults, null-vs-absent on
  `SyncRequest.checkin`/`strengthTest` and workout/activity optionals, full `SyncRequest` round-trip
  from the MODELS example JSON.

## Acceptance

- [ ] All seven models import and instantiate; `SyncRequest`/`SyncResponse` `model_fields` match the
      MODELS "POST /sync" tables.
- [ ] `SyncResponse(...).model_dump_json()` emits `recordsUpserted`, `recordsDuplicate`,
      `workoutsUpserted`, `activityDaysUpserted`, `checkinSaved`, `strengthTestSaved`, `serverTime`
      (camelCase); a `Workout` emits `durationS`, `distanceM`, `activeEnergyKcal`, `effortScore`,
      `zoneMinutes`; `ActivitySummary` emits `activeEnergyKcal`/`exerciseMinutes`/`standHours`;
      `DailyCheckin` emits `giSymptoms`/`kneePain`; `StrengthTest` emits `maxPushups`/`maxPullups`.
      Parsing accepts both camelCase and snake_case.
- [ ] `"weight" not in DailyCheckin.model_fields` and `"bodyMass" not in DailyCheckin.model_fields`.
- [ ] `DailyCheckin` with `kneePain` ∈ {0, 10} validates; `kneePain` ∈ {-1, 11} raises
      `ValidationError`.
- [ ] `SyncRequest.model_validate({})` succeeds with `records==[]`, `workouts==[]`,
      `activitySummary==[]`, `checkin is None`, `strengthTest is None`.
- [ ] `SyncRequest.checkin`/`strengthTest` and the `Workout`/`ActivitySummary` optionals each parse
      when omitted and when explicitly `null`.
- [ ] The MODELS "SyncRequest" example JSON (3 records + checkin) round-trips:
      `SyncRequest.model_validate_json(EXAMPLE)` then `.model_dump_json()` preserves the camelCase keys.

## Steps

### RED
- [ ] Extend `test_sync_models.py` with the assertions above (camelCase dumps, `DailyCheckin` no-weight
      + bounded `kneePain`, `SyncRequest` defaults, null-vs-absent params, MODELS-example round-trip).
      Run — fails (models absent).

### GREEN
- [ ] Extend `app/api/schemas/sync.py`: add `from datetime import date`, `from pydantic import Field`,
      and define the seven models in dependency order (`WorkoutStat` → `Workout`; leaf models;
      `SyncRequest` last among requests; `SyncResponse`). Run — tests pass.

### REFACTOR
- [ ] Confirm field ordering mirrors the MODELS tables; `ruff check` clean; no unused imports.

## Notes

`Workout.type` and `WorkoutStat.type` are free `str` (not enums) — MODELS types them as open HealthKit
activity-type / stat-type strings (PLAN Decisions). `zone_minutes` is `dict[str, float] | None` (not a
typed `Zone` map) to stay tolerant of the `z1…z5` payload. `knee_pain` uses `Field(ge=0, le=10)` per
MODELS "integer 0–10". These models define the `SyncResponse` *shape* only; populating its counts from DB
writes is E5·P2 (out of scope here).
