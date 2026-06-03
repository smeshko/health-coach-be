# TASK-001: RecordType enum and HealthRecord model (quantity and category)

Depends on: None
Suggested commit: `feat(sync): add RecordType enum and HealthRecord wire model`

## Goal

Add the `RecordType` enum (exact MODELS "Enums" value set) and the `HealthRecord` camelCase wire model
handling both quantity and category samples, in `app/api/schemas/sync.py`.

## Files

- `app/api/schemas/sync.py` (new) — module-level `RecordType(str, enum.Enum)` with the exact MODELS
  "Enums → `RecordType`" snake_case values, and `HealthRecord(CamelModel)` (imports the E1·P1
  `CamelModel` from `app/api/schemas/base.py`). Fields per MODELS "HealthRecord": `uuid: str`,
  `type: RecordType`, `start: datetime`, `end: datetime`, `value: float | None = None`,
  `unit: str | None = None`, `category: str | None = None`, `source: str | None = None`,
  `metadata: dict | None = None`.
- `tests/api/schemas/test_sync_models.py` (new) — tests for `RecordType` value set, `HealthRecord`
  quantity vs category, camelCase round-trip, dietary + `body_mass` acceptance, null-vs-absent.
- `tests/api/__init__.py`, `tests/api/schemas/__init__.py` (new, if the package needs them) — empty
  package markers so the test path imports.

## Acceptance

- [ ] `from app.api.schemas.sync import RecordType, HealthRecord` succeeds.
- [ ] `[m.value for m in RecordType]` equals the exact MODELS "Enums → `RecordType`" list (24 values:
      `heart_rate`, `heart_rate_variability_sdnn`, `resting_heart_rate`, `sleep_analysis`, `step_count`,
      `active_energy_burned`, `basal_energy_burned`, `physical_effort`, `vo2_max`, `body_mass`,
      `running_speed`, `running_power`, `running_cadence`, `running_stride_length`,
      `running_ground_contact_time`, `running_vertical_oscillation`, `respiratory_rate`,
      `dietary_energy_consumed`, `dietary_protein`, `dietary_carbohydrates`, `dietary_fat_total`,
      `dietary_fiber`, `dietary_sodium`, `dietary_water`) — asserted against an inline expected list.
- [ ] A quantity sample (`value=57.0`, `unit="count/min"`, `category=None`) and a category sample
      (`category="asleepDeep"`, `value=None`) both validate via `HealthRecord.model_validate(...)`.
- [ ] `type: "body_mass"`, `type: "dietary_protein"`, `type: "sleep_analysis"` parse; an unknown
      string (e.g. `type: "blood_glucose"`) raises `pydantic.ValidationError`.
- [ ] `HealthRecord(...).model_dump_json()` emits camelCase keys and parsing accepts **both** camelCase
      and snake_case input for any aliased field.
- [ ] Each optional field (`value`/`unit`/`category`/`source`/`metadata`) validates when **omitted**
      and when sent as explicit `null` (parametrised).
- [ ] A record carrying a nested `metadata` object parses (free passthrough).

## Steps

### RED
- [ ] Create `tests/api/schemas/test_sync_models.py` asserting the `RecordType` value list, the
      quantity/category cases, camelCase round-trip, dietary + `body_mass`, unknown-type rejection, and
      a parametrised omitted-vs-`null` test for each `HealthRecord` optional. Run — fails (no module).

### GREEN
- [ ] Create `app/api/schemas/sync.py`: `import enum`, `from datetime import datetime`,
      `from app.api.schemas.base import CamelModel`. Define `RecordType(str, enum.Enum)` with the exact
      MODELS values, then `HealthRecord(CamelModel)` with the fields above (optionals `T | None = None`).
      Add empty `__init__.py` package markers under `tests/api/` and `tests/api/schemas/` if needed.
      Run — tests pass.

### REFACTOR
- [ ] Order the enum members to match MODELS reading order; confirm `ruff check` is clean.

## Notes

`RecordType` members carry the **snake_case wire values** verbatim — these are *not* `HK…Identifier`
strings (the wire↔HK bridge is TASK-003). `HealthRecord` inherits `CamelModel`, which already sets
`alias_generator=to_camel`, `populate_by_name=True`, and `serialize_by_alias=True` (E1·P1), so
`model_dump_json()` emits camelCase without a `by_alias=True` at the call site. No cross-field
"exactly one of value/category" validator — MODELS does not mandate it (see PLAN Decisions).
