# Adversarial Validation — Round 3

**Run:** 2026-06-02 21:51 UTC
**Plan:** e1-p2-auth-errors-health
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md, validation/round-2.md
**Note:** This is the **final** round (3-round cap). Both findings applied; cap reached.

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: the round-2 contract-drift fix is now self-consistent, but the plan still leaves a broken 401/no-detail error path and the DST validation can pass a non-converting timezone implementation.

Findings:
- [high] No-detail HTTPExceptions can produce an invalid envelope (.claude/plans/e1-p2-auth-errors-health/tasks/TASK-001-error-envelope-models-and-exception-handlers.md:26-30)
  Verdict: apply. TASK-001 makes `Error.message` a required `str`, then specifies the HTTPException handler should carry `exc.detail` as both message and detail; TASK-002 later requires auth failures to raise `HTTPException(status_code=401)` with no detail. A literal implementation can construct `message=None` or emit a non-human `None`, breaking the protected-route 401 envelope and any no-detail 404/400 path.
  Recommendation: Require a non-null public message fallback per status/code when `exc.detail` is absent, keep `detail` null unless a string is intentionally public, and add final validation for no-detail 401/404/400 envelopes with `message` as a string.
- [medium] DST proof does not prove UTC-to-Sofia conversion (.claude/plans/e1-p2-auth-errors-health/tasks/TASK-004-final-validation.md:19-24)
  Verdict: apply. TASK-004 checks Jan/Jul offsets plus `ZoneInfo` presence, but an implementation that does `clock().replace(tzinfo=ZoneInfo("Europe/Sofia"))` would pass those checks while relabeling the UTC instant instead of converting it, shifting `serverTime` by two or three hours. That violates the TASK-003 production-conversion requirement and can poison drift checks.
  Recommendation: Assert instant-preserving conversion, e.g. a fixed `2026-01-15T12:00:00Z` becomes `14:00+02:00` and a fixed `2026-07-15T12:00:00Z` becomes `15:00+03:00`, or add a source guard for `.astimezone(ZoneInfo("Europe/Sofia"))`.

Next steps:
- Patch TASK-001/TASK-002/TASK-004 to make HTTPException message handling explicit and tested.
- Strengthen TASK-003/TASK-004 DST validation to assert local converted time, not just offset.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | No-detail `HTTPException` (e.g. auth's bare `401`) could yield `message=None` since `Error.message` is required and the handler was told to use `exc.detail` for the message | high | apply | New, valid defect exposed by the round-2 spec. Fix: each status/code in `STATUS_TO_CODE` carries a **non-null default public message**; the handler uses `exc.detail` only as `detail` (when a string), never as the sole message source; `message` is always a non-empty `str`. Add final-validation for no-detail `401`/`404`/`400` envelopes asserting `message` is a non-empty string. | TASK-001 (Files/Acceptance/Steps), TASK-002 (Notes), TASK-004 |
| 2 | DST proof checks offset + `ZoneInfo` presence but a `.replace(tzinfo=ZoneInfo(...))` relabel (not convert) would still pass, shifting the wall-clock by 2–3h | medium | apply | New, valid: offset alone doesn't prove instant-preserving conversion. Fix: assert exact converted wall-clock — `2026-01-15T12:00:00Z` → `14:00+02:00`, `2026-07-15T12:00:00Z` → `15:00+03:00` — and add a source guard requiring `.astimezone(ZoneInfo("Europe/Sofia"))` (and rejecting `.replace(tzinfo=`). | TASK-003 (Files/Acceptance/Steps/Notes), TASK-004 |

**Cap reached:** round 3 had applies; per the runbook both were applied and validation stops here (3-round cap). No further round is run.
