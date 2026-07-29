# Plan: Corroborated hard-day classification

Status: in-progress
Branch: bug/corroborated-hard-day
Risk: medium
Epic: none
Phase: none
Linear: none
Created: 2026-07-28

## Goal

`hard_day` reflects actual session intensity — a light workout typed as HIIT no longer
triggers the −15 readiness penalty and a "hard day yesterday" brief, and a genuinely hard
untyped session (threshold/VO₂ run) no longer slips through as light.

## Scope

- `hard_day()` in `app/services/daily_metrics_engine.py`: symmetric intensity corroboration
  — a workout of **any** type flags hard when `effort_score >= 7` AND duration ≥ 20 min, or
  when its **in-window** z4+z5 minutes ≥ 15; a typed match (`HARD_ACTIVITY_TYPES`) with
  **both** signals absent falls back to today's type heuristic (hard).
- **Signal validity gates** (round-1 #2, #3) — a signal only counts as *present* (and so
  only then blocks the typed fallback) when it is trustworthy:
  - effort: `1.0 <= effort_score <= 10.0`; anything outside that range, or non-finite,
    is treated exactly as `NULL` (absent).
  - zones: credited in-window HR minutes ≥ `HARD_HR_COVERAGE_MIN_FRAC` × the workout's
    duration, and duration > 0. Below that (dead battery, manual log) zones are *absent*,
    not "present and zero". Promotion by z4+z5 ≥ 15 is coverage-independent — 15 credited
    hard minutes cannot accrue without real data.
- New per-workout in-window zone helper (HR samples overlapping the workout's start–end
  window, single highest-priority source, existing interval/instant credit rules) returning
  **both** the z4+z5 minutes and the credited coverage minutes the gate needs.
- `hard_day(session, day, *, profile)` signature change; sole caller `_compute_day_values`
  already holds `profile`.
- Pinned constants: `HARD_EFFORT_MIN = 7.0`, `HARD_EFFORT_MIN_DURATION_MIN = 20.0`,
  `HARD_Z45_MIN = 15.0`, `HARD_EFFORT_VALID_RANGE = (1.0, 10.0)`,
  `HARD_HR_COVERAGE_MIN_FRAC = 0.5`.
