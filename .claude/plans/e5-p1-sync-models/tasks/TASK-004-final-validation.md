# TASK-004: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for e5-p1-sync-models`

## Goal

Confirm every PLAN.md acceptance criterion is met by a concrete, non-circular check, and the plan is
production-ready.

## Steps

- [ ] All task checkboxes in `PLAN.md` (TASK-001..003) are ticked.

### Lint + test gates
- [ ] `uv run ruff check .` passes with no errors.
- [ ] `uv run pytest tests/api/schemas/test_sync_models.py tests/core/test_healthkit.py` passes.

### Acceptance criteria — one concrete check each (maps 1:1 to PLAN.md "Acceptance Criteria")
- [ ] **AC1 — all eight models exist, inherit `CamelModel`, match MODELS field-for-field.**
      `uv run python -c "from app.api.schemas.sync import SyncRequest, HealthRecord, Workout, WorkoutStat, ActivitySummary, DailyCheckin, StrengthTest, SyncResponse"` exits 0; the
      `model_fields`-vs-MODELS assertions in `tests/api/schemas/test_sync_models.py` pass.
- [ ] **AC2 — wire JSON is camelCase (round-trip).** The round-trip tests in
      `test_sync_models.py` assert `HealthRecord(...).model_dump_json()` and
      `SyncResponse(...).model_dump_json()` contain `activeEnergyKcal`/`recordsUpserted`/`durationS`/
      `giSymptoms`/`maxPushups`/`serverTime` and that both camelCase and snake_case inputs parse.
- [ ] **AC3 — `RecordType` is exactly the MODELS value set.** The `test_record_type_values` test
      asserts `[m.value for m in RecordType]` equals the 24-value MODELS list (incl. the seven
      `dietary_*` and `body_mass`); `body_mass`/`dietary_protein`/`sleep_analysis` parse on
      `HealthRecord.type`.
- [ ] **AC4 — `HealthRecord` handles quantity *and* category.** The quantity-sample and category-sample
      (`category="asleepDeep"`, `value=None`) tests in `test_sync_models.py` validate and round-trip.
- [ ] **AC5 — optionals accept omission *and* `null`.** The parametrised omitted-vs-`null` test in
      `test_sync_models.py` covers record `value`/`unit`/`category`/`source`/`metadata`,
      `ActivitySummary.steps`, `SyncRequest.checkin`/`strengthTest`, and the workout optionals.
- [ ] **AC6 — check-in objective-only with bounded knee pain.** The `test_daily_checkin` cases assert
      `"weight" not in DailyCheckin.model_fields`, `kneePain` ∈ {-1, 11} rejected, {0, 10} accepted.
- [ ] **AC7 — whitelist filter shared with E4, no duplication.** The completeness + agreement tests in
      `tests/core/test_healthkit.py` assert every `RecordType` value has a `RECORD_TYPE_TO_HK` entry,
      `is_record_type_whitelisted` agrees with `is_whitelisted` on the mapped identifier, a
      whitelisted type (`dietary_protein`/`body_mass`) is kept, and a non-whitelisted/unknown type is
      dropped/rejected. Confirm `WHITELISTED_TYPES` is declared once (E4·P3) —
      `uv run python -c "import ast,inspect,app.core.healthkit as h; src=inspect.getsource(h); assert src.count('WHITELISTED_TYPES =') <= 1"` (or grep the module) — no second list.
- [ ] **AC8 — lint + targeted tests pass** (the two gate commands above).

### Boundaries
- [ ] No `POST /sync` route, ORM model, migration, or auth dependency was added (scope is models +
      filter only); `grep -rn "APIRouter\|@router.post" app/api/schemas/sync.py` returns nothing.
- [ ] `app/core/healthkit.py` did not re-declare or alter `WHITELISTED_TYPES` (reuse from E4·P3).
