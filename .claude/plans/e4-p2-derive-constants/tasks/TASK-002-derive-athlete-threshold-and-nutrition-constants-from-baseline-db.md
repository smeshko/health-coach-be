# TASK-002: Derive athlete, threshold and nutrition constants from baseline.db

Depends on: TASK-001
Suggested commit: `feat(scripts): derive athlete/threshold/nutrition constants from baseline.db`

## Goal

Read the read-only `baseline.db` and compute the five-section constant set — the data-derived thresholds
(`max_hr`/`rhr_baseline`/`hrv_baseline_ms`/`cadence_current_spm`), the computed `easy_hr_cap` (Maffetone
180 − age), and the config anchors (`athlete`, `cadence_target_spm`, the whole `nutrition` block) — as an
in-memory dict, respecting the caps.

## Files

- `scripts/derive_constants.py` — **new** (the derivation core; the write/CLI lands in TASK-003):
  - **DB read helpers** (plain `sqlite3`, read-only): open `baseline.db`; a `_records(con, hk_type)` query
    pulling `value` (+ dates) for a given HK `type` from `records` (DB.md §1 raw shape: `records(type, unit,
    value, value_text, …, start_date, …)`, no `uuid`/`origin`).
  - **"Recent" window (rolling anchors only)**: the central-value anchors `rhr_baseline`,
    `hrv_baseline_ms`, `cadence_current_spm` are computed over the **trailing `RECENT_DAYS` (≈90) days from
    the latest sample** in the corpus (a `WHERE start_date >= <max(start_date) − 90d>` filter), so a 7-year
    corpus yields a *current* monthly anchor rather than a lifetime mean and the result is deterministic for
    a fixed corpus. `RECENT_DAYS` is a named module constant; the fixture/test pins which rows fall inside
    the window. (DB.md §5 "monthly anchor" / §6 trailing window intent.) **`max_hr` is NOT window-restricted**
    — see below.
  - **Thresholds derived from records** (constitution §3; DB.md §1/§5):
    - `derive_max_hr(con)` — the **bounded max** of `HKQuantityTypeIdentifierHeartRate` `value`s over the
      **whole corpus** (NOT the recent window): max HR is a near-stationary physiological ceiling "from
      observed boxing peaks" (constitution §3), so windowing it could miss the true peak if no recent
      max-effort session exists. Only **clamp to a physiological window** (drop `< HR_FLOOR≈80` and
      `> HR_CEILING≈220`) so an artifact spike can't inflate it. (A high percentile of the clamped samples
      is an acceptable extra-robust alternative, but the pinned behaviour the test asserts is the bounded
      max.) Returns an `int`.
    - `derive_rhr_baseline(con)` — median of in-window `HKQuantityTypeIdentifierRestingHeartRate` `value`s
      (robust monthly anchor; DB.md §5 ¹). Returns an `int`.
    - `derive_hrv_baseline_ms(con)` — median of in-window
      `HKQuantityTypeIdentifierHeartRateVariabilitySDNN` `value`s (ms; informational, DB.md §5). `int`.
    - `derive_cadence_current_spm(con)` — robust median of in-window running-cadence `value`s (DB.md §1
      "running cadence & dynamics"; the §5 `cadence_current_spm` "THIS month's cue"). The **exact** HK
      cadence record `type` (e.g. a `HKQuantityTypeIdentifierRunning…` cadence/step-rate identifier) is an
      implementation detail to **confirm against the real `baseline.db`/`export.xml`** the way E4·P1's
      RESEARCH inspected the corpus — pin it as a named constant `CADENCE_TYPE` rather than guessing here.
      `int`.
  - **Computed threshold**: `easy_hr_cap = 180 - age` (Maffetone; constitution §3 / DB.md §5 comment).
  - **Config anchors** (DB.md §5 / constitution §7 — not fitted from samples): a small `@dataclass`
    `DerivationConfig` (or a constants block) holding the `athlete` block (age=34, sex='male',
    height_cm=174, goal_weight_kg=75), `cadence_target_spm=172`, and the full `nutrition` anchor set
    (activity_factor=1.65, deficit_pct=0.12, protein_g_per_kg=1.8, fat_g_per_kg_low=0.8,
    fat_g_per_kg_high=1.0, carbs `{hard_low:4, hard_high:5, moderate:3, rest_low:2, rest_high:2.5}`,
    hydration_l_low=3.0, hydration_l_high=3.5, fiber_g_low=25, fiber_g_high=35) — the DB.md §5 anchors;
    injectable so a real deploy can override.
  - **`derive_constants(con, config) -> dict`** — assemble the five-section dict (`athlete`, `thresholds`
    incl. `zones` via `compute_zones(max_hr, rhr_baseline)`, `nutrition`, and a `meta` stub filled in
    TASK-003). Keys mirror DB.md §5 1:1 (snake_case).
