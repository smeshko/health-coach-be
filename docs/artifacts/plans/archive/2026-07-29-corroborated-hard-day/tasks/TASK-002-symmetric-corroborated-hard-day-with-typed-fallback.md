# TASK-002: Symmetric corroborated hard_day() with typed fallback

Depends on: TASK-001
Suggested commit: `feat(metrics): corroborate hard_day with effort + in-window zones`

## Goal

`hard_day()` classifies by actual intensity — either signal confirms any workout as hard,
typed matches fall back to the label heuristic only when both signals are absent — fixing
the July 27 false positive without losing the no-data behavior.

## Files

- `app/services/daily_metrics_engine.py` — rewrite `hard_day` (line ~627), add the five
  constants next to `HARD_ACTIVITY_TYPES`/`LONG_DURATION_MIN` (`HARD_EFFORT_MIN`,
  `HARD_EFFORT_MIN_DURATION_MIN`, `HARD_Z45_MIN`, `HARD_EFFORT_VALID_RANGE`,
  `HARD_HR_COVERAGE_MIN_FRAC`), update the docstring;
  change signature to `hard_day(session, day, *, profile)` and update the sole caller
  `_compute_day_values` (line ~786).
- `tests/services/test_daily_metrics_engine.py` — new branch/boundary tests; adjust
  existing `hard_day` calls for the `profile` kwarg.

## Acceptance

- [ ] Per workout `w`: hard if (effort is **valid and** `>= HARD_EFFORT_MIN` AND
      `_duration_minutes(w) >= HARD_EFFORT_MIN_DURATION_MIN`) OR
      (in-window z4+z5 `>= HARD_Z45_MIN`) — regardless of `activity_type`.
- [ ] **Signal presence is validity-gated** (DECISIONS.md Decisions 6 & 7):
      - effort counts as *present* only when `HARD_EFFORT_VALID_RANGE[0] <= effort_score
        <= HARD_EFFORT_VALID_RANGE[1]` and finite; otherwise it is absent, exactly as `NULL`.
      - zones count as *present* only when TASK-001 returns non-`None` **and**
        `credited_minutes >= HARD_HR_COVERAGE_MIN_FRAC * _duration_minutes(w)` **and**
        `_duration_minutes(w) > 0`; otherwise absent.
      - promotion by z4+z5 `>= HARD_Z45_MIN` is **not** coverage-gated — it fires whenever
        TASK-001 returns that many minutes.
- [ ] Typed match (`HARD_ACTIVITY_TYPES`) with both signals absent → hard (fallback
      identical to today's behavior).
- [ ] Typed match with at least one signal present (per the gates above) and neither
      confirming → not hard via type (July 27 fixture: HIIT, effort 3, in-window z1/z2 with
      full coverage → `hard_day = 0`).
- [ ] **Per-workout isolation** (round-1 #4): the zones signal for `w` is computed strictly
      from `w`'s own window — z4/z5 minutes earned elsewhere in the day never contribute,
      and two workouts' in-window minutes are never summed.
- [ ] `_duration_minutes(w) >= LONG_DURATION_MIN` (90) still flags unconditionally.
- [ ] Constants pinned: `HARD_EFFORT_MIN = 7.0`, `HARD_EFFORT_MIN_DURATION_MIN = 20.0`,
      `HARD_Z45_MIN = 15.0`, `HARD_EFFORT_VALID_RANGE = (1.0, 10.0)`,
      `HARD_HR_COVERAGE_MIN_FRAC = 0.5`; all comparisons boundary-inclusive, with boundary
      tests.
- [ ] Missing duration → effort branch cannot confirm (normalizes to 0) and zones can never
      be *present* (coverage gate requires duration > 0); zones can still promote.
- [ ] Existing hard_day tests stay green (their fixtures carry no effort/HR → fallback),
      modulo the `profile` kwarg.

Evidence: `uv run pytest tests/services/test_daily_metrics_engine.py -q` output, including
a July 27-shaped fixture asserting `daily_metrics.hard_day == 0` after `recompute_day`.

## Steps

### RED
- [ ] July 27 regression fixture: typed HIIT, effort 3.0, ~50 min, in-window HR all
      z1/z2 covering ≥ 50 % of the window → asserts 0.
- [ ] Promotion tests: `running` + effort 9 + 25 min → 1; `running` + null effort +
      16 in-window z4 min → 1; `running` + effort 6 + heavy z3 only → 0.
- [ ] **Promotion is not coverage-gated** (round-2 #4): `running`, null effort, 50-min
      workout with only 16 credited in-window minutes — all z4 — so coverage (32 %) is
      *below* `HARD_HR_COVERAGE_MIN_FRAC` yet z4+z5 ≥ 15 → 1. Pin the duration explicitly
      in the fixture; an implementation that wrongly applies the coverage gate to promotion
      must fail this test.
- [ ] Boundary tests: effort 7.0 & duration 20.0 → 1; in-window z4+z5 exactly 15.0 → 1;
      effort 7.0 & duration 19.9 with zones absent → **0 for both the typed and the untyped
      variant**. Rationale (round-1 #6, pinned): the fallback requires BOTH signals absent;
      a present-but-unconfirming effort signal disables it, so the typed label does not
      rescue the workout.
- [ ] Demotion-guard tests — zones absent → fallback holds:
      - typed boxing, no effort, day has HR records but none in the workout window → 1.
      - **sparse coverage** (round-1 #2): typed boxing, no effort, HR covering only 3 min of
        a 50-min window, all z1 → 1. Same fixture at ≥ 50 % coverage, all z1 → 0.
      - coverage boundary: credited exactly 50 % of duration, all z1 → 0 (present, inclusive).
- [ ] Effort-validity tests (round-1 #3): `effort_score = 99`, untyped, 30 min, no HR → 0
      (invalid → absent → no promotion, no type to fall back to); `effort_score = -3`,
      typed boxing, no HR → 1 (invalid → absent → fallback holds); boundary `effort_score
      = 10.0` → valid, `= 1.0` → valid.
- [ ] Isolation tests (round-1 #4): a 30-min untyped workout with 0 in-window z4/z5 while
      the day carries 20 z4 min **outside** the window → 0; two untyped workouts with 8
      in-window z4 min each (16 day-total) → 0.
- [ ] Long-duration test: effort 2, 95 min, any type → 1 (rule unchanged).

### GREEN
- [ ] Per-workout evaluation loop using TASK-001's helper; short-circuit on the first
      hard workout; keep `_drop_superseded_seed` and the same-Sofia-day filter intact.

### REFACTOR
- [ ] Docstring: state the full rule, reference this plan's DECISIONS.md (revising
      archived e6-p1 Decision 3), keep the "always a real 0/1" contract line.

## Notes

Fallback semantics pinned: the type heuristic applies ONLY when both signals are absent
for that workout. A typed workout with a present-but-unconfirming signal (e.g. effort 3,
or in-window zones showing z1/z2 only **with adequate coverage**) is deliberately NOT hard
— that is the bug fix. The 90-min rule and seed-superseding logic are untouched.

"Absent" is validity-gated, not merely null-gated (DECISIONS.md Decisions 6 & 7): an
out-of-range effort score and a barely-covered HR window both count as *absent*, so the
typed fallback still protects those sessions. This is what keeps the demotion path from
firing on bad data rather than on evidence.
