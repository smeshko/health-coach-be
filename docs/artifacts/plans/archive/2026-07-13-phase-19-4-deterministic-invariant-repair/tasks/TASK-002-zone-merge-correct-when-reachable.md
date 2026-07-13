# TASK-002: Correct-when-reachable zone-rederivation merge

## Intent
When an anchor moves, the recompute produces a VALID profile — updating thresholds AND
zones atomically — instead of raising on `_zones_consistent_with_max_hr`. (Runtime anchor
SOURCE is Phase 19.6; here the mechanism is made correct + demonstrated via an injected anchor.)

## Steps
1. In `RecomputeConstants.process`, in the `if zones.changed` merge block, also set
   `dump["thresholds"]["max_hr"] = zones.new_max_hr` and
   `dump["thresholds"]["rhr_baseline"] = zones.new_rhr` alongside `dump["zones"]`. (RHR must
   be written even though `compute_zones` ignores it — else `changed` re-fires every recompute
   on the same unchanged RHR, round-1 #1.)
2. Leave the caller passing `new_* = current profile anchors` (documented production no-op;
   19.6 supplies the measured anchor). Add a code comment pointing to Phase 19.6.

## Tests (TDD — failing first)
- `test_recompute.py`: `rederive_zones` with a moved max-HR → `changed=True`,
  `zones == compute_zones(new_max_hr, new_rhr)`, echoes `new_max_hr`/`new_rhr`; RHR-only move
  → `changed=True` but zones == `compute_zones(current_max, new_rhr)` (bounds unchanged since
  %max-only), echoes `new_rhr`.
- `test_weekly_planner.py`: inject a `rederive_zones` result (monkeypatch) on a DUE week:
  - max-HR move → proposed `Profile` validates, `zones == compute_zones(new,…)`,
    `thresholds.max_hr == new_max_hr`, `thresholds.rhr_baseline == new_rhr`;
  - RHR-only move → `zones` bounds unchanged, `thresholds.rhr_baseline == new_rhr`;
  - default (`new == current`) → `zones`, `thresholds.max_hr`, `thresholds.rhr_baseline`
    byte-identical (assert those fields only — `cadence_current_spm` may change on a due run).

## Acceptance
Injected max-HR move → valid re-derived Profile (thresholds+zones); RHR-only move updates
rhr_baseline with unchanged zone bounds; default path no-op on the three anchor fields.
