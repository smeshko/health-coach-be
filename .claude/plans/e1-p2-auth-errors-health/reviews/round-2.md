# Adversarial Review — Round 2

**Run:** 2026-06-03 08:31 UTC
**Branch:** feature/e1-p2-auth-errors-health
**Base:** staging
**Commits reviewed:** 053973c..1a10dce
**Prior rounds in scope:** reviews/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

No-ship: the round-1 fixes closed the exact internal_error leak/header/logging issues, but the global HTTP handler still trusts route-supplied detail for mapped auth/not-found errors, and the auth dependency emits 401s without a Bearer challenge.

Findings:
- [medium] Mapped HTTPException details can still leak arbitrary route text (app/api/errors.py:116-124)
  The round-1 leak fix only suppresses detail when the resolved code is internal_error. For mapped statuses, line 120 still returns _http_detail(exc), so any future route that raises HTTPException(401/404, detail=...) will put that raw string in error.detail. I verified this with direct TestClient probes: 401 detail 'token prefix secret' and 404 detail 'tenant/user secret' are returned verbatim. This keeps the global error layer unsafe by default for the exact auth/not-found paths future domain endpoints are likely to use.
  Recommendation: Default mapped HTTPException detail to null as well, or require an explicit typed/public exception for client-safe detail. Add regression tests for 401 and 404 with sensitive detail strings.
- [medium] Protected routes return 401 without WWW-Authenticate (app/api/auth.py:27-31)
  require_auth raises bare HTTPException(status_code=401) for missing, non-Bearer, and wrong-token requests. The error handler now preserves exc.headers, but there are no headers to preserve here, so /probe returns only Content-Type with no WWW-Authenticate challenge. I verified missing, Basic, and wrong Bearer requests all lack the header. This is a real auth interoperability regression: clients and intermediaries that rely on the 401 challenge cannot distinguish or recover correctly.
  Recommendation: Raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"}) on every auth failure, and assert the header on missing, malformed, and wrong-token requests.

Next steps:
- Block shipment until the HTTP detail policy is safe by default and auth failures emit the Bearer challenge header.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Mapped 401/404 HTTPException still echoes caller `detail` (unsafe by default) | med | fix | Valid follow-on to round-1 #1. Made the HTTP handler emit `detail=null` for *all* HTTPExceptions (only the validation handler sets a self-generated detail). Tightens — doesn't break — the plan's "no internals leaked" intent; no acceptance asserts a non-null mapped detail. A typed public-detail exception is the future opt-in if E10/E11 needs one. | f2f3412 |
| 2 | Auth 401s lack the `WWW-Authenticate: Bearer` challenge | med | fix | Real RFC 7235 interop gap. `require_auth` now raises `HTTPException(401, headers={"WWW-Authenticate": "Bearer"})`; the round-1 header-forwarding fix carries it onto the envelope. Asserted on missing/non-Bearer/wrong-token. | cd1a0bb |
