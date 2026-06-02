# TASK-001: Error envelope models and exception handlers

Depends on: None
Suggested commit: `feat(api): add error envelope and exception handlers`

## Goal

Define the single `Error` envelope (`{ "error": { code, message, detail } }`) with stable machine codes
and register FastAPI exception handlers so every non-2xx response uses it.

## Files

- `app/api/errors.py` — new:
  - `ErrorCode` — a **closed** `str`/`Enum` of the five MODELS "Errors" codes (`validation_error`,
    `unauthorized`, `not_found`, `brief_generation_failed`, `upstream_timeout`) **plus one named fallback
    `internal_error`** for unmapped statuses / unhandled exceptions. No open/status-derived codes — every
    value handlers can emit is a member of this enum. (`internal_error` is a deliberate extension to MODELS,
    flagged in PLAN.md Decisions to fold back into the doc.)
  - `Error(CamelModel)` — fields `code: ErrorCode`, `message: str`, `detail: str | None = None`
    (inherits `app/api/schemas/base.py`).
  - `ErrorResponse(CamelModel)` — `error: Error` (the wire wrapper `{ "error": { … } }`).
  - A helper `error_response(code, message, status_code, detail=None) -> JSONResponse` that returns the
    wrapped envelope at the given HTTP status.
  - A single source-of-truth `STATUS_TO_CODE: dict[int, tuple[ErrorCode, str]]` table mapping each handled
    status to `(code, default_public_message)` — e.g. `401→(unauthorized, "Authentication required.")`,
    `404→(not_found, "Resource not found.")` — with a default of
    `(internal_error, "An internal error occurred.")` for any status not in the table. **`message` is
    always a non-empty string** (the default), so a no-detail `HTTPException` (like auth's bare `401`)
    never yields `message=None` (resolves round-3 #1).
  - `register_exception_handlers(app: FastAPI) -> None` registering:
    - `RequestValidationError` → `422`, code `validation_error`, a fixed public `message`, `detail`
      summarising the failures.
    - `StarletteHTTPException` / `HTTPException` → envelope with `(code, message) =
      STATUS_TO_CODE.get(status, default)`; `detail` is set from `exc.detail` **only when it is a non-empty
      string** (else `None`). `exc.detail` is never used as the sole `message` source — `message` is always
      the table's public default.
    - `Exception` (catch-all) → `500`, code `internal_error`, the fixed public `message`, `detail: None`
      (no internals leaked).
- `app/api/app.py` — call `register_exception_handlers(app)` inside `create_app()` (after settings load).
- `docs/architecture/MODELS.md` — "Errors" section: add `internal_error` to the `error.code` stable-code
  list (the table note and the bullet listing the five codes), so the documented wire contract matches the
  `ErrorCode` enum on commit (resolves round-2 #1 — not a deferred follow-up).
- `tests/test_errors.py` — new (see Steps).

## Acceptance

- [ ] `Error` serialises camelCase on the wire and `ErrorResponse` wraps it as `{ "error": { … } }`
      matching the MODELS "Errors" example keys (`code`, `message`, `detail`).
- [ ] `Error.detail` (`str | None = None`) accepts **both** omission and explicit `null` on input.
- [ ] A route that raises `HTTPException(404)` returns the envelope with `code == "not_found"`; a request
      to an unknown path also returns the `not_found` envelope (not FastAPI's default `{"detail": …}`).
- [ ] A route with a body/param that fails validation returns `422` with `code == "validation_error"`.
- [ ] A route that raises a bare `Exception` returns `500` with `code == "internal_error"`, a fixed
      message, and `detail == null` — no exception text leaked (tested with
      `TestClient(raise_server_exceptions=False)`).
- [ ] An `HTTPException` with an unmapped status (e.g. `400`) returns the envelope with
      `code == "internal_error"` (the table default), never a code outside `ErrorCode`.
- [ ] A **no-detail** `HTTPException` (raised with no `detail`, as auth does for `401`) still returns a
      valid envelope: `message` is a **non-empty string** (the table default) and `detail == null` —
      asserted for `401`, `404`, and `400` (resolves round-3 #1).
- [ ] `ErrorCode` is a closed set (the five MODELS codes + `internal_error`); constructing `Error` with a
      code outside it raises a `ValidationError`.
- [ ] `docs/architecture/MODELS.md` "Errors" lists `internal_error` among the stable `error.code` values,
      so every member of `ErrorCode` is documented (no undocumented wire code shipped).

## Steps

### RED
- [ ] `tests/test_errors.py`: build an app via `create_app()` with valid env (monkeypatch settings env),
      add throwaway routes inside the test that raise `HTTPException(404)`, `HTTPException(400)`, and a bare
      `Exception`, plus one with a typed body to trigger `RequestValidationError`. Assert each response is
      the `{ "error": { code, message, detail } }` envelope with the expected `code`: `404`→`not_found`,
      `400` (unmapped)→`internal_error`, bare `Exception`→`500`/`internal_error` with `detail == null` and
      no internal text, validation→`422`/`validation_error`; assert an unknown path → `not_found`. Raise the
      `404`/`400`/`401` `HTTPException`s **with no detail** and assert each envelope's `message` is a
      non-empty string and `detail == null` (round-3 #1). Add a unit test that `Error` round-trips
      camelCase, that `detail` accepts omission and explicit `null`, and that an invalid `code` raises
      `ValidationError`.

### GREEN
- [ ] Implement `app/api/errors.py` (`ErrorCode`, `Error`, `ErrorResponse`, `error_response`,
      `STATUS_TO_CODE`, `register_exception_handlers`) and wire `register_exception_handlers(app)` into
      `create_app()`.
- [ ] Update `docs/architecture/MODELS.md` "Errors" to add `internal_error` to the documented code list,
      so the doc and the `ErrorCode` enum match on commit.

### REFACTOR
- [ ] Keep the status→code map in one table; ensure handlers never echo raw exception text into the 500
      envelope; tidy with `ruff`.
