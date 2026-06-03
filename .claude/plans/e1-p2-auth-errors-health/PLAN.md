# Plan: E1·P2 — Auth, error envelope & health

Status: in-progress
Branch: feature/e1-p2-auth-errors-health
Risk: small
Created: 2026-06-03

> Epic **E1 — Foundation & API Skeleton**, phase **P2**. Source of truth:
> [`epics/E01-foundation.md`](../../../epics/E01-foundation.md) (§3 E1·P2, §4 acceptance) · grounded in
> [`docs/architecture/ARCHITECTURE.md`](../../../docs/architecture/ARCHITECTURE.md) §1 and
> [`docs/architecture/MODELS.md`](../../../docs/architecture/MODELS.md) "Conventions" / "Errors".
> Builds on **E1·P1** (`app/api/app.py` `create_app()`, `app/core/settings.py` `get_settings()`,
> `app/api/schemas/base.py` `CamelModel`).

## Goal

Make the FastAPI process authenticated and observable: one error envelope for every non-2xx, a reusable
bearer-token auth dependency, and an unauthenticated `GET /health` liveness endpoint.

## Scope

- **Error envelope** (`app/api/errors.py`): a `CamelModel`-based `Error { code, message, detail }` payload
  wrapped as `{ "error": { … } }` (MODELS "Errors"), with stable machine codes `validation_error`,
  `unauthorized`, `not_found`, `brief_generation_failed`, `upstream_timeout` **plus one explicit fallback
  `internal_error`** for unmapped statuses / unhandled exceptions (see Decisions — a named extension to the
  MODELS set, not an open "status-derived" code). **The MODELS "Errors" code list is updated in this same
  PR** to add `internal_error`, so the wire contract and the doc agree on commit (no deferred drift).
  Exception handlers registered on the app:
  `RequestValidationError` → `422` `validation_error`; `HTTPException` → the envelope via an explicit
  status→code table (`401`→`unauthorized`, `404`→`not_found`; every other status → `internal_error`); any
  unhandled `Exception` → `500` `internal_error` with a generic message (no internal detail leaked).
- **Auth dependency** (`app/api/auth.py`): a reusable FastAPI dependency that reads the `Authorization`
  header, expects `Bearer <token>`, and compares constant-time against `get_settings().api_token`. Missing
  or wrong → `HTTPException(401)` that the handler renders as the `unauthorized` envelope. Single user, no
  tenancy (MODELS "Conventions → Auth").
- **`GET /health`** (`app/api/routes/health.py`): **unauthenticated**, returns process liveness
  (`status: "ok"`) plus `serverTime` as an ISO-8601 timestamp carrying the actual local UTC offset
  (Europe/Sofia, DST-aware; never a hard-coded offset). Plus a **protected probe route** guarded by the
  auth dependency to demonstrate `401`-without / `200`-with the token (epic §4 acceptance).
- **Wiring**: register the handlers, the health router, and the probe router inside `create_app()`
  (`app/api/app.py`), keeping the factory's fail-fast settings load from E1·P1 intact.

## Out of Scope

- The real domain endpoints `/sync`, `/brief/daily`, `/brief/weekly` (E5/E10/E11) — only a throwaway
  protected *probe* route ships here, to prove the auth gate.
- Codes `brief_generation_failed` / `upstream_timeout` are **defined** in the `Error` model's code set now,
  but the brief paths that raise them arrive in E9/E10/E11. (The `internal_error` fallback is wired **and**
  documented in MODELS in this PR — see Scope — so it is *not* deferred.)
- Workflow engine primitives (E1·P3); DB models/migrations (E2); LLM (E9); Docker/Langfuse (E12).

## Research Summary

The error envelope is fixed by MODELS "Errors": a single wrapper `{ "error": { "code", "message",
"detail" } }` over all non-2xx, with `code` from a closed set (`validation_error`, `not_found`,
`brief_generation_failed`, `upstream_timeout`, `unauthorized`); `detail` is `string | null` (nullable,
optional). MODELS enumerates no code for an unmapped status or an unhandled `500`, so this phase adds **one
named fallback `internal_error`** (a deliberate extension, **added to MODELS "Errors" in this PR**) rather
than emitting an open status-derived code — keeping `code` a named closed enum that matches the doc on
commit (see Decisions). Auth is one long-lived bearer token in the `Authorization` header, never the body, single user
no tenancy (MODELS "Conventions → Auth"; epic §2 R3). Timestamps must be ISO-8601 carrying the **actual**
device offset and never a fixed one — Europe/Sofia is `+02:00` winter / `+03:00` summer (MODELS
"Conventions → Timestamps"); `serverTime` already appears that way in `SyncResponse`. The process is a
single synchronous FastAPI app (ARCHITECTURE §1). E1·P1 already ships `create_app()`, the `api_token`
setting, and the `CamelModel` base this phase reuses.

## Decisions

- **Envelope wrapper `{ "error": { … } }`, not a bare `Error`** — MODELS "Errors" shows the wrapper
  explicitly (and `SyncResponse`/briefs are the only un-wrapped 2xx shapes). The phase note's shorthand
  `Error { code, message, detail }` describes the inner object; the wire shape is the wrapper.
- **`Error` model inherits `CamelModel`** — keeps the wire camelCase and `detail` null-vs-absent behaviour
  consistent with every other model (epic §2 R5; E1·P1 `app/api/schemas/base.py`). `code`/`message`/
  `detail` are already single words so casing is a no-op, but inheriting keeps the convention uniform and
  future-proof.
