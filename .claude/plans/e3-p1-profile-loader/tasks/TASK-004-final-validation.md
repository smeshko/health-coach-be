# TASK-004: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for e3-p1-profile-loader`

## Goal

Confirm every PLAN.md acceptance criterion is met with a concrete, non-circular check (named command or
test): the typed `Profile` loads a valid file and the shipped §5 example, each invalid case (caps,
monotonicity, contiguity, missing carb key, fat low>high, max_hr≤rhr, stray key) raises a clear
`ValidationError`, the accessors return the E8/E9 constants, and no live/derived value is sourced from
`profile.yaml`.

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked.
- [ ] **Lint:** `uv run ruff check .` passes with no issues.
- [ ] **Tests:** `uv run pytest tests/core/test_profile.py` passes (all loader + validation tests green).

### Acceptance-criteria mapping (1:1, concrete)

- [ ] **Valid file loads into the typed model** — `uv run pytest tests/core/test_profile.py -k "valid and
      load"` proves `load_profile(<valid temp yaml>)` returns a `Profile` whose field values equal the yaml
      (`max_hr == 192`, `carbs_g_per_kg.hard_low == 4`, `zones.z1 == (96, 125)`). (epic §4; DB.md §5)
- [ ] **Shipped example loads** — `uv run pytest tests/core/test_profile.py -k "example or default"` proves
      `load_profile()` (default app-root path) loads the committed `profile.yaml` with no error; **also**
      `uv run python -c "from app.core.profile import load_profile; p=load_profile(); print(p.meta.constitution_version)"`
      exits 0 and prints `v1`. (epic §3 E3·P1; DB.md §5)
- [ ] **Deficit cap** — `uv run pytest tests/core/test_profile.py -k "deficit"` proves `deficit_pct = 0.25`
      raises `ValidationError` naming `deficit_pct` and that `0.20` is accepted (inclusive boundary).
      (epic R2; DB.md §5)
- [ ] **Protein cap** — `uv run pytest tests/core/test_profile.py -k "protein"` proves `protein_g_per_kg =
      2.5` raises `ValidationError` naming `protein_g_per_kg` and `2.0` is accepted. (epic R2; DB.md §5)
- [ ] **Non-monotonic zones** — `uv run pytest tests/core/test_profile.py -k "monotonic"` proves a zone set
      with `low >= high` (or non-increasing lows) raises `ValidationError`. (epic R2; DB.md §5)
- [ ] **Non-contiguous zones** — `uv run pytest tests/core/test_profile.py -k "contiguous or contiguity"`
      proves a monotonic-but-gapped set (`z1=[96,124]`, `z2=[125,150]`) raises `ValidationError`.
      (epic R2; DB.md §5)
- [ ] **Missing carb multiplier** — `uv run pytest tests/core/test_profile.py -k "carb and missing"` proves
      omitting one of `{hard_low,hard_high,moderate,rest_low,rest_high}` raises `ValidationError` naming the
      missing field. (epic R2; DB.md §5)
- [ ] **Fat low > high** — `uv run pytest tests/core/test_profile.py -k "fat"` proves `fat_g_per_kg_low >
      fat_g_per_kg_high` raises `ValidationError`. (epic R2; DB.md §5)
- [ ] **max_hr > rhr** — `uv run pytest tests/core/test_profile.py -k "max_hr or rhr"` proves `max_hr <=
      rhr_baseline` raises `ValidationError`. (epic R2; DB.md §5)
- [ ] **Unknown / stray key rejected** — `uv run pytest tests/core/test_profile.py -k "extra or stray or
      unknown"` proves an extra key in any section raises `ValidationError` (`extra="forbid"`).
      (Decision; epic R1)
- [ ] **Exact key set equals DB.md §5 (positive allowlist, not just banned names)** — `uv run pytest
      tests/core/test_profile.py -k "keyset or schema_keys"` proves `set(Section.model_fields)` equals the
      **frozen expected set** for every section (`athlete`={age,sex,height_cm,goal_weight_kg};
      `thresholds`={max_hr,rhr_baseline,hrv_baseline_ms,easy_hr_cap,cadence_target_spm,cadence_current_spm};
      `zones`={z1,z2,z3,z4,z5}; `nutrition`={activity_factor,deficit_pct,protein_g_per_kg,fat_g_per_kg_low,
      fat_g_per_kg_high,carbs_g_per_kg,hydration_l_low,hydration_l_high,fiber_g_low,fiber_g_high} with
      `carbs_g_per_kg`={hard_low,hard_high,moderate,rest_low,rest_high}; `meta`={derived_from,computed_at,
      constitution_version}) — so a defaulted extra field (e.g. `sleep_hours`, `body_mass`) is caught even
      though it would never appear in input YAML. **Includes the ROOT model:** assert
      `set(Profile.model_fields) == {"athlete","thresholds","zones","nutrition","meta"}` (a defaulted
      top-level field like `daily_metrics`/`body_mass` on `Profile` is caught — section-level
      `extra="forbid"` and nested keyset checks would miss it), and assert the shipped `profile.yaml`
      top-level keys equal the same set. (Codex round-1 #1 + round-2 #1; DB.md §5; epic R1/R3)
- [ ] **Accessors return the constants E8/E9 need** — `uv run pytest tests/core/test_profile.py -k
      "accessor or zone_bounds or version"` proves `p.zone_bounds()["z5"] == (177,192)`,
      `p.nutrition.deficit_pct == 0.12`, and `p.meta.constitution_version == "v1"`. (epic R1; DB.md §5;
      LLM.md §2)
- [ ] **No live/derived value sourced from the file** — `uv run pytest tests/core/test_profile.py -k
      "static or live or absent"` proves `Profile` (and its nested sections) expose **no** field named
      `body_weight`/`current_weight`/`hrv_30d`/`rhr_30d`/`readiness` (name-absence over `model_fields`);
      **also** `! grep -nE "body_weight|current_weight|hrv_30d|rhr_30d|readiness" app/core/profile.py
      profile.yaml` finds nothing. (epic R3; DB.md §5 table + ¹)
- [ ] **Lint + suite** — `uv run ruff check .` and `uv run pytest tests/core/test_profile.py` both pass.

- [ ] `PLAN.md` acceptance criteria all met (each mapped above).
