# TASK-003: Whitelist filter shared with E4

Depends on: TASK-001
Suggested commit: `feat(sync): add wire-type to HealthKit whitelist bridge and record filter`

## Goal

Extend `app/core/healthkit.py` (E4·P3) with the wire↔HK bridge (`RECORD_TYPE_TO_HK`) and the pure
record-filter helpers (`is_record_type_whitelisted`, `filter_whitelisted_records`) that derive storage
membership **from** E4's existing `WHITELISTED_TYPES` frozenset — no second list.

## Files

- `app/core/healthkit.py` (extend; **do not duplicate** the E4·P3 `WHITELISTED_TYPES` / `is_whitelisted`)
  — add:
  - `RECORD_TYPE_TO_HK: dict[str, str]` — maps each `RecordType` **value** (e.g. `resting_heart_rate`)
    to its `HK…Identifier` (e.g. `HKQuantityTypeIdentifierRestingHeartRate`). Single source of the
    wire↔storage mapping.
  - `def is_record_type_whitelisted(record_type: str) -> bool` — `True` iff
    `RECORD_TYPE_TO_HK.get(record_type)` is in `WHITELISTED_TYPES` (via E4's `is_whitelisted`). Unknown
    wire strings → `False`.
  - `def filter_whitelisted_records(records: Iterable[HealthRecord]) -> list[HealthRecord]` — returns
    only records whose `type` (a `RecordType`, use `.value`) is whitelisted-for-storage. Pure, no IO.
    Import `HealthRecord` from `app.api.schemas.sync` (lazy/TYPE_CHECKING import if needed to avoid a
    core→api cycle; the runtime call passes already-parsed records).
- `tests/core/test_healthkit.py` (extend) — completeness test (every `RecordType` value has a
  `RECORD_TYPE_TO_HK` entry), agreement test (`is_record_type_whitelisted` agrees with `is_whitelisted`
  on the mapped identifier), and `filter_whitelisted_records` keep/drop behaviour.

## Acceptance

- [ ] Every `RecordType` value is a key in `RECORD_TYPE_TO_HK`
      (`set(RECORD_TYPE_TO_HK) == {m.value for m in RecordType}`).
- [ ] For every `RecordType` value `v`, `is_record_type_whitelisted(v) == is_whitelisted(RECORD_TYPE_TO_HK[v])`
      (the filter derives membership **from** E4's `WHITELISTED_TYPES`, no second list).
- [ ] `is_record_type_whitelisted("dietary_protein")` and `is_record_type_whitelisted("body_mass")` are
      `True`; `is_record_type_whitelisted("blood_glucose")` (unknown wire string) is `False`.
- [ ] `filter_whitelisted_records([...])` keeps whitelisted records (`dietary_protein`, `body_mass`) and
      drops a recognised-but-unstored `RecordType` value **if one exists** in E4's set; if E4's
      `WHITELISTED_TYPES` covers every `RecordType`, the test instead asserts an **unknown wire string**
      is rejected by the `RecordType` enum at `HealthRecord` parse time (so the rejection path is
      exercised either way — TASK-003 asserts the actual relationship at test time).
- [ ] `filter_whitelisted_records` is pure (no DB/IO) and order-preserving.

## Steps

### RED
- [ ] Extend `tests/core/test_healthkit.py` with the completeness, agreement, and keep/drop assertions
      above. Run — fails (symbols absent).

### GREEN
- [ ] Extend `app/core/healthkit.py`: build `RECORD_TYPE_TO_HK` mapping each `RecordType` value to its
      `HK…Identifier`, then `is_record_type_whitelisted` (delegating to `is_whitelisted`) and
      `filter_whitelisted_records`. Run — tests pass.

### REFACTOR
- [ ] Keep the map adjacent to `WHITELISTED_TYPES`; confirm no `WHITELISTED_TYPES` re-declaration;
      `ruff check` clean.

## Notes

`Workout` / `ActivitySummary` are **not** `type`-whitelisted — DB.md §1 gates `records.type` only, so the
filter applies to `HealthRecord`s alone. A wire type that the enum accepts but E4 does not store
(potentially `respiratory_rate`, `running_cadence`) is valid on the wire yet **filtered from storage** —
exactly the epic R3 "accepted on the wire, ignored for storage if non-whitelisted" behaviour. Single
source of truth: membership is derived from E4's `WHITELISTED_TYPES`; adding a wire type without a map
entry is caught by the completeness test, not silent drift.
