# Adversarial Review — Round 1

**Run:** 2026-06-03 08:22 UTC
**Branch:** feature/e1-p2-auth-errors-health
**Base:** staging
**Commits reviewed:** 053973c..1cad11d

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

No-ship: the new global error layer can leak internal detail, strips required HTTP recovery headers, and makes 500s hard to investigate.

Findings:
- [high] HTTPException details still leak on internal_error responses (app/api/errors.py:107-109)
  The HTTP handler maps every unmapped status to internal_error, but still passes _http_detail(exc) into the response. A route raising HTTPException(status_code=500, detail=str(exc)) will return that text as error.detail; I verified the handler emits detail: "db password leaked" with code internal_error. That violates the no-internal-detail guarantee and can expose DB/upstream/secret material once real endpoints start wrapping failures as HTTPException.
  Recommendation: Do not propagate detail when code is internal_error; only expose details for explicitly public error codes/statuses, or introduce a typed public exception and force all generic/unmapped HTTPException details to null.
- [medium] HTTPException headers are dropped by the envelope handler (app/api/errors.py:106-109)
  _on_http builds a fresh JSONResponse and never forwards exc.headers. This currently breaks POST /health: Starlette raises 405 with an Allow header, but the response comes back with only content headers. The same design would drop Retry-After, WWW-Authenticate, and other recovery metadata, making clients and monitors unable to handle errors correctly.
  Recommendation: Let error_response accept headers and pass exc.headers through from the HTTPException handler; add regression tests for 405 Allow and auth 401 WWW-Authenticate/other recovery headers.
- [medium] Unhandled exceptions are consumed without server-side logging (app/api/errors.py:111-114)
  The catch-all handler turns every unhandled Exception into a generic 500 body but does not log the exception or any request context. I found no logging middleware in the app, so real /sync or brief failures would be reduced to access-log 500s with no stack/root-cause trail, making rollback and recovery materially harder.
  Recommendation: Log exceptions before returning the sanitized envelope, including method/path and a request/correlation id if available, or use middleware that preserves stack logging while still rewriting the client response.

Next steps:
- Block shipment until the error handler sanitizes internal_error details, preserves HTTPException headers, and records unhandled exceptions server-side.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | `internal_error` HTTPException still propagates caller `detail` → internal/secret leak | high | fix | Real security bug; the plan's whole point for `internal_error` is "no internals leaked" (Decisions). Force `detail=None` whenever the resolved code is `internal_error`; keep detail only for the explicitly-mapped public codes. | 8541ac3 |
| 2 | Envelope handler drops `exc.headers` (405 `Allow`, 401 `WWW-Authenticate`, `Retry-After`) | med | fix | HTTP-correctness regression from overriding Starlette's handler. Forward `exc.headers` through `error_response`; add a 405-`Allow` regression test. | d5e2213 |
| 3 | Unhandled `Exception` swallowed with no server-side log | med | fix | Operability gap: a catch-all that leaves zero trace makes 500s opaque. Add minimal **stdlib** logging (method/path + stack) before returning the sanitized envelope — not Langfuse tracing, which stays deferred to E12. | 1a10dce |
