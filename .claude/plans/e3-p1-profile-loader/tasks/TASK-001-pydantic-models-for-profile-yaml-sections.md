# TASK-001: Pydantic models for profile.yaml sections

Depends on: None
Suggested commit: `feat(core): add typed Pydantic models for profile.yaml sections`

## Goal

Define the five typed Pydantic models mirroring DB.md §5 (`Athlete`, `Thresholds`, `Zones`, `Nutrition`
with nested `CarbsPerKg`, `Meta`) and the root `Profile`, with field names matching the §5 yaml keys
exactly and `extra="forbid"` on every model — structure only (validators land in TASK-002).

## Files

- `app/core/profile.py` — new: the models. Each is a plain `pydantic.BaseModel` (NOT the E1·P1 camelCase
  wire base — this is internal config read as-is), configured `model_config = ConfigDict(extra="forbid")`:
  - `Athlete`: `age: int`, `sex: str`, `height_cm: int`, `goal_weight_kg: float`.
  - `Thresholds`: `max_hr: int`, `rhr_baseline: int`, `hrv_baseline_ms: int`, `easy_hr_cap: int`,
    `cadence_target_spm: int`, `cadence_current_spm: int`.
  - `Zones`: `z1: tuple[int, int]`, … `z5: tuple[int, int]` (each `[low, high]`).
  - `CarbsPerKg`: `hard_low: float`, `hard_high: float`, `moderate: float`, `rest_low: float`,
    `rest_high: float` — all required, no defaults.
  - `Nutrition`: `activity_factor: float`, `deficit_pct: float`, `protein_g_per_kg: float`,
    `fat_g_per_kg_low: float`, `fat_g_per_kg_high: float`, `carbs_g_per_kg: CarbsPerKg`,
    `hydration_l_low: float`, `hydration_l_high: float`, `fiber_g_low: float`, `fiber_g_high: float`.
  - `Meta`: `derived_from: str`, `computed_at: datetime.date`, `constitution_version: str`.
  - `Profile`: `athlete: Athlete`, `thresholds: Thresholds`, `zones: Zones`, `nutrition: Nutrition`,
    `meta: Meta`.
- `tests/core/__init__.py` / `tests/core/test_profile.py` — new: construction tests over the models built
  directly from dicts (no loader yet — that is TASK-002).

## Acceptance

- [ ] `Profile(**valid_dict)` constructs with all five sections; field values round-trip
      (`p.thresholds.max_hr == 192`, `p.nutrition.carbs_g_per_kg.hard_low == 4`, `p.zones.z1 == (96, 125)`,
      `p.meta.computed_at == date(2026, 6, 2)`).
- [ ] A missing carb multiplier (e.g. no `rest_high`) raises `pydantic.ValidationError` naming the missing
      field (structural — required field, no default).
- [ ] An unknown/stray key in any section raises `ValidationError` (`extra="forbid"`).
- [ ] A missing section (e.g. no `meta`) raises `ValidationError`.
- [ ] `Profile`'s schema exposes **no** field for current weight / rolling HRV-or-RHR-30d / per-day metrics
      (assert `body_weight`/`current_weight`/`hrv_30d`/`rhr_30d`/`readiness` absent across the nested
      models' `model_fields`).

## Steps

### RED
- [ ] `tests/core/test_profile.py`: a `valid_dict` fixture (the DB.md §5 values); assert `Profile(**d)`
      constructs and field values match; assert dropping a carb key / a section / adding a stray key each
      raises `ValidationError`; assert the static-vs-live name-absence.

### GREEN
- [ ] Implement the six models in `app/core/profile.py` with `extra="forbid"` and the exact field names.

### REFACTOR
- [ ] Keep field names 1:1 with DB.md §5 yaml keys; no camelCase aliasing (internal config); group the
      models top-to-bottom in section order.

## Notes

Field names must mirror DB.md §5 **exactly** (`height_cm`, `hrv_baseline_ms`, `cadence_current_spm`,
`carbs_g_per_kg`, etc.) — the E3·P2 constitution template and E8 macro engine read these keys. This is
internal config, so do **not** inherit the E1·P1 camelCase wire base and do **not** alias to camelCase.
Validators (caps, monotonic/contiguous zones, fat low≤high, max_hr>rhr) and the YAML loader are TASK-002 —
this task is models + `extra="forbid"` only.
