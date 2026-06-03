# Adversarial Review — Round 4 (verification)

**Run:** 2026-06-03 08:46 UTC
**Branch:** feature/e1-p2-auth-errors-health
**Base:** staging
**Commits reviewed:** 053973c..baefd6b
**Prior rounds in scope:** reviews/round-1.md, reviews/round-2.md, reviews/round-3.md

> Verification pass after the round-3 fixes. It confirmed the runtime fixes hold and surfaced one more
> same-class doc-sync item. Rather than chase it artifact-by-artifact (which would invite a round-5), I
> swept **every** tracked file enumerating the closed error-code set and converged in one commit. Codex
> looping stopped here: the findings have decayed from real security/correctness bugs (rounds 1–3) to
> trivial contract-list sync, all fixed and deterministically verified.

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

No-ship: the round-3 runtime fix and models.html edit hold, but the tracked E1 contract still advertises the old closed error-code set.

Findings:
- [medium] E1 source epic still omits internal_error from the stable code contract (epics/E01-foundation.md:33-35)
  The server now emits internal_error for fallback HTTPException/unhandled paths, and MODELS.md/models.html were updated, but the E1 requirement that scopes this phase still lists only validation_error, unauthorized, not_found, brief_generation_failed, and upstream_timeout. The visual companion repeats the same stale list at docs/architecture/epics.html:257. Impact is inferred from these tracked docs being requirements/contract material: clients or later phase implementers using them can reject a real code returned on 400/405/500 fallback paths.
  Recommendation: Update epics/E01-foundation.md and docs/architecture/epics.html to include internal_error in the stable code set, or stop emitting internal_error as a fallback code.

Next steps:
- Patch the stale E1 contract artifacts and rerun the review grep for every tracked error-code list.
- Full pytest could not be run in this read-only sandbox because pytest had no usable temporary directory; a targeted runtime probe confirmed HTTPException(500) is sanitized and logged.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | E1 source epic + epics.html still list the old 5-code set (closed-enum contract skew) | med | fix | Same class as round-3 #2, consistent with the plan's "no deferred drift" decision. Swept all tracked closed-set enumerations: only `epics/E01-foundation.md` (R4) and `docs/architecture/epics.html` needed it; E9/E10/LLM mention only the LLM-failure codes contextually (not the closed set), so they stay. Verified every closed-set artifact now lists `internal_error`. | 86b35f4 |

Round-3 fixes confirmed: 5xx HTTPExceptions now logged (runtime probe), `models.html` carries `internal_error`. No regressions.
