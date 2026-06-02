# TASK-004: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for e1-p2-auth-errors-health`

## Goal

Confirm the plan is fully implemented and production-ready, with a concrete, non-circular check for every
PLAN.md acceptance criterion.

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked.
- [ ] **Lint:** `uv run ruff check .` passes with no issues.
- [ ] **Tests:** `uv run pytest` passes (`test_errors.py`, `test_auth.py`, `test_health.py` all green).

### Per PLAN.md acceptance criterion (1:1)

- [ ] **`/health` unauthenticated + DST-aware `serverTime`** — `tests/test_health.py` asserts
      `GET /health` with no `Authorization` header → `200`, `status == "ok"`, and (DST proof through the
      **production conversion**, instant-preserving, not a monkeypatched helper) overriding only the **UTC
      clock source**: `2026-01-15T12:00:00Z` → `serverTime` parses to `2026-01-15T14:00:00+02:00` and
      `2026-07-15T12:00:00Z` → `2026-07-15T15:00:00+03:00` (assert the **full converted datetime**, not just
      the offset — catches a `.replace(tzinfo=...)` relabel; round-3 #2). Source guards:
      `grep -RIn 'astimezone(ZoneInfo("Europe/Sofia"))' app/api/routes/health.py` is present, and
      `grep -REn "timezone\(timedelta|\.replace\(tzinfo=|datetime\.timezone\(" app/api/routes/health.py`
      finds no fixed-offset/relabel construction for `serverTime`. Manual: `uv run uvicorn app.main:app`
      then `curl -s localhost:8000/health`.
- [ ] **Protected probe `401`/`200`** — `tests/test_health.py` (and/or `tests/test_auth.py`) asserts the
      probe route → `401` with no token, `401` with a wrong token, `200` with `Bearer <api_token>`.
      Manual: `curl -i localhost:8000/probe` (401) vs `curl -i -H "Authorization: Bearer $API_TOKEN"
      localhost:8000/probe` (200).
- [ ] **Single envelope for every non-2xx with a closed `code`** — `tests/test_errors.py` asserts the
      `{ "error": { code, message, detail } }` shape and `code` value for `401` (auth → `unauthorized`),
      `404` (unknown route → `not_found`), `400` (unmapped `HTTPException` → `internal_error`), `422`
      (`RequestValidationError` → `validation_error`), and `500` (unhandled → `internal_error`,
      `detail == null`, no internal text). `ErrorCode` is the five MODELS codes + `internal_error`;
      constructing `Error` with any other code raises `ValidationError` (unit test). **No-detail paths
      (round-3 #1):** a `401`/`404`/`400` `HTTPException` raised with no `detail` still yields an envelope
      whose `message` is a **non-empty string** and `detail == null`.
- [ ] **`internal_error` documented in MODELS (no contract drift)** —
      `grep -n "internal_error" docs/architecture/MODELS.md` finds it in the "Errors" code list, so every
      `ErrorCode` member is present in the source-of-truth doc (resolves round-2 #1).
- [ ] **`Error` camelCase + null-vs-absent `detail`** — `tests/test_errors.py` asserts `Error`/
      `ErrorResponse` raw `model_dump_json()` emits the `{ "error": { … } }` keys, and `detail`
      (`str | None = None`) is accepted both omitted and as explicit `null`.
- [ ] **Auth dependency reusable + constant-time** — `tests/test_auth.py` attaches `require_auth` to a
      second throwaway route and asserts it is also gated; the impl uses `secrets.compare_digest` against
      `get_settings().api_token` (grep the source / assert wrong-token → `401`).
- [ ] **`uv run ruff check .` and `uv run pytest` pass** — covered by the Lint/Tests steps above.

### Cross-cutting

- [ ] **No dropped deps reintroduced** — `grep -rIn -e psycopg -e celery -e redis -e pgvector -e supabase
      -e vecs app tests` returns nothing (ARCHITECTURE §1 stack note).
- [ ] **Importability** — `uv run python -c "import app.api.errors, app.api.auth, app.api.routes.health"`
      succeeds.
- [ ] `PLAN.md` acceptance criteria all met.
