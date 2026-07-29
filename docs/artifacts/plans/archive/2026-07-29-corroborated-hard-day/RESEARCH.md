# Research: Corroborated hard-day classification

Curated findings only — no raw conversation transcripts.

## Incident (2026-07-28 daily brief)

- July 27, 18:40–19:30 (~50 min) workout synced fine (`workoutsUpserted: 1` before the
  brief request), stored as `activity_type = high_intensity_interval_training`,
  `effort_score = 3.0`, 355 kcal. `daily_metrics` for the day: 56 min z1, 3.9 min z2,
  zero z3–z5.
- `hard_day()` flagged it hard purely on the HIIT label → readiness applied the −15
  `yesterday_hard_day` penalty → the LLM (which receives only the precomputed readiness
  block in `inputs_snapshot`, never raw workouts) faithfully narrated "hard day yesterday".
- Not a sync failure, not an LLM error: a deterministic-classifier design gap.

## Key Files & Facts

- `app/services/daily_metrics_engine.py:627` `hard_day(session, day)` — returns 1 if any
  same-Sofia-day workout's `_canonical_activity_type` ∈ `HARD_ACTIVITY_TYPES`
  (`boxing`, `high_intensity_interval_training`, `kickboxing`, `martial_arts`, line 433)
  or `_duration_minutes(w) >= 90`. No intensity fields consulted.
- Sole caller: `_compute_day_values` (line 786), which also computes
  `zone_minutes(session, day, profile=profile)` — so `profile` is available to pass down.
- `_duration_minutes` (line 614): normalizes via `duration_unit`; `None`/unknown unit → 0.0
  — so a duration-less workout can never confirm via the effort branch (pinned behavior).
- `zone_minutes` (line 442): restricts to the single highest-priority HR source
  (`_choose_source`), credits interval samples by `_in_day_overlap_seconds` and instant
  samples by `_instant_hr_credit_seconds` (capped gap), buckets via
  `_bucket_zone(bpm, profile.zone_bounds())`. No in-day HR sample → every `z*_min` is
  `None` ("no-data convention") — the model for this plan's "zones absent" definition.

## Available disproving signals

- `workouts.effort_score` — Apple RPE 1–10 (`WorkoutEffortScore`), nullable; upsert
  backfills only where NULL (`workout_upsert.py`), never clobbers. Apple semantics:
  1–3 easy, 4–6 moderate, 7–8 hard, 9–10 max. **The 1–10 range is a convention, not a
  constraint** (round-1 #3): `app/api/schemas/sync.py` declares `effort_score: int | None`
  with no bounds and the column is an unconstrained `Float`, so 99 and -3 are storable
  today — hence the classifier-side validity gate (DECISIONS.md Decision 7).
- `workouts.physical_effort` (METs proxy, nullable) — deliberately unused by this plan.
- `records` heart-rate samples, bucketable against `profile.zone_bounds()` within a
  workout's `start_date`–`end_date` window.

## Downstream consumers of `hard_day`

- `readiness.py:70` — `HARD_DAY_POINTS = -15`; the −25 boxing + sleep < 6 h variant only
  applies when `yesterday_hard_day` is true, so demotion suppresses both.
- Weekly hard-day budget and 7/28-day rollups count `hard_day == 1` rows.
- The daily brief narrates readiness; it never sees raw workouts.

## Constraints

- Archived Decision 3 (`docs/artifacts/plans/archive/2026-06-04-e6-p1-per-day-recompute/
  DECISIONS.md`) chose the pure type/duration predicate and rejected effort/zone scoring
  because the fields are nullable. The revision keeps determinism: nullable signals only
  refine the outcome when present; both-signals-absent reproduces the original predicate.
- DB.md §2 (line 154) already describes `hard_day` as "boxing/threshold/VO₂/long/HIIT" —
  threshold/VO₂ runs arrive typed `running` and were never catchable by the label set;
  symmetric promotion implements the documented intent.
- `hard_day` must stay a real 0/1, never `None` (flag, not measurement).

## Useful Commands

```bash
uv run pytest tests/services/test_daily_metrics_engine.py -q   # engine test suite
```

## Uncertainty

- Effort ≥ 7 with missing duration → resolved: effort branch cannot confirm (duration
  normalizes to 0); workout may still confirm via zones or fall back if typed.
- Whether prod HR coverage always spans workouts → resolved by design: in-window presence
  gate makes missing coverage fall back instead of demoting.

## Existing tests to preserve/extend

`tests/services/test_daily_metrics_engine.py`: `test_hard_day_per_hard_activity_type`,
`test_hard_day_long_duration_threshold_inclusive`, `test_hard_day_seconds_unit_normalized`,
`test_hard_day_easy_only_and_empty_day_are_zero`,
`test_hard_day_matches_seeded_hk_workout_activity_types`,
`test_hard_day_seed_workout_superseded_on_sync_covered_day`. Typed-workout fixtures carry
no effort/HR → they exercise the fallback branch and should stay green unchanged
(signature update aside).
