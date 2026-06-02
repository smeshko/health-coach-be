# TASK-002: Bearer-token auth dependency

Depends on: TASK-001
Suggested commit: `feat(api): add bearer-token auth dependency`

## Goal

A reusable FastAPI dependency that authenticates requests against the single long-lived bearer token,
raising a `401` that the error handlers render as the `unauthorized` envelope.

## Files

- `app/api/auth.py` — new:
  - `require_auth(...)` — a FastAPI dependency that reads the `Authorization` header (via
    `fastapi.security.HTTPBearer(auto_error=False)` or direct header read), requires the `Bearer <token>`
    scheme, and compares the credentials **constant-time** (`secrets.compare_digest`) against
    `get_settings().api_token`. Missing header, wrong scheme, or wrong token → `HTTPException(401)`
    (rendered as the `unauthorized` envelope by TASK-001's handler). On success the dependency returns
    (e.g. the token / a sentinel) so it can guard any route via `Depends(require_auth)`.
- `tests/test_auth.py` — new (see Steps).

## Acceptance

- [ ] A route guarded by `Depends(require_auth)` returns `401` with the **`unauthorized`** envelope when:
      the `Authorization` header is **absent**, the scheme is not `Bearer`, or the token value is wrong.
- [ ] The same route returns `200` when `Authorization: Bearer <api_token>` matches
      `get_settings().api_token`.
- [ ] Token comparison is constant-time (`secrets.compare_digest`) — asserted by inspection/use in the
      impl; the wrong-token case still returns `401`.
- [ ] `require_auth` is importable and reusable: attaching it to a second route also gates that route
      (proves it is not hard-wired to one endpoint).

## Steps

### RED
- [ ] `tests/test_auth.py`: build `create_app()` with a known `api_token` (monkeypatch env), register a
      throwaway route `Depends(require_auth)` in the test app. Assert: no header → `401` + `unauthorized`
      envelope; `Authorization: Bearer wrong` → `401`; non-Bearer scheme → `401`; correct token → `200`.
      Assert the 401 body is the envelope from TASK-001 (`{ "error": { "code": "unauthorized", … } }`),
      not FastAPI's default.

### GREEN
- [ ] Implement `app/api/auth.py` (`require_auth`) using `get_settings().api_token` and
      `secrets.compare_digest`; raise `HTTPException(status_code=401)` for every failure path.

### REFACTOR
- [ ] Ensure the dependency reads settings via `get_settings()` (cached) so it is overridable in tests;
      tidy with `ruff`.

## Notes

The dependency must not build its own JSON error — it raises `HTTPException(401)` and lets TASK-001's
`HTTPException` handler map `401 → unauthorized`. Keep auth logic free of any envelope construction. It may
raise the `401` **with no `detail`**; TASK-001's handler supplies a non-null public `message` from its
status table (round-3 #1), so the `unauthorized` envelope still has a valid `message` and `detail: null`.
