# Adversarial Validation — Round 2

**Run:** 2026-07-28
**Plan:** corroborated-hard-day
**Status at start:** draft
**Reviewer:** codex
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: round-1 edits leave historical derived state inconsistent, and the new HR trust gate can still both suppress real hard sessions and demote sessions from incomplete evidence.

Findings:
- [high] Apply — historical recompute leaves readiness and cached coaching stale (docs/artifacts/plans/corroborated-hard-day/DECISIONS.md:151-156)
  Decision 5 claims historical readiness remains internally consistent because it is recomputed in the same run. In fact, `recompute_day` explicitly preserves `readiness_score` and `band` (`app/services/daily_metrics_engine.py:803-813`), while `_expand_forward_window` can recompute existing rows through D+29 (`:678-700`). A duplicate sync can therefore reclassify multiple historical `hard_day` values without updating dependent next-day readiness or cached suggestions.
  Recommendation: Apply — either add effective-date/version gating or invalidate and regenerate dependent readiness/suggestions, with cascade tests; update PLAN.md, DECISIONS.md, and TASK-004 (likely adding an implementation task).
- [high] Apply — 50% credited minutes do not prove trustworthy negative HR evidence (docs/artifacts/plans/corroborated-hard-day/DECISIONS.md:183-195)
  The gate measures summed credited minutes, not representative temporal coverage. A watch recording only the first 25 easy minutes of a 50-minute session meets the inclusive 50% threshold even if it dies before the hard interval, disabling typed fallback and producing `hard_day = 0`. Existing credit semantics also add interval and instant credits independently (`daily_metrics_engine.py:472-481`), so overlapping records can inflate both coverage and z4/z5 totals beyond unique elapsed time.
  Recommendation: Apply — define coverage as unique valid HR-covered time and require near-complete or gap-bounded evidence for demotion, or make zones promote-only; add overlap and missing-hard-segment tests in PLAN.md, DECISIONS.md, TASK-001, TASK-002, TASK-003, and TASK-004.
- [high] Apply — strict source priority can discard the only complete HR recording (docs/artifacts/plans/corroborated-hard-day/tasks/TASK-001-per-workout-in-window-z4-z5-minutes-helper.md:29-36)
  TASK-001 selects the highest-priority source before considering adequacy. `_choose_source` sorts by `source_rank` before row weight (`daily_metrics_engine.py:295-306`), so one sparse Watch sample masks a complete Garmin recording. An untyped workout with 20 Garmin z4 minutes can consequently remain light, directly violating the promotion goal; the current two-source test does not exercise sparse-high-priority versus complete-lower-priority data.
  Recommendation: Apply — evaluate each source independently or select among adequately covered sources without summing across devices; add sparse-Watch/full-Garmin promotion and demotion tests to PLAN.md, DECISIONS.md, TASK-001, TASK-002, and TASK-004.
- [medium] Apply — final validation does not prove promotion bypasses the coverage gate (docs/artifacts/plans/corroborated-hard-day/tasks/TASK-004-final-validation.md:21-32)
  TASK-002 says z4/z5 promotion is coverage-independent, but its promotion fixtures do not pin workout duration or assert coverage below 50%; TASK-004 merely names generic z4/z5 promotion. An implementation that incorrectly applies the coverage gate to promotion can pass all named evidence while missing genuinely hard, partially recorded sessions.
  Recommendation: Apply — require a named test where 15–16 credited z4/z5 minutes in a 50-minute workout remain below 50% coverage yet still produce 1; update PLAN.md, TASK-002, and TASK-004.
- [medium] Apply — deferring ingestion lets one invalid effort value permanently block correction (docs/artifacts/plans/corroborated-hard-day/DECISIONS.md:223-239)
  Classifier-side filtering prevents 99 from promoting a workout, but it does not repair the stored signal. `_backfill_effort_scores` updates duplicate workouts only when the stored value is NULL (`app/services/workout_upsert.py:87-106`); after 99 is stored, a later corrected score of 9 for the same UUID is ignored forever. The classifier then treats effort as absent and can continue missing an untyped hard workout. This invalidates the rationale that the local guard fully removes the plan-owned misclassification risk.
  Recommendation: Apply — normalize invalid incoming effort to absence and allow a later valid value to replace stored invalid data, including existing-row and non-finite tests; update PLAN.md, RESEARCH.md, DECISIONS.md, TASK-002, TASK-004, and add app/services/workout_upsert.py to implementation scope.

Next steps:
- Redesign the HR coverage and source-selection rules before implementation.
- Resolve historical dependent-state invalidation versus an explicit cutover guard.
- Expand named final evidence for low-coverage promotion, mixed/overlapping HR records, source skew, and corrected effort values.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Decision 5's consistency rationale is false — `recompute_day` preserves readiness, so a flipped historical `hard_day` leaves the next day's verdict stale | high | apply | Verified: `PRESERVED_COLUMNS` (`readiness_score`/`band`) are never rewritten by `recompute_day` (engine:803-813). The rationale I wrote in round 1 was wrong. User confirmed the no-gate decision still stands, so the fix is an honest rationale: the preserved verdict is deliberately an audit trail of what the user was told, not a value to be retconned. | PLAN.md:Risks, DECISIONS.md:Decision 5 |
| 2 | 50 % *summed* credited minutes doesn't prove a session was easy (watch dies after the easy first half); interval+instant credits can overlap | high | reject | User decision: a watch dying mid-workout is not a real scenario in this setup, so the gate is not to be redesigned around it. The overlap sub-point is pre-existing `zone_minutes` credit behaviour that this plan reuses unchanged rather than introduces. | — |
| 3 | Rank-first source pick lets a sparse Apple Watch sample mask a complete Garmin recording | high | reject | Grounded in code (`source_rank`: Watch 0 < Garmin 1), but the user records on Apple only — the dual-device-with-better-secondary case is hypothetical here. Decision 3 deliberately reuses `zone_minutes`' source rule; diverging would buy nothing for this setup. | — |
| 4 | No named evidence that promotion bypasses the coverage gate | med | apply | Correct and cheap: with the gate in place, an implementation that wrongly applies it to promotion would pass every other named criterion while re-breaking the promotion half of the plan. | PLAN.md:Acceptance Criteria, TASK-002, TASK-004 |
| 5 | Classifier-side effort gate is one-way — `_backfill_effort_scores` only fills NULL, so a stored 99 blocks its own correction forever | med | apply | Verified at `workout_upsert.py:87-106`. This genuinely undercuts round-1 #3's rationale that the local guard fully contains the risk. User chose to apply; scoped to repairing our own stored data, not to adding `/sync` bounds (still deferred as round-1 #7). | PLAN.md:Scope, PLAN.md:Acceptance Criteria, DECISIONS.md:Decision 7, +TASK-005, TASK-004 |
