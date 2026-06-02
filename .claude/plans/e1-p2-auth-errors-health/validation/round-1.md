# Adversarial Validation — Round 1

**Run:** 2026-06-02 21:40 UTC
**Plan:** e1-p2-auth-errors-health
**Status at start:** draft

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: the plan has an error-code contract contradiction and a final-validation check that cannot catch the timezone bug it claims to prevent.

Findings:
- [high] [reject] Closed error-code set conflicts with generic fallback codes (.claude/plans/e1-p2-auth-errors-health/tasks/TASK-001-error-envelope-models-and-exception-handlers.md:21-26)
  Verdict: reject. MODELS/E01 define exactly five stable error codes, and this task also defines ErrorCode as that closed enum, but the same handler spec requires status-derived/generic codes for unmapped HTTPException and 500. That is impossible to implement without either failing model validation or widening the wire contract outside the cited docs.
  Recommendation: Change PLAN.md, TASK-001, and TASK-004 to name exact allowed fallback codes, or first update MODELS/E01 to add explicit codes such as bad_request/internal_error and then validate against that amended contract.
- [medium] [apply] DST-aware serverTime validation would pass a hard-coded offset (.claude/plans/e1-p2-auth-errors-health/tasks/TASK-004-final-validation.md:19-22)
  Verdict: apply. The plan promises Europe/Sofia/DST-aware serverTime, but final validation only checks that fromisoformat(...).utcoffset() is not None. A hard-coded +03:00 timestamp or fixed timezone(timedelta(hours=3)) passes this check while violating the architecture rule to never assume a fixed offset.
  Recommendation: Change TASK-003 and TASK-004 to require an injectable clock/helper using ZoneInfo('Europe/Sofia') and test both winter and summer dates, or add an explicit source inspection check that rejects fixed-offset timezone construction.

Next steps:
- Resolve the error-code contract before implementation; this is a schema/API decision, not a coding detail.
- Strengthen the final-validation task so each claimed acceptance criterion fails for the specific bad implementation it is meant to prevent.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Closed `ErrorCode` enum conflicts with "status-derived/generic" fallback codes for unmapped `HTTPException`/`500` — impossible to implement against a closed five-code set | high | apply | Real contradiction (Codex's own rationale). Codex labelled it "reject" but its label is advisory; the defect is genuine. Faithful fix: drop the "status-derived generic" language and name **one** explicit fallback `internal_error` for 500/unmapped, documented as a deliberate named extension to the MODELS five-code set (flagged to fold into MODELS), keeping the wire contract a named closed set rather than an open status-derived one. | PLAN.md:Scope, PLAN.md:Decisions, PLAN.md:Acceptance Criteria, TASK-001, TASK-004 |
| 2 | Final-validation `utcoffset() is not None` check passes a hard-coded `+03:00` / `timezone(timedelta(hours=3))` — does not catch the fixed-offset bug it claims to prevent | medium | apply | Valid: a fixed-offset datetime satisfies the check while violating MODELS "never assume a fixed offset". Fix: require a `now_sofia()` helper using `ZoneInfo("Europe/Sofia")`, test **both** a winter (`+02:00`) and a summer (`+03:00`) instant via an injectable clock, and add a source-inspection check rejecting fixed-offset `timezone(...)` construction. | TASK-003, TASK-004, PLAN.md:Acceptance Criteria |
