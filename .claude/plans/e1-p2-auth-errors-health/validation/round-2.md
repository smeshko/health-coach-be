# Adversarial Validation — Round 2

**Run:** 2026-06-02 21:45 UTC
**Plan:** e1-p2-auth-errors-health
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: the plan is internally cleaner, but it still ships an undocumented error enum member and the DST validation can bypass the production clock code.

Findings:
- [high] [apply] internal_error remains contract drift from MODELS/E01 (.claude/plans/e1-p2-auth-errors-health/PLAN.md:44-46)
  Verdict: apply. Rationale: PLAN now self-consistently uses a closed enum plus internal_error, but current MODELS and E01 still enumerate only the five stable codes; this line explicitly defers folding internal_error into MODELS. That means the plan would ship a wire code absent from the cited source-of-truth contract, which is high-risk for client enum handling/schema generation. Plan files to change: PLAN.md, TASK-001, TASK-004.
  Recommendation: Make the docs update part of this plan and final validation, or remove the internal_error extension from the implementation contract; do not leave it as an out-of-plan follow-up.
- [medium] [apply] DST test can bypass now_sofia production logic (.claude/plans/e1-p2-auth-errors-health/tasks/TASK-004-final-validation.md:19-24)
  Verdict: apply. Rationale: TASK-004 validates offsets after 'the clock injected' returns winter/summer values, while TASK-003 makes now_sofia itself the injectable/monkeypatched helper. A test that replaces now_sofia proves response serialization, not that production now_sofia uses ZoneInfo('Europe/Sofia'); a fixed-offset implementation can still pass if the helper is patched away and the narrow grep is avoided. Plan files to change: TASK-003, TASK-004.
  Recommendation: Specify a test of the production conversion path: inject only a base UTC instant/clock dependency into now_sofia, assert Jan and Jul outputs use +02:00/+03:00, and add a source check for ZoneInfo('Europe/Sofia') plus a robust rejection of datetime.timezone/timedelta fixed offsets.

Next steps:
- Update the plan so internal_error is either documented in MODELS as part of this change or not emitted.
- Tighten TASK-003/TASK-004 so the DST proof exercises production now_sofia instead of monkeypatching it away.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | `internal_error` is still contract drift — deferring the MODELS update means shipping a wire code absent from the source-of-truth doc | high | apply | Valid: a wire code must exist in MODELS "Errors" on commit, not as a deferred follow-up (client enum/schema risk). Fix: fold the docs update **into this plan** — add `internal_error` to MODELS.md "Errors" code list as a step in TASK-001 and a final-validation check, and drop the "deferred docs follow-up" framing. | PLAN.md:Scope, PLAN.md:Out of Scope, PLAN.md:Decisions, PLAN.md:Acceptance Criteria, TASK-001, TASK-004 |
| 2 | DST test can monkeypatch `now_sofia` away → proves serialization, not that production uses `ZoneInfo` | medium | apply | Valid: replacing `now_sofia` bypasses the `ZoneInfo` conversion. Fix: inject only a **base UTC instant** (a clock returning a `datetime`) **into** `now_sofia`, so production's `.astimezone(ZoneInfo("Europe/Sofia"))` runs; assert Jan→`+02:00`, Jul→`+03:00`; add a source check requiring `ZoneInfo("Europe/Sofia")` present and `datetime.timezone(`/fixed-`timedelta` offset construction absent. | TASK-003, TASK-004 |
