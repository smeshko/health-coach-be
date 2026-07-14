# Plan: Runtime measured max-HR anchor source (Phase 19.6)

Status: in-progress
Branch: fix/phase-19-6-runtime-measured-max-hr
Risk: high
Epic: 19 — Make the numbers trustworthy (audit wave 2, tracked in the iOS repo's docs/artifacts/epics/19-trustworthy-numbers.md)
Phase: 19.6 — Runtime measured max-HR anchor source
Created: 2026-07-14

## Goal

Supply the **runtime measured max-HR source** that Phase 19.4 left missing, turning the
zone-rederivation merge from a documented production no-op into a live path. Build a
`measured_max_hr(session, as_of, current_max_hr)` query — a SQLAlchemy port of the offline
`scripts/derive_constants.py:derive_max_hr` — and feed its value into the
`rederive_zones(...)` call in `RecomputeConstants.process`, so a genuine measured
max-HR shift observed in the `records` table re-derives the HR zones end-to-end in the
weekly recompute, while a quiet window or a sensor artifact can never move the anchor.

## Scope

- **New `measured_max_hr(session, as_of, current_max_hr)` in `app/services/recompute.py`** (alongside
  `rederive_zones` — see Decisions D1). Properties, all correctness-critical because
  max-HR anchors EVERY zone bound:
  - **Whole-corpus bounded MAX** over `records.value` (NOT date-windowed — a recent
    window could miss the true peak), clamped to the physiological window
    `HR_FLOOR (80) .. HR_CEILING (205)` — parity with the offline derivation.
  - **Dual type-alias match**: `records.type IN ("heart_rate",
    "HKQuantityTypeIdentifierHeartRate")` — seed rows store the HK identifier, live
    `/sync` rows store the snake_case wire alias. Alias set derived from
    `app.core.healthkit.RECORD_TYPE_TO_HK` (single source of truth), not hardcoded.
  - **`as_of` cutoff — device-local-date, conservative-inclusive**: a single lexical
    upper bound on `records.start_date` (ISO-8601 TEXT) — `start_date < (as_of + 1 day)`
    prefix — so the whole-corpus MAX runs as one index-backed SQL `func.max()`. This is
    **device-local-date** precise, NOT Sofia-precise: unlike `daily_metrics_engine._window`
    (which widens its lexical range then re-narrows by Sofia date *in Python*), a
    `func.max()` aggregate can't re-filter, so the bound is deliberately biased **inclusive**
    — never drop an in-week peak; a near-future row within ~1 day may be included, which is
    immaterial for a defensive whole-corpus ceiling that is ratcheted up-only (production
    carries no future HR). See D2/R3.
  - **Ratchet-up only**: the caller-facing anchor never drops below the current stored
    anchor (see D2 for where the clamp lives).
- **Wire it into `RecomputeConstants.process`** (`app/core/weekly_planner.py` ~L329-337):
  replace `new_max_hr=profile.thresholds.max_hr` with the ratcheted measured value
  (`session` already in scope at L299; `as_of` derived from `event.iso_week`). Leave the
  merge below (L339-368) untouched — it
  is already correct-when-reachable (Phase 19.4).
- **Tests**: unit tests for `measured_max_hr` (corpus-wide, physiological clamp, dual
  alias, conservative-inclusive `as_of` cutoff — inclusion AND far-future exclusion, ratchet,
  empty-corpus fallback) and an end-to-end recompute test
  (real shift re-derives zones; quiet/artifact window does not move the anchor).

## Out of Scope

- Rewriting the `rederive_zones` / `ZoneRederivation` / `compute_zones` kernel or the
  merge logic in `RecomputeConstants.process` L339-368 — Phase 19.4 already made it
  correct-when-reachable; this phase only supplies `new_max_hr`.
- A runtime **RHR** measured source (`new_rhr` stays `profile.thresholds.rhr_baseline`)
  and any RHR/HRV baseline rederivation — out of this phase's single criterion.
- Changing how records are ingested/stored, the whitelist, or the `profile.yaml` write
  path (owned by `PersistPlanNode`).
- Backfilling/altering the offline `scripts/derive_constants.py` derivation.

## Research Summary

See [RESEARCH.md](./RESEARCH.md) for verified code pointers (records model, dual HR
type-alias evidence, injection point, constants, test conventions).

## Decisions

- **D1 — Home module: `app/services/recompute.py`.** `measured_max_hr` lives beside
  `rederive_zones`, `ZoneRederivation`, and `ANCHOR_MIN_DELTA_BPM`, in the module that
  already imports `compute_zones` from `scripts/` and owns the runtime port of the
  offline derivation. Rejected: a new `app/services/hr_anchor.py` (needless surface for
  one function) and hosting in `weekly_planner.py` (mixes orchestration with a data query).
- **D2 — Ratchet-up clamp lives in `measured_max_hr`, taking `current_max_hr` as an
  argument.** `measured_max_hr(session, as_of, current_max_hr)` returns
  `max(current_max_hr, clamped_corpus_max)`, so the ratchet is a property of the source
  and is unit-testable in isolation; `rederive_zones`'s `>= ANCHOR_MIN_DELTA_BPM` gate
  then only fires on a genuine upward move. Rejected: clamping at the call site (would
  duplicate the invariant and leave the raw function foot-gunnable).
- **D3 — Empty/absent corpus ⇒ return `current_max_hr` (no-op), never raise.** The
  offline `derive_max_hr` raises `ValueError` on an empty corpus because it runs at
  build time; at runtime a weekly brief must never crash on a thin corpus, and the
  ratchet floor already gives the correct fallback (keep the stored anchor).
- **D4 — Physiological window + HR type strings are defined app-side, NOT imported from
  `scripts/derive_constants.py`.** That module's line 37 does a bare
  `from compute_zones import compute_zones`, so importing it from `app/` code is
  fragile (needs `scripts/` on `sys.path`; it has no `__init__.py`). Mirror the values
  (`_HR_FLOOR=80.0`, `_HR_CEILING=205.0`) app-side with a comment citing the offline
  source, and add a parity assertion. **The parity test lives in `tests/scripts/`** (e.g.
  extend `tests/scripts/test_derive_constants.py`), because the `derive_constants` fixture
  and the `sys.path.insert(0, scripts/)` that makes the offline module importable both live
  only in `tests/scripts/conftest.py` (pytest fixtures are directory-scoped, so they are
  invisible to `tests/services/`). It imports the app-side `_HR_FLOOR`/`_HR_CEILING` from
  `app.services.recompute` and asserts they equal the offline module's `HR_FLOOR`/`HR_CEILING`.
  See Risk R1.

## Risks

- **R1 — Physiological-window drift from the offline derivation.** If someone later
  edits `HR_FLOOR`/`HR_CEILING` in `scripts/derive_constants.py` but not the app-side
  copy, the runtime anchor could diverge from the offline seed. Mitigation: a parity
  unit test (D4) that loads the offline module and asserts the constants match; a code
  comment on the app-side constants pointing at the offline source.
- **R2 — Downward-anchor validation abort.** A measured anchor below a dependent
  threshold (e.g. `easy_hr_cap`) would fail `Profile.model_validate`. The ratchet-up-only
  policy (D2) prevents a downward move by construction; the merge's existing
  try/except fallback (Phase 19.4, weekly_planner L358-366) is defense-in-depth. Covered
  by the quiet-window end-to-end test.
- **R3 — `as_of` boundary off-by-a-day.** `records.start_date` is ISO-8601 TEXT with the
  device offset preserved verbatim, so its date-prefix is the *device-local* date, which can
  differ from the Sofia date by ±1 day. A single-SQL `func.max()` cutoff cannot re-narrow by
  Sofia date in Python the way `daily_metrics_engine._window` does (it pairs its ±1-day
  lexical range with a Python Sofia-date filter). Mitigation: bias the lexical upper bound
  **inclusive** (`start_date < (as_of + 1 day)` prefix) so an in-week peak is never dropped;
  accept that a near-future row within ~1 day may be included — immaterial for an up-only
  whole-corpus ceiling, and production carries no future HR. A unit test seeds a sample
  straddling the `as_of` boundary at a non-UTC offset and asserts this conservative-inclusive
  rule (NOT Sofia-date precision).
- **R4 — Dual-alias regression.** If only one type string is matched, either the entire
  seeded history (HK identifier) or all live data (`heart_rate`) is silently dropped from
  the MAX. Mitigation: derive the alias set from `RECORD_TYPE_TO_HK`; a unit test seeds
  BOTH origins and asserts the peak comes from whichever origin holds it.

## Acceptance Criteria

Maps to the epic's single criterion: *"A real measured max-HR shift (from records)
re-derives HR zones end-to-end in the weekly recompute; a quiet window or sensor
artifact does not move the anchor."*

- [ ] `measured_max_hr(session, as_of, current_max_hr)` returns the whole-corpus bounded
      MAX over both HR type aliases, clamped to `[_HR_FLOOR, _HR_CEILING]` and ratcheted to
      `>= current_max_hr`, with the `as_of` cutoff applied as a conservative-inclusive
      device-local-date bound (never drops an in-week peak; see R3); empty corpus ⇒
      `current_max_hr`.
- [ ] `RecomputeConstants.process` feeds the measured value as `new_max_hr` into
      `rederive_zones`; the merge (L339-368) is unchanged.
- [ ] End-to-end: a recompute-due weekly brief with a records corpus whose peak exceeds
      the stored anchor by `>= ANCHOR_MIN_DELTA_BPM` re-derives the HR zones (new
      `zones.z5.high == new max_hr`) and updates `thresholds.max_hr`.
- [ ] End-to-end: a quiet window (no new peak) OR an out-of-range artifact (e.g. 250 bpm)
      leaves `thresholds.max_hr` and `zones` unchanged.
- [ ] `uv run pytest` and `uv run ruff check` are green.

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [x] TASK-001: Add measured_max_hr(session, as_of, current_max_hr) query fn + unit tests
- [ ] TASK-002: Wire measured_max_hr into RecomputeConstants (ratchet-up feed) (depends on TASK-001)
- [ ] TASK-003: End-to-end recompute test: real shift re-derives zones, quiet window does not (depends on TASK-002)
- [ ] TASK-004: Final Validation
