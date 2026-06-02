# TASK-003: GET /health endpoint (unauthenticated)

Depends on: TASK-002
Suggested commit: `feat(api): add unauthenticated health endpoint and protected probe`

## Goal

Add an unauthenticated `GET /health` returning process liveness + DST-aware `serverTime`, and a protected
probe route guarded by `require_auth` that demonstrates the `401`-vs-`200` gate.

## Files

- `app/api/routes/health.py` — new:
  - `HealthResponse(CamelModel)` — `status: str` (e.g. `"ok"`), `server_time: datetime` (wire key
    `serverTime`).
  - `now_sofia(clock: Callable[[], datetime] = <utc-now>) -> datetime` — the production conversion helper:
    it takes an **aware UTC instant** from an injected `clock` (default = `datetime.now(timezone.utc)`) and
    converts via `.astimezone(ZoneInfo("Europe/Sofia"))` — an **instant-preserving** conversion, **not** a
    `.replace(tzinfo=...)` relabel. The offset always comes from the tz database; there is **no**
    `timezone(timedelta(...))` fixed-offset construction anywhere (MODELS "Conventions → Timestamps"). Tests
    inject **only the base UTC instant** (a Jan vs a Jul timestamp) — so the real `ZoneInfo` conversion runs
    and both the offset **and the wall-clock** must be correct per season (resolves round-2 #2 and round-3
    #2: `now_sofia` is *not* monkeypatched away, and a relabel is rejected).
  - `router = APIRouter()` with `GET /health` (no auth dependency) returning
    `HealthResponse(status="ok", server_time=now_sofia())`. The injectable `clock` is exposed via a FastAPI
    dependency (or module-level seam) so the test overrides the **UTC source**, not the conversion.
  - A **protected probe** route `GET /probe` (or similar) declared with `dependencies=[Depends(require_auth)]`
    returning a trivial `200` body — exists only to demonstrate the auth gate (epic §4 acceptance);
    superseded by real endpoints in E5/E10/E11.
- `app/api/app.py` — `include_router(health.router)` inside `create_app()`.
- `tests/test_health.py` — new (see Steps).

## Acceptance

- [ ] `GET /health` returns `200` with **no** `Authorization` header; body has `status == "ok"` and a
      `serverTime` string that parses (`datetime.fromisoformat`) to a timezone-aware datetime. **DST proof
      via the production conversion (instant-preserving, not a relabel):** inject only a **base UTC instant**
      and assert the exact converted wall-clock — `2026-01-15T12:00:00Z` → `2026-01-15T14:00:00+02:00`
      (winter) and `2026-07-15T12:00:00Z` → `2026-07-15T15:00:00+03:00` (summer). This catches both a fixed
      `timezone(timedelta(...))` impl (same offset year-round) **and** a `.replace(tzinfo=ZoneInfo(...))`
      relabel (right offset, wrong wall-clock) — only a true `astimezone(ZoneInfo("Europe/Sofia"))` passes
      (round-3 #2).
- [ ] `serverTime` is the camelCase wire key (the model inherits `CamelModel`).
- [ ] The protected probe route returns `401` (`unauthorized` envelope) without/with a wrong token and
      `200` with the correct `Bearer <api_token>` — the end-to-end demonstration of the auth gate.
- [ ] `/health` is reachable without the auth dependency (no `401` is ever returned for it).

## Steps

### RED
- [ ] `tests/test_health.py`: with `create_app()` + valid env, `GET /health` (no header) → `200`,
      `status == "ok"`, the JSON key is `serverTime` (camelCase). Override only the **UTC clock source**:
      `2026-01-15T12:00:00Z` → `serverTime` parses to `2026-01-15T14:00:00+02:00`; `2026-07-15T12:00:00Z` →
      `2026-07-15T15:00:00+03:00` (assert the full converted datetime, not just the offset — catches a
      relabel; `now_sofia`/`ZoneInfo` conversion is *not* replaced). Then hit the probe route: no token →
      `401` + `unauthorized` envelope; wrong token → `401`; correct `Bearer <api_token>` → `200`.

### GREEN
- [ ] Implement `app/api/routes/health.py` (`HealthResponse`, `/health`, protected `/probe`) and wire the
      router into `create_app()`.

### REFACTOR
- [ ] Keep the probe route minimal and clearly marked as a temporary auth demonstration; tidy with `ruff`.

## Notes

`serverTime` mirrors the `serverTime` field already used in `SyncResponse` (MODELS) — same ISO-8601 +
real-offset convention. A bare "offset is not None" check is **insufficient** (a fixed
`timezone(timedelta(hours=3))` passes it), monkeypatching `now_sofia` itself only proves serialization, and
even an offset-only check passes a `.replace(tzinfo=ZoneInfo(...))` **relabel** (right offset, wrong
wall-clock). The seam to inject is the **UTC clock source**, leaving the
`astimezone(ZoneInfo("Europe/Sofia"))` conversion in the production path, and the test asserts the **full
converted wall-clock** (`12:00Z` → `14:00+02:00` Jan, `15:00+03:00` Jul) — only a true instant-preserving
conversion passes (resolves round-2 #2 and round-3 #2).
