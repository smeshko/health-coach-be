# TASK-001: Per-workout in-window z4+z5 minutes helper

Depends on: None
Suggested commit: `feat(metrics): per-workout in-window z4+z5 minutes helper`

## Goal

A pure helper that returns a workout's in-window z4+z5 minutes **and** the credited
coverage that backs them — or `None` when no HR sample overlaps the workout — as the
corroboration signal for TASK-002.

## Files

- `app/services/daily_metrics_engine.py` — new `_workout_z45_minutes(session, w, *,
  profile) -> tuple[float, float] | None` (name/shape adjustable to module idiom) near
  `zone_minutes`, returning `(z45_minutes, credited_minutes)`.
- `tests/services/test_daily_metrics_engine.py` — new tests for the helper.

## Acceptance

- [ ] Returns `None` when no `heart_rate` record overlaps `[w.start_date, w.end_date]`
      (the "zones absent" convention, mirroring `zone_minutes`' all-`None` rule).
- [ ] Returns `(z45_minutes, credited_minutes)` where `credited_minutes` is the total
      in-window credited time across **all** zones (not just z4/z5) — TASK-002's coverage
      gate (`HARD_HR_COVERAGE_MIN_FRAC`, DECISIONS.md Decision 6) needs it to tell a
      genuinely easy session from a session the watch barely recorded.
- [ ] Interval samples credit only their overlap with the workout window
      (via `_in_day_overlap_seconds`-style clamping to the window, not the day).
- [ ] Instant samples credit capped-gap seconds (`_instant_hr_credit_seconds` semantics)
      clamped to the workout window. **Successor context comes from outside the window**
      (round-1 #5): mirror `zone_minutes:465-477` — pick the source from the in-window
      rows, then compute gaps over that source's rows across the full ±1-day window, so the
      last in-window instant credits its real gap (clipped at the window end) instead of
      the 0 that `_instant_hr_credit_seconds` gives a window's final sample.
- [ ] Restricts to the single highest-priority HR source among in-window samples
      (`_choose_source`), so dual-device days don't double-count.
- [ ] Buckets via `_bucket_zone(bpm, profile.zone_bounds())`; returns the z4+z5 sum in
      minutes; z1–z3 minutes feed `credited_minutes` but are not returned individually.
- [ ] Workout with `end_date is None` → `None` (window undefined).

Evidence: `uv run pytest tests/services/test_daily_metrics_engine.py -q` output showing the
new tests passing.

## Steps

### RED
- [ ] Tests: no-overlap → `None`; interval sample half-overlapping window credits only the
      overlap; instant-sample chain credits capped gaps; two sources in-window → only the
      chosen source counts; z4/z5 bpm fixtures vs `profile.zone_bounds()` sum correctly;
      `end_date=None` → `None`.
- [ ] Successor-context test (round-1 #5): the last instant sample inside the window has its
      next same-source sample **after** `w.end_date` — assert it credits the gap clipped to
      the window end, not 0. Size the fixture so the naive filter-first implementation lands
      just under 15.0 z4+z5 minutes and the correct one lands at/above it.
- [ ] Coverage test: 3 credited minutes inside a 50-minute window → returns
      `(z45, credited≈3.0)`, so TASK-002 can distinguish it from a fully-covered easy
      session.

### GREEN
- [ ] Implement by reusing/extracting the existing credit helpers rather than
      reimplementing; keep `zone_minutes` behavior byte-identical.

### REFACTOR
- [ ] If extraction created a shared window-crediting core, ensure `zone_minutes` calls it
      and its full suite stays green.

## Notes

Do not change `zone_minutes` output or the stored `z*_min` columns — this helper is
classifier-internal and never persisted.
