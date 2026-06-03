# Adversarial Review — Round 3

**Run:** 2026-06-03 08:38 UTC
**Branch:** feature/e1-p2-auth-errors-health
**Base:** staging
**Commits reviewed:** 053973c..cd1a0bb
**Prior rounds in scope:** reviews/round-1.md, reviews/round-2.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

No-ship: the direct prior fixes hold, but 5xx HTTPExceptions still become sanitized, unlogged internal errors, and one tracked contract artifact still advertises the old closed error-code set.

Findings:
- [medium] HTTPException 5xx responses are sanitized but never logged (app/api/errors.py:95-105)
  The round-1 logging fix only covers the catch-all Exception handler. Any route that raises HTTPException(status_code=500) takes the StarletteHTTPException path here, which returns the internal_error envelope with detail=null and exits without logging. I verified a direct probe returns 500 internal_error with zero app.api.errors log records, while a RuntimeError on the catch-all path logs once. A future endpoint that wraps DB/upstream failure as HTTPException(500) would leave only an access-log 500 and no root-cause trail.
  Recommendation: Log HTTPException responses with status_code >= 500 before returning the envelope, including method/path/status and exception info; add a regression test for HTTPException(500, detail="secret") that asserts the response is sanitized and an error log is emitted.
- [medium] Generated model contract still omits internal_error (docs/architecture/models.html:867)
  This branch adds internal_error to the code enum and to MODELS.md, but the tracked visual companion still lists only validation_error, not_found, brief_generation_failed, upstream_timeout, and unauthorized. Because this is the human-facing schema companion for the request/response models, clients or reviewers using it will miss a real code the server now emits for 400/405/500 fallback paths. That is contract skew on a closed enum.
  Recommendation: Regenerate or update docs/architecture/models.html so the Error field list includes internal_error, and add final validation that checks every tracked contract artifact for the complete error-code set.

Next steps:
- Patch 5xx HTTPException logging and add the regression test.
- Regenerate the model HTML contract artifact before merging.

## Triage

Both findings are new, narrow, and converging (consistency follow-ons to the round-1/round-2 fixes, not
signs of a brittle area). Per the maintainer's "work autonomously" directive they were fixed rather than
escalated; a verification round (round-4) follows.

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | 5xx HTTPExceptions sanitized but not logged (round-1 logging only covered the catch-all) | med | fix | Real operability gap consistent with round-1 #3. Log any HTTPException with status ≥ 500 (method/path/status + exc_info) before returning the envelope; client stays sanitized. Regression test added. | daab4fb |
| 2 | Generated `models.html` still lists only the old five codes (contract skew introduced by this PR's MODELS.md edit) | med | fix | This PR created the skew, so it fixes it: added `internal_error` to the `error.code` list in `models.html`. Surgical edit (MODELS.md remains source of truth); a full template regen of `models.html` is a separate docs-tooling sweep, kept out of this auth/errors PR. | baefd6b |
