# TASK-002: Wire measured_max_hr into RecomputeConstants (ratchet-up feed)

Depends on: TASK-001
Suggested commit: `feat(weekly): feed the runtime measured max-HR into zone rederivation`

## Goal

Replace the production no-op `new_max_hr=profile.thresholds.max_hr` in
`RecomputeConstants.process` with the ratcheted measured anchor from
`measured_max_hr(...)`, so a genuine corpus peak drives `rederive_zones` end-to-end.

## Files

- `app/core/weekly_planner.py` — in `RecomputeConstants.process` (~L329-337): import
  `measured_max_hr` from `app.services.recompute`; compute
  `new_max_hr = measured_max_hr(session, as_of=<end of event.iso_week>,
  current_max_hr=profile.thresholds.max_hr)` and pass it as `new_max_hr` to
  `rederive_zones`. Update/remove the "documented production no-op" comment (L325-327) to
  reflect that the source now exists (cite Phase 19.6). Leave the merge (L339-368)
  untouched.

## Acceptance

- [ ] `rederive_zones` receives the measured value as `new_max_hr`; `new_rhr` stays
      `profile.thresholds.rhr_baseline` (RHR source out of scope).
- [ ] The `as_of` cutoff is derived from `event.iso_week` (the recompute week boundary),
      so records through the recompute week are included and far-future rows excluded
      (near-boundary rows within ~1 day may be included by `measured_max_hr`'s
      conservative-inclusive cutoff — R3; immaterial for an up-only whole-corpus ceiling).
- [ ] `session` and `event` are used from the existing scope (no new session opened).
- [ ] Existing `RecomputeConstants` / weekly tests still pass (a corpus with no HR rows
      ratchets to the stored anchor ⇒ no behavioural change for those fixtures).

Evidence: `uv run pytest tests/core/test_weekly_planner.py tests/services/test_recompute.py`
green, plus the diff showing the single-line `new_max_hr=` swap.

## Steps

### RED
- [ ] Adjust any existing `RecomputeConstants` test that asserted the no-op (if one
      pins `new_max_hr == current`) so it reflects the measured feed; confirm the suite
      still expresses "no HR rows ⇒ anchor unchanged".

### GREEN
- [ ] Compute the `as_of` cutoff from `event.iso_week` (e.g.
      `_iso_week_monday(event.iso_week) + timedelta(days=7)` as the exclusive end-of-week
      boundary — reuse the existing `_iso_week_monday` helper) and pass
      `new_max_hr=measured_max_hr(session, as_of=<that>, current_max_hr=profile.thresholds.max_hr)`.

### REFACTOR
- [ ] Rewrite the stale L325-327 comment to state the runtime source now exists
      (Phase 19.6) and that the ratchet-up policy guarantees `new_max_hr >= current`.

## Notes

- Do not touch the merge/validation block (L339-368) — Phase 19.4 made it
  correct-when-reachable; this task only changes the anchor fed in.
- The end-to-end behavioural proof lives in TASK-003; this task is the wiring + keeping
  the existing suite green.
