# Review Summary — e1-p2-auth-errors-health

**Rounds:** 4 (3 review + 1 verification)
**Fix commits:** 8541ac3..86b35f4

## Rounds

| Round | Findings | Fixed | Deferred | Rejected |
|-------|----------|-------|----------|----------|
| 1     | 3        | 3     | 0        | 0        |
| 2     | 2        | 2     | 0        | 0        |
| 3     | 2        | 2     | 0        | 0        |
| 4 (verify) | 1   | 1     | 0        | 0        |

## Fixes

### Round 1 — global error layer hardening
- `8541ac3` — never leak caller `detail` on `internal_error` responses (round-1 #1)
- `d5e2213` — preserve `HTTPException` headers (405 `Allow`, etc.) through the envelope (round-1 #2)
- `1a10dce` — log unhandled exceptions server-side, stdlib logging (round-1 #3)

### Round 2 — safe-by-default + auth challenge
- `f2f3412` — never echo `HTTPException` detail on the wire; detail null by default (round-2 #1)
- `cd1a0bb` — send `WWW-Authenticate: Bearer` on every auth 401 (round-2 #2)

### Round 3 — consistency
- `daab4fb` — log 5xx `HTTPException`s too, not just the catch-all (round-3 #1)
- `baefd6b` — add `internal_error` to the generated `models.html` contract (round-3 #2)

### Round 4 (verification) — contract-list sweep
- `86b35f4` — add `internal_error` to the E1 source epic + `epics.html` stable-code list (round-4 #1)

## Deferred

- None.

## Rejected

- None. (E9/E10/LLM docs reference `brief_generation_failed`/`upstream_timeout` *contextually* as the LLM
  failure codes, not as the closed set, so they were deliberately left unchanged — not a rejection of a
  finding, a scoping note for the round-4 sweep.)

## Notes

- The error-`detail` policy was deliberately tightened beyond the plan's original wording to **safe by
  default**: the HTTP handler never echoes a route's `HTTPException.detail`; only the validation handler
  emits a (self-generated) detail. No acceptance criterion required a non-null mapped detail. A typed
  public-detail exception is the future opt-in if E10/E11 needs client-safe detail.
- Server-side logging here is **stdlib only**; Langfuse tracing stays deferred to E12 per the plan.
- Codex logged transient `pytest`/sandbox failures across rounds; `uv run pytest` is green (60 passed) in
  this environment and they were never raised as findings.
- Final state: `uv run pytest` → 60 passed; `uv run ruff check .` clean; every closed-set contract
  artifact (MODELS.md, models.html, E01-foundation.md, epics.html, the `ErrorCode` enum) lists
  `internal_error`.
