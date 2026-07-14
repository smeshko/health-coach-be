# TASK-003: End-to-end recompute test: real shift re-derives zones, quiet window does not

Depends on: TASK-002
Suggested commit: `test(weekly): measured max-HR shift re-derives zones end-to-end`

## Goal

Prove the epic's single acceptance criterion at the node level: driving
`RecomputeConstants.process` on a recompute-due week, a records corpus whose peak clears
the stored anchor re-derives the HR zones, while a quiet window / out-of-range artifact
leaves anchor and zones untouched.

## Files

- `tests/core/test_weekly_planner.py` — add an end-to-end block driving
  `RecomputeConstants` through a `TaskContext(event=…, metadata={"session": session})`
  on a **recompute-due** week (profile `meta.constants_recomputed_week` set so
  `is_recompute_due` is True), seeding `Records` HR rows via the `session` fixture.

## Acceptance

- [ ] **Real shift**: seed HR records with a peak `>= stored max_hr +
      ANCHOR_MIN_DELTA_BPM` (within `[HR_FLOOR, HR_CEILING]`, dated within the recompute
      week). After `process`, the output `Profile` has `thresholds.max_hr == measured
      peak` and `zones.z5[1] == measured peak` (zones re-derived via `compute_zones`).
- [ ] **Quiet window**: seed only HR records at/below the stored anchor → output
      `thresholds.max_hr` and `zones` are unchanged (ratchet floor holds).
- [ ] **Sensor artifact**: seed one out-of-range spike (e.g. 250 bpm) above the anchor →
      it is clamped out, anchor and zones unchanged.
- [ ] **Dual origin**: at least one assertion uses seeded rows of BOTH `type`
      spellings (`heart_rate` and `HKQuantityTypeIdentifierHeartRate`) so the alias union
      is exercised end-to-end.

Evidence: `uv run pytest tests/core/test_weekly_planner.py -k "recompute and max_hr"`
output showing the shift, quiet, and artifact cases green.

## Steps

### RED
- [ ] Add the three scenarios (shift / quiet / artifact) driving `RecomputeConstants`
      on a due week with seeded HR `Records`. Assert on the output `Profile`'s
      `thresholds.max_hr` and `zones.z5`.

### GREEN
- [ ] With TASK-002 wired, the shift case should already pass; adjust seeding dates
      (relative to `event.iso_week` and the `as_of` cutoff) until the corpus peak is
      inside the window.

### REFACTOR
- [ ] Factor a small local seed helper (peak bpm, count, origin, date) if the three
      cases duplicate row-building; keep house style (`Records(...)` + `session.commit`).

## Notes

- The recompute is monthly-gated; the test MUST make the week due (set
  `meta.constants_recomputed_week` appropriately), else `process` short-circuits before
  `rederive_zones`.
- `as_of` is the recompute-week boundary (TASK-002) — date seeded records inside the week
  so they fall under the cutoff.