- `tests/scripts/test_derive_constants.py` — **new**: a `_make_baseline_db(tmp_path, …)` helper creating a
  tiny `records` table with known HR/RHR/HRV/cadence rows (incl. an out-of-range HR spike); assert each
  derived value.

## Acceptance

- [ ] `derive_max_hr` over a fixture with corpus-wide HR values `{120,150,188,191, 235(spike)}` returns the
      bounded max (`191`, the `235` spike excluded by the physiological `HR_CEILING` clamp — **not** by any
      date window; max_hr is computed over the whole corpus). Include an HR sample **older than
      `RECENT_DAYS`** and assert it still counts toward `max_hr` (proving max_hr is not windowed).
- [ ] `derive_rhr_baseline` / `derive_hrv_baseline_ms` / `derive_cadence_current_spm` return the median of
      their **in-window** fixture rows (pinned expected ints); a sample dated **older than `RECENT_DAYS`**
      before the latest sample is excluded from the central value.
- [ ] `easy_hr_cap == 180 - age` (e.g. `146` at age 34).
- [ ] `derive_constants(...)` returns a dict whose `thresholds.zones` equals
      `compute_zones(derived_max_hr, derived_rhr)` and whose `nutrition.deficit_pct ≤ 0.20` and
      `protein_g_per_kg ≤ 2.0` (caps respected).
- [ ] Section keys mirror DB.md §5 exactly (so the dict can construct `Profile(**data)` in TASK-003).

## Steps

### RED
- [ ] `tests/scripts/test_derive_constants.py`: add `_make_baseline_db(tmp_path, hr=[…], rhr=[…], hrv=[…],
      cadence=[…])`; tests for each `derive_*` function asserting the pinned values incl. spike exclusion;
      a test asserting `derive_constants(...)["thresholds"]["zones"] == compute_zones(max_hr, rhr)` and the
      cap bounds.

### GREEN
- [ ] Implement the `sqlite3` read helpers + the `derive_*` functions + `derive_constants` (smallest code).

### REFACTOR
- [ ] Factor the percentile/median into a small numeric helper; bound HR samples with named floor/ceiling
      constants; type hints; cite the doc section in each function docstring. Open the DB read-only
      (`sqlite3.connect(f"file:{path}?mode=ro", uri=True)`).

## Notes

`rhr_baseline` here is the **monthly zone-derivation anchor**, NOT the live readiness baseline (DB.md §5 ¹
— readiness reads the rolling `daily_metrics` values; do not conflate). The `nutrition` block and `athlete`
block are **config anchors** (medical/clinician constants + profile inputs from constitution §7 / DB.md
§5), not numbers fitted from raw samples — only `max_hr/rhr/hrv/cadence_current` are data-derived and
`easy_hr_cap` is computed. Use plain `sqlite3` (no SQLAlchemy/`app/` import for the DB read); the only
`app/` import is `app.core.profile` in TASK-003 (the validator).
