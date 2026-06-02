# TASK-003: Example profile.yaml and constant accessors

Depends on: TASK-002
Suggested commit: `feat(core): ship example profile.yaml and constant accessors`

## Goal

Ship the DB.md §5 example `profile.yaml` verbatim at the app/repo root (so E8/E9 have constants before E4
generates them) and add the accessors E8 (zone bounds + nutrition constants) and E9
(`constitution_version`) call — reading static fields only.

## Files

- `profile.yaml` — new, at the app/repo root (the `PROFILE_PATH` default from TASK-002): the **DB.md §5
  block verbatim** —
  - `athlete`: age 34, sex male, height_cm 174, goal_weight_kg 75.
  - `thresholds`: max_hr 192, rhr_baseline 58, hrv_baseline_ms 38, easy_hr_cap 146, cadence_target_spm 172,
    cadence_current_spm 160.
  - `zones`: `z1: [96, 125]`, `z2: [125, 150]`, `z3: [150, 167]`, `z4: [167, 177]`, `z5: [177, 192]`.
  - `nutrition`: activity_factor 1.65, deficit_pct 0.12, protein_g_per_kg 1.8, fat_g_per_kg_low 0.8,
    fat_g_per_kg_high 1.0, `carbs_g_per_kg: { hard_low: 4, hard_high: 5, moderate: 3, rest_low: 2,
    rest_high: 2.5 }`, hydration_l_low 3.0, hydration_l_high 3.5, fiber_g_low 25, fiber_g_high 35.
  - `meta`: derived_from baseline.db, computed_at 2026-06-02, constitution_version v1.
  - Keep the explanatory comments from §5 (the file is hand-edited / git-diffed).
- `app/core/profile.py` — add accessors on `Profile` (read-only, static fields only):
  - `zone_bounds(self) -> dict[str, tuple[int, int]]` — `{"z1": (96,125), …, "z5": (177,192)}` (E8).
  - `constitution_version` is already `self.meta.constitution_version: str` (E9) — optionally a thin
    convenience property `constitution_version` on `Profile` delegating to `meta`.
  - The nutrition constants are reachable via `self.nutrition` (E8 reads `deficit_pct`, `activity_factor`,
    `protein_g_per_kg`, `fat_g_per_kg_*`, `carbs_g_per_kg.*`, hydration, fiber) — no live/derived value is
    exposed.
- `tests/core/test_profile.py` — extend: load the **shipped** `profile.yaml` via `load_profile()` (default
  path) and assert the accessors; assert the static-vs-live absence over the full model.

## Acceptance

- [ ] `load_profile()` (no arg) loads the committed `profile.yaml` into a `Profile` with no error.
- [ ] `p.zone_bounds() == {"z1": (96,125), "z2": (125,150), "z3": (150,167), "z4": (167,177),
      "z5": (177,192)}`.
- [ ] `p.nutrition.deficit_pct == 0.12`, `p.nutrition.carbs_g_per_kg.hard_high == 5`,
      `p.nutrition.protein_g_per_kg == 1.8` (E8 constants reachable).
- [ ] `p.meta.constitution_version == "v1"` (and `p.constitution_version == "v1"` if the convenience
      property is added) (E9 stamp).
- [ ] The shipped file passes all TASK-002 validators (it is the known-valid §5 example).
- [ ] No live/derived field is exposed by `Profile` or its accessors (re-assert the name-absence guard
      against the real loaded model).

## Steps

### RED
- [ ] `tests/core/test_profile.py`: add a test that calls `load_profile()` (default path) and asserts
      `zone_bounds()`, the nutrition constants, and `constitution_version`; re-assert static-vs-live
      absence.

### GREEN
- [ ] Write `profile.yaml` (DB.md §5 verbatim) at the app/repo root; add `zone_bounds()` (and the optional
      `constitution_version` property) to `Profile`.

### REFACTOR
- [ ] Keep accessors returning plain static values (tuples/floats/str) — no DB reads, no derived math; the
      macro engine (E8) and renderer (E9) own that. Ensure `profile.yaml` is committed (not gitignored).

## Notes

`profile.yaml` is the §5 block **verbatim** — this is the starting fixture so E8 (macros/zones) and E9
(render inputs) have constants before E4 derives the real ones from `baseline.db`. Accessors read **static**
fields only: current weight, 30d HRV/RHR baselines, and per-day metrics live in `daily_metrics` (the DB),
not here (DB.md §5 table + ¹). Confirm the file is not caught by `.gitignore` (it must ship).