- `_backfill_effort_scores` in `app/services/workout_upsert.py`: a valid incoming score may
  replace a stored **invalid** one, so the validity gate can't strand a workout as
  permanently effort-absent (round-2 #5, TASK-005).
- Tests for every branch and boundary; docs update (DB.md §2 wording, Decision 3 revision).

## Out of Scope

- Proactive backfill/recompute of historical `daily_metrics` rows — no migration or sweep
  re-runs the classifier over past days. **Not a freeze** (round-1 #1): `affected_dates`
  (`app/services/recompute.py`, called from `app/api/routes/sync.py`) buckets every
  submitted workout to its Sofia
  day regardless of duplicate status, so any later payload touching an old day *will*
  recompute it under the new rule and may flip its stored `hard_day`. That is accepted —
  the new rule is the more correct one (DECISIONS.md Decision 5). No effective-date guard.
- Day-level hardness without a workout row (untracked activity with high z4/z5 stays 0).
- The duration ≥ 90 min "long session" rule — unchanged and not corroboration-gated.
- Readiness scoring (`readiness.py`), weekly hard-day budget, brief prompt assembly — they
  consume the corrected flag unchanged.
- iOS recording-side changes (picking a different workout type on the watch).

## Research Summary

See [RESEARCH.md](RESEARCH.md). Headline: the incident's root cause is that
`hard_day()` treats `activity_type` labels as ground truth; the DB already carries the
disproving signals (`workouts.effort_score`, HR records bucketable via
`profile.zone_bounds()`), and `zone_minutes`' all-`None` no-data convention gives a clean
"signal absent" definition.

## Decisions

See [DECISIONS.md](DECISIONS.md) — four decisions weighed during the grill (corroboration
signal choice, symmetric promotion, in-window vs day-total zones, workout-anchored only)
plus three from validation (historical rows documented not gated, coverage gate on the
zones signal, effort validity handled classifier-side).
This plan deliberately revises archived Decision 3 of `2026-06-04-e6-p1-per-day-recompute`
(pure deterministic type predicate), keeping its determinism via the both-signals-absent
fallback.

## Risks

- **Behavior change beyond the bug**: promotion flags previously-light hard runs, affecting
  readiness and the weekly hard-day budget — intended, but changes coaching output.
  Mitigation: thresholds pinned as constants; tests document each flip.
- **Wrong demotion when HR coverage is partial** (watch dies mid-session): a bare presence
  gate does NOT cover this — one warm-up sample would make zones "present and zero" and
  silently disable the typed fallback (round-1 #2). Mitigated by the coverage gate: zones
  count as present only when credited in-window minutes ≥ `HARD_HR_COVERAGE_MIN_FRAC` of
  the workout duration; sparse coverage → zones absent → effort or type fallback.
- **Historical rows silently reclassified by a re-sync**: accepted, not mitigated — see
  Out of Scope and DECISIONS.md Decision 5. The blast radius is ~30 days, not one: a sync
  touching day D full-recomputes every existing row through D+29 (`_expand_forward_window`,
  round-3 #2), so `hard_day` can flip on days whose workouts were never re-sent. The
  **stored readiness verdict does NOT follow** (round-2 #1: `readiness_score`/`band` are
  `PRESERVED_COLUMNS`, never rewritten by `recompute_day`) — deliberately kept as the
  record of what the user was told that morning.
- **Out-of-range `effort_score` skewing the classifier** (`sync.py` accepts 99 / -3 today):
  mitigated classifier-side — values outside `HARD_EFFORT_VALID_RANGE` are treated as
  absent. Ingestion-side bounds are deferred (round-1 #7).
- **Dual-device double-count inside a window**: mitigated by reusing the single-source
  selection rule from `zone_minutes`.
- **Drift between helper and `zone_minutes` credit semantics**: mitigated by extracting and
  reusing the existing interval/instant credit helpers rather than reimplementing.

## Acceptance Criteria

- [ ] July 27-shaped fixture (HIIT-typed, effort 3, in-window HR all z1/z2) → `hard_day = 0`.
- [ ] Hard untyped fixture (running, effort 9, duration ≥ 20 min) → `hard_day = 1`; same via
      in-window z4+z5 ≥ 15 with null effort.
- [ ] Typed workout with no effort and no in-window HR → `hard_day = 1` (fallback preserved).
- [ ] **Sparse-coverage fallback** (round-1 #2): typed boxing, no effort, HR covering only
      the first 3 min of a 50-min window, all z1 → `hard_day = 1` (coverage below
      `HARD_HR_COVERAGE_MIN_FRAC` → zones absent → fallback). Same fixture with HR covering
      ≥ 50 % of the window, all z1 → `hard_day = 0`.
- [ ] **Promotion is coverage-independent** (round-2 #4): 16 credited in-window z4 minutes
      in a 50-min workout (32 % coverage, below the gate) → `hard_day = 1`.
- [ ] **Effort validity** (round-1 #3): `effort_score = 99` on an easy 30-min untyped
      workout → `hard_day = 0` (invalid → absent, no promotion); `effort_score = -3` on a
      typed boxing workout with no HR → `hard_day = 1` (invalid → absent → fallback holds).
- [ ] **Invalid effort is correctable** (round-2 #5, round-3 #1): a workout stored with
      `effort_score = 99` accepts a later synced `9` for the same uuid, including when both
      arrive in the *same* payload; a valid stored score is still never overwritten.
- [ ] **Per-workout isolation** (round-1 #4): 20 in-window z4 min earned *outside* the
      workout window → that workout does not flag; two workouts of 8 in-window z4 min each
      (16 day-total) → `hard_day = 0` (no cross-workout aggregation).
- [ ] Duration ≥ 90 min still flags regardless of signals; boundary tests inclusive (≥) for
      7 / 20 / 15 / 90.
- [ ] All existing engine tests pass; `pytest` green.
- [ ] DB.md §2 `hard_day` description matches the implemented rule.

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [x] TASK-001: Per-workout in-window z4+z5 minutes helper
- [x] TASK-002: Symmetric corroborated hard_day() with typed fallback (depends on TASK-001)
- [ ] TASK-005: Let a valid effort_score replace an invalid stored one (depends on TASK-002)
- [ ] TASK-003: Docs: DB.md hard_day wording + Decision 3 revision record (depends on TASK-002)
- [ ] TASK-004: Final Validation