- **`code` is a closed `Enum` set: the five MODELS codes + one named fallback `internal_error`** — the
  five MODELS codes are stable machine contracts for the iOS client; modelling them as an enum makes an
  unknown code a construction-time error, not a typo on the wire. A single explicit `internal_error` is
  added for every status with no documented code (unmapped `HTTPException`, unhandled `500`) **instead of**
  an open "status-derived/generic" code — this keeps the wire contract a named closed set. This is a
  deliberate, minimal extension to the MODELS five-code set; **MODELS "Errors" is updated in this same PR**
  to add `internal_error` so the docs and code agree on commit (no deferred drift — resolves round-2 #1).
  (Resolves round-1 #1: a closed enum cannot also yield status-derived values.)
- **Map `HTTPException` → envelope via an explicit status→code table (`401→unauthorized`,
  `404→not_found`, all others → `internal_error`)** — so any handler that raises `HTTPException` (incl.
  the auth dependency's `401`) renders a stable in-set code without each call site repeating envelope
  construction, and no status can produce a code outside the closed enum.
- **Constant-time token comparison (`secrets.compare_digest`)** — avoids a timing side-channel on the one
  long-lived token; cheap and standard.
- **`GET /health` is intentionally unauthenticated** — it is a pure liveness ping (`status: "ok"` +
  `serverTime`) that leaks nothing, and keeping it credential-free lets the E12 Docker `HEALTHCHECK`,
  `litestream`, and uptime monitors probe it without baking the API token into the probe (epic §3 E1·P2,
  §4 acceptance). Every *other* route — including the probe shipped here — is gated by the auth dependency.
  If richer status is ever needed (DB reachable, migration head), it belongs on a **separate
  authenticated** `/readyz`-style probe, not on `/health`. (Resolves review comment §ov-scope — confirmed
  with the maintainer: keep `/health` unauthenticated.)
- **`serverTime` via `datetime.now(ZoneInfo("Europe/Sofia"))` → `.isoformat()`** — emits the real
  DST-aware offset; never hard-codes `+03:00` (MODELS "Conventions → Timestamps"; runbook pitfall 6).
- **Generic `500` envelope hides internal detail** — unhandled exceptions return a fixed message and
  `detail: null`, so stack traces / internals never leak to the client.

## Risks

- **Leaking internals in the 500 detail** — mitigation: the unhandled-exception handler emits a fixed
  message with `detail: null`; a test raises from a route and asserts no internal text appears.
- **Timing side-channel on the token** — mitigation: `secrets.compare_digest`; a test asserts wrong-token
  → `401`.
- **Hard-coding the timezone offset** — mitigation: derive from `ZoneInfo("Europe/Sofia")`; a test asserts
  `serverTime` parses as an aware ISO-8601 datetime with a non-`None` offset (not a literal-string check).
- **FastAPI's default validation/HTTP error shapes leaking through** — mitigation: register handlers for
  `RequestValidationError`, `HTTPException`, **and** `Exception`; a test asserts a 422/401/404/500 each
  conform to the envelope (no default `{"detail": …}` shape).
- **`TestClient` raising server exceptions instead of returning 500** — mitigation: construct the client
  with `raise_server_exceptions=False` in the unhandled-exception test so the registered 500 handler is
  exercised.
- **`internal_error` fallback drifting from MODELS "Errors"** — mitigation: it is a single, explicitly
  named code (not open/status-derived), modelled in the same `ErrorCode` enum and asserted on the wire;
  **MODELS "Errors" is updated in this same PR** to list it, and final validation greps MODELS for the
  code, so the contract and code stay in sync on commit.

## Acceptance Criteria

- [ ] `GET /health` returns `200` **without** any `Authorization` header, with body `{ "status": "ok",
      "serverTime": <iso8601> }` where `serverTime` is produced via `ZoneInfo("Europe/Sofia")` and, with an
      injectable clock, emits `+02:00` for a winter instant and `+03:00` for a summer instant (DST-aware,
      never a fixed offset) — the parsed datetime is timezone-aware.
- [ ] The protected probe route returns `401` with the **`unauthorized`** envelope when the token is
      missing **and** when it is wrong, and `200` when the correct `Bearer <api_token>` is sent.
- [ ] Every non-2xx response is the single envelope `{ "error": { "code", "message", "detail" } }` with a
      `code` from the closed set (five MODELS codes + the named `internal_error` fallback) — verified for
      `401` (auth → `unauthorized`), `404` (unknown route → `not_found`), `422` (`RequestValidationError`
      → `validation_error`), and `500` (unhandled → `internal_error`, `detail: null`, no internal text
      leaked).
- [ ] The `Error` payload is camelCase on the wire (inherits `CamelModel`) and its optional `detail`
      accepts both omission and explicit `null`.
- [ ] `docs/architecture/MODELS.md` "Errors" lists `internal_error` in the code set, so the documented
      contract matches the `ErrorCode` enum (verified by grep in final validation).
- [ ] The auth dependency is reusable (importable, attachable to any route via `Depends`) and compares the
      token constant-time against `get_settings().api_token`.
- [ ] `uv run ruff check .` and `uv run pytest` pass.

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [x] TASK-001: Error envelope models and exception handlers
- [x] TASK-002: Bearer-token auth dependency
- [x] TASK-003: GET /health endpoint (unauthenticated)
- [ ] TASK-004: Final Validation
