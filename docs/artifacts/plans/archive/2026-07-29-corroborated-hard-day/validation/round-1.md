# Adversarial Validation — Round 1

**Run:** 2026-07-28
**Plan:** corroborated-hard-day
**Status at start:** draft
**Reviewer:** codex (plan Risk: medium)

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: the plan cannot enforce its historical cutover, still misclassifies sparse HR and invalid effort data, and does not validate key per-workout window semantics.

Findings:
- [high] Apply: the promised July 27 freeze is not enforceable (docs/artifacts/plans/corroborated-hard-day/PLAN.md:30-33)
  PLAN says historical rows stay unchanged, but `/sync` unconditionally derives affected dates from every submitted workout/record and recomputes them, including duplicates (`app/api/routes/sync.py:75-83`, `app/services/recompute.py:56-70`). Any later payload touching July 27 will run the new classifier and rewrite `hard_day`; preserved readiness fields may then disagree with it.
  Recommendation: Apply — either add an effective-date/version guard with historical-resync tests or explicitly allow source-triggered historical changes; update PLAN.md, DECISIONS.md, TASK-002, and TASK-004.
- [high] Apply: partial HR coverage still demotes genuinely hard typed sessions (docs/artifacts/plans/corroborated-hard-day/PLAN.md:61-62)
  The claimed mitigation only handles zero samples. Under TASK-001, any overlapping sample makes zones present; under TASK-002, present-but-unconfirming zones disable typed fallback. Current zone semantics likewise turns one usable low-zone sample into present zero-valued z4/z5 (`daily_metrics_engine.py:453-482`). A watch recording only warm-up before dying therefore produces the exact false demotion this risk claims to prevent.
  Recommendation: Apply — define minimum usable HR coverage before zones become present and add sparse/partial/high-priority-source coverage tests; update PLAN.md, DECISIONS.md, TASK-001, and TASK-002.
- [high] Apply: the classifier trusts an unvalidated effort score (docs/artifacts/plans/corroborated-hard-day/tasks/TASK-002-symmetric-corroborated-hard-day-with-typed-fallback.md:21-35)
  The plan treats every non-null effort as a valid 1–10 signal, but `Workout.effort_score` has no bounds and the database column is an unconstrained nullable float (`app/api/schemas/sync.py:93-107`, `app/database/models/workouts.py:28`). Current validation accepts values such as 99 and -3. A malformed high value promotes an easy workout, while a malformed low value disables typed fallback and demotes a hard one.
  Recommendation: Apply — require finite 1–10 effort values at ingestion and/or treat invalid stored values as absent, with both promotion and fallback tests; update PLAN.md, DECISIONS.md, RESEARCH.md, and TASK-002.
- [medium] Apply: final validation does not prove per-workout isolation (docs/artifacts/plans/corroborated-hard-day/PLAN.md:68-77)
  Per-workout isolation is the reason for the new helper, but PLAN acceptance and TASK-002 tests omit negative cases where ≥15 z4/z5 minutes occur outside the workout or where two individually sub-threshold workouts total ≥15. TASK-004 only checks PLAN criteria generically, so a day-total or cross-workout aggregation bug could satisfy every named final criterion.
  Recommendation: Apply — add observable acceptance tests for outside-window HR and two sub-threshold workouts, and map them into final evidence; update PLAN.md, TASK-002, and TASK-004.
- [medium] Apply: instant-credit requirements omit successor context outside the workout (docs/artifacts/plans/corroborated-hard-day/tasks/TASK-001-per-workout-in-window-z4-z5-minutes-helper.md:19-40)
  Current instant semantics intentionally selects a source from in-day rows but retains the wider source window so the last in-boundary point can use a later successor (`daily_metrics_engine.py:420-438,465-477`). TASK-001 frames inputs/tests as overlapping samples only. Filtering before crediting makes the last in-workout point worth zero and can move a session below the exact 15-minute threshold.
  Recommendation: Apply — require successor-only context from the first same-source instant after workout end and add an exact-threshold test with that successor outside the window; update TASK-001 and TASK-002.
- [medium] Apply: TASK-002 specifies both 1 and 0 for the same boundary case (docs/artifacts/plans/corroborated-hard-day/tasks/TASK-002-symmetric-corroborated-hard-day-with-typed-fallback.md:47-51)
  The 7-RPE/19.9-minute typed case first says it “flags 1,” then correctly states that present-but-unconfirming effort disables fallback and concludes 0. This makes the RED test and expected implementation mutually exclusive despite the later notes favoring 0.
  Recommendation: Apply — state unequivocally that both typed and untyped variants return 0; update TASK-002.

Next steps:
- Resolve the cutover and HR-coverage decisions before implementation.
- Add invalid-input and isolation acceptance cases, then make TASK-004 enumerate their evidence.
- Correct the contradictory boundary expectation.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | July 27 freeze not enforceable — any re-sync touching the day recomputes it under the new rule | high | apply | Verified: `affected_dates` buckets every submitted workout to its Sofia day regardless of duplicate status, so Out-of-Scope's "July 27 stays as-is" is a wish, not a guarantee. User chose to document rather than gate. | PLAN.md:Out of Scope, PLAN.md:Risks, DECISIONS.md:Decision 5 |
| 2 | Partial HR coverage (dead battery mid-session) still wrongly demotes a typed hard session | high | apply | Verified against `zone_minutes:453-482`: one in-window sample makes zones "present" with z4+z5 = 0, which disables the typed fallback — precisely the false demotion PLAN.md:61-62 claims to have mitigated. | PLAN.md:Scope, PLAN.md:Risks, PLAN.md:Acceptance Criteria, DECISIONS.md:Decision 6, TASK-001, TASK-002, TASK-003, TASK-004 |
| 3 | Classifier trusts an unvalidated effort score (99 / -3 accepted) | high | apply | Verified: `sync.py:106` is a bare `int \| None` with no bounds and the column is an unconstrained `Float`. Applied classifier-side only (out-of-range → treat as absent); ingestion-side validation deferred as a separate concern. | PLAN.md:Scope, PLAN.md:Risks, PLAN.md:Acceptance Criteria, DECISIONS.md:Decision 7, RESEARCH.md, TASK-002, TASK-003, TASK-004 |
| 4 | Acceptance/final-validation never prove per-workout isolation | med | apply | Correct and cheap: the helper exists *because* of isolation, yet no criterion fails if the implementation aggregates day-totals or sums across workouts. | PLAN.md:Acceptance Criteria, TASK-002, TASK-004 |
| 5 | Instant-credit spec drops successor context outside the workout window | med | apply | Verified against `zone_minutes:465-477` + `_instant_hr_credit_seconds:420-438`: the existing pattern deliberately keeps the wider source window so the last in-boundary instant finds a successor. TASK-001 as written would filter first and zero it out. | TASK-001, TASK-004 |
| 6 | TASK-002 states both 1 and 0 for the 7-RPE / 19.9-min typed boundary case | med | apply | The task text literally contradicts itself mid-sentence (planner thinking out loud); RED test and implementation would be mutually exclusive. | TASK-002 |
| 7 | Ingestion-side bounds validation on `effort_score` (reject 99 / -3 at `/sync`) | med | defer | Real, but it is an API-contract change touching the iOS payload and existing stored rows — a separate concern from the classifier. The classifier-side guard (#3) already removes the misclassification risk this plan owns. | — |
