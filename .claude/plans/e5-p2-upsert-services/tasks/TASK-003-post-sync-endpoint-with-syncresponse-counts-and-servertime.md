# TASK-003: POST /sync endpoint with SyncResponse counts and serverTime

Depends on: TASK-001, TASK-002
Suggested commit: `feat(api): add authenticated POST /sync returning SyncResponse counts + serverTime`

## Goal

Add an authenticated `POST /sync` route that runs the three upsert services in one transaction and
returns a `SyncResponse` whose split counts make idempotency observable, with a DST-aware `serverTime`
and `checkinSaved`/`strengthTestSaved` stubbed `false` (E5·P3).

## Files

- `app/api/routes/sync.py` (new) — `router = APIRouter()`; `@router.post("/sync", response_model=
  SyncResponse, dependencies=[Depends(require_auth)])` (the E1·P2 bearer dep — no/wrong token → `401`
  `unauthorized` envelope) taking `body: SyncRequest`:
  - open a session via `SessionLocal()` (E2·P1) in a `try/except/finally` (or a small context manager)
    — **one transaction** per request.
  - `rec = upsert_records(session, body.records)` (TASK-001);
    `wo = upsert_workouts(session, body.workouts)` (TASK-002);
    `days = upsert_activity(session, body.activity_summary)` (TASK-002).
  - `session.commit()` (rollback on exception, then re-raise so the E1·P2 `Exception` handler renders the
    envelope).
  - return `SyncResponse(records_upserted=rec.upserted, records_duplicate=rec.duplicate,
    workouts_upserted=wo.upserted, activity_days_upserted=days, checkin_saved=False,
    strength_test_saved=False, server_time=now_sofia())`. **`now_sofia` is moved to `app/core/time.py`**
    (next to the existing Europe/Sofia period-key/timestamp helpers — E2·P1) and both `/sync` **and**
    `/health` import it from there, so no route module imports a helper from another route module
    (round-1 #3). It stays the same instant-preserving, DST-aware conversion (`astimezone(ZoneInfo(
    "Europe/Sofia"))`, injectable `clock`). **No** readiness, **no** `daily_metrics` recompute (MODELS
    "SyncResponse"; epic §3).
- `app/core/time.py` — **move** `now_sofia(clock=...)` here (it currently lives in E1·P2's
  `app/api/routes/health.py`); it's a domain/time concern alongside the existing `period_date`/`iso_week`
  helpers, so both routes can import it without a route→route dependency (round-1 #3). Keep its behaviour
  identical (instant-preserving `astimezone(ZoneInfo("Europe/Sofia"))`, injectable `clock`).
- `app/api/routes/health.py` — update `/health` to import `now_sofia` from `app.core.time` (no behaviour
  change); its existing DST tests must still pass.
- `app/api/app.py` — `from app.api.routes import sync` and `app.include_router(sync.router)` inside
  `create_app()` (mirrors E1·P2's `include_router(health.router)`).
- `tests/api/routes/__init__.py` (new, if absent) — package marker.
- `tests/api/routes/test_sync.py` (new) — endpoint tests over `create_app()` + `TestClient` against a
  migrated temp-file `app.db` (override the engine/`app_db_path` to the temp DB so the route's
  `SessionLocal` hits it), with a known `api_token`.

## Acceptance

- [ ] `POST /sync` with `Authorization: Bearer <api_token>` and a body containing records/workouts/
      activitySummary returns `200` and a `SyncResponse` JSON with **camelCase** keys
      `recordsUpserted`/`recordsDuplicate`/`workoutsUpserted`/`activityDaysUpserted` matching what the
      services persisted, `checkinSaved=false`, `strengthTestSaved=false`.
- [ ] `serverTime` is present and parses (`datetime.fromisoformat`) to a **timezone-aware** datetime
      (`tzinfo is not None`); a Jan UTC clock yields `+02:00` and a Jul clock `+03:00` (DST proof via an
      injected clock, not a monkeypatched `now_sofia`).
- [ ] **End-to-end idempotency:** posting the **same** body twice — the second response has
      `recordsUpserted=0`/`recordsDuplicate=N`, `workoutsUpserted=0`, and the `records`/`workouts`/
      `workout_statistics` row counts are unchanged after the second call.
- [ ] **Auth:** `POST /sync` with **no** token and with a **wrong** token returns `401` and the
      `{"error":{"code":"unauthorized",…}}` envelope; the correct token → `200` (epic §4; E1·P2).
- [ ] **Whitelist end-to-end:** a body containing a non-whitelisted record `type` returns `200` but that
      record is **absent** from `records` (epic R3).
- [ ] **No recompute/readiness:** after a `POST /sync`, the `daily_metrics` table is **untouched** (empty
      / row-count unchanged); `grep -n "recompute\|readiness\|daily_metrics" app/api/routes/sync.py
      app/services/*.py` finds nothing (MODELS "SyncResponse"; epic §3/§7).
- [ ] After moving `now_sofia` to `app/core/time.py`, the E1·P2 `/health` tests still pass (no behaviour
      change; `/health` imports `now_sofia` from `app.core.time`).
- [ ] `uv run ruff check app/api/routes/sync.py app/core/time.py tests/api/routes/test_sync.py` is clean.

## Steps

### RED
- [ ] Add `tests/api/routes/test_sync.py`: build `create_app()` (known `api_token`, engine pointed at a
      migrated temp `app.db`); assert the success-path `200` + camelCase counts + stubbed flags +
      aware `serverTime` (+ Jan/Jul DST offsets via injected clock); the replay idempotency case; the
      no-token and wrong-token `401` `unauthorized` cases; the whitelist-drop case; and that
      `daily_metrics` is untouched. Run — fails (no `/sync` route).

### GREEN
- [ ] Add `app/api/routes/sync.py` per **Files** (authed route → one transaction → three services →
      commit → `SyncResponse`) and register it in `create_app()`. Run — tests pass.

### REFACTOR
- [ ] If the session-open/commit/rollback boilerplate is noisy, wrap it in a tiny local context manager
      (or reuse an E2·P1 `get_session()` context if it exists); keep `now_sofia` as the single
      serverTime source; confirm `ruff check` is clean.

## Notes

The route is the only HTTP-aware piece — the services stay pure. `SyncResponse` inherits `CamelModel`
(E5·P1, `serialize_by_alias=True`), so returning the model gives camelCase wire keys without
`by_alias=True`. `checkinSaved`/`strengthTestSaved` are **deliberately `false`** here: `SyncRequest`
carries `checkin`/`strengthTest`, but persisting them (and the `daily_metrics` recompute fan-out) is
**E5·P3** (epic §3) — this phase ignores those two body fields and returns the stub flags (documented in
PLAN Out of Scope). `now_sofia` is relocated to `app/core/time.py` (round-1 #3) so `/sync` and `/health`
share one DST-aware `serverTime` source and never hard-code `+03:00` (MODELS "Conventions → Timestamps");
the `/health` DST tests (E1·P2) must stay green after the import move.
