# TASK-003: daily_metrics recompute hook fan-out and response flags

Depends on: TASK-001, TASK-002
Suggested commit: `feat(api): wire checkin/strength upsert + daily_metrics recompute seam into POST /sync`

## Goal

Extend the E5·P2 `/sync` route to persist the check-in and strength test, fire the injectable
`daily_metrics` recompute seam for exactly the affected Europe/Sofia dates (engine deferred to E6), and
return `checkinSaved`/`strengthTestSaved` — completing `POST /sync`.

## Files

- `app/services/recompute.py` (new) — the **recompute SEAM** (the E6 contract; engine NOT implemented
  here):
  - `class RecomputeDailyMetrics(typing.Protocol)` with `def __call__(self, dates: set[date]) -> None:
    ...` — the interface E6's engine implements (documented as such in a docstring: "E6 supplies the
    concrete engine; this phase ships a no-op default").
  - `def noop_recompute(dates: set[date]) -> None: return None` — the default seam implementation for this
    phase (DB.md §6 recompute is E6; epic §3/§7). It does **not** read or write `daily_metrics`.
  - `def affected_dates(request: SyncRequest) -> set[date]` — the fan-out set: the union of every
    Europe/Sofia date this sync touched —
    - each `request.records[*].start` and `request.workouts[*].start` → `to_sofia(start).date()` (a
      `datetime.date`; `to_sofia` returns an aware Europe/Sofia datetime, E2·P1), so an offset that
      crosses the Sofia day boundary buckets to the **Sofia** date — NOT the wire-offset date
      (ARCHITECTURE §4). (Use `to_sofia(...).date()`, not `period_date(...)`, so the set holds `date`
      objects, not `YYYY-MM-DD` strings — `period_date` returns a string.)
    - each `request.activity_summary[*].date` (already a calendar `date`) used directly;
    - `request.checkin.date` and `request.strength_test.date` when present (each a calendar `date`);
    - returned as a **de-duplicated `set[date]`** — possibly **empty** (e.g. an empty body, or a body
      whose only records are non-whitelisted): that is fine, the caller always calls `recompute(...)` with
      whatever set this returns (empty → `noop_recompute(set())` is a harmless no-op; a real E6 engine
      treats an empty set as "nothing to do"). Import `to_sofia` from `app.core.time` (E2·P1). No
      FastAPI/HTTP imports — pure.
- `app/api/routes/sync.py` (edit E5·P2) — extend the existing authed `POST /sync` route:
  - inside the existing single transaction, after the records/workouts/activity upserts, call
    `checkin_saved = upsert_checkin(session, body.checkin)` (TASK-001) and `strength_test_saved =
    upsert_strength_test(session, body.strength_test)` (TASK-002).
  - `session.commit()` (unchanged — one transaction for all upserts; rollback + re-raise on error).
  - **after commit**, **always** call `recompute(affected_dates(body))` where `recompute` is an
    **injected** `RecomputeDailyMetrics` (FastAPI `Depends` provider, or a module-level provider function)
    defaulting to `noop_recompute`. The call is unconditional — even an empty affected set is passed
    through (the default no-op and a real E6 engine both handle `set()` harmlessly), so behaviour is
    deterministic, not guessed. Firing post-commit means the (future) E6 engine reads committed rows and a
    recompute error can't roll back a good ingest.
  - return `SyncResponse(..., checkin_saved=checkin_saved, strength_test_saved=strength_test_saved, ...)`
    — replacing E5·P2's stubbed `checkin_saved=False`/`strength_test_saved=False`. The records/workouts/
    activity counts and `server_time=now_sofia()` are unchanged. Still **no** readiness computation.
  - add a provider, e.g. `def get_recompute() -> RecomputeDailyMetrics: return noop_recompute`, and inject
    via `recompute: RecomputeDailyMetrics = Depends(get_recompute)` so a test can `app.dependency_overrides`
    a spy and E6 can override the provider with the real engine **without editing the route**.
- `tests/api/routes/test_sync.py` (extend E5·P2) — add the check-in/strength-test/recompute cases below
  (reuse the E5·P2 migrated-temp-`app.db` + `TestClient` + known-token fixture; override the recompute
  provider with a spy that captures its `dates` arg).

## Acceptance

- [ ] **`affected_dates(body)` = exact Sofia-date union.** Given a body with records/workouts at known
      `start`s, activity dates, a check-in date, and a strength-test date, `affected_dates` returns the
      **de-duplicated** set of their Europe/Sofia dates; a record whose `start` offset crosses the Sofia
      day boundary buckets to the **Sofia** date, not the wire-offset date
      (`tests/services/test_recompute.py`).
- [ ] **`affected_dates` on an empty/date-less body returns `set()`** and `recompute` is still called
      (with the empty set), so an empty sync is deterministic and harmless
      (`tests/services/test_recompute.py` + `tests/api/routes/test_sync.py`).
- [ ] **`POST /sync` fires the recompute spy once with exactly that set.** With a spy provider injected,
      one `POST /sync` calls it **once** with `dates == affected_dates(body)` (captured-args assertion).
- [ ] **`checkinSaved`/`strengthTestSaved` set correctly.** `POST /sync` with a `checkin` returns
      `checkinSaved=true` and persists one `checkins` row; with a `strengthTest` returns
      `strengthTestSaved=true` and persists one `strength_tests` row at the derived `iso_week`; with
      **both absent** returns `checkinSaved=false` **and** `strengthTestSaved=false`.
- [ ] **Default seam is harmless.** With the default `noop_recompute` provider (no override), `POST /sync`
      returns `200` and writes **no** `daily_metrics` row (`SELECT count(*) FROM daily_metrics == 0`).
- [ ] **No readiness here.** `grep -n "readiness" app/api/routes/sync.py app/services/recompute.py
      app/services/checkin_upsert.py app/services/strength_test_upsert.py` finds nothing; no
      `readiness_score`/`band` is written by a sync (MODELS SyncResponse; epic §3/§7).
- [ ] **Idempotent for the new writers (end-to-end).** Replaying the same body keeps `checkins` and
      `strength_tests` at **one row each**, still returns the saved flags `true`, and fires recompute again
      with the same date set.
- [ ] **E5·P2 behaviour preserved.** The existing records/workouts/activity counts, `serverTime`
      aware-datetime, and auth (`401` `unauthorized` without/with a wrong token) tests still pass.
- [ ] `uv run ruff check app/api/routes/sync.py app/services/recompute.py tests/api/routes/test_sync.py
      tests/services/test_recompute.py` is clean.

## Steps

### RED
- [ ] Add `tests/services/test_recompute.py`: assert `affected_dates(...)` returns the exact de-duplicated
      Sofia-date union (incl. an offset-crossing `start` bucketed to the Sofia date) and that
      `noop_recompute(set())` returns `None`. Extend `tests/api/routes/test_sync.py`: spy-provider
      override asserting one call with the exact date set; `checkinSaved`/`strengthTestSaved` true-when-
      present / false-when-absent (+ one row each); default-`noop` leaves `daily_metrics` empty; replay
      idempotency for `checkins`/`strength_tests`. Run — fails (route still stubs the flags; no
      `recompute` module).

### GREEN
- [ ] Add `app/services/recompute.py` (`RecomputeDailyMetrics` protocol, `noop_recompute`,
      `affected_dates`). Edit `app/api/routes/sync.py` to call the two upsert services in the transaction,
      fire `recompute(affected_dates(body))` after commit via the injected provider, and return the real
      `checkin_saved`/`strength_test_saved`. Run — tests pass.

### REFACTOR
- [ ] If the affected-date fan-out reads densely, factor the per-collection date extraction into small
      helpers; keep `to_sofia` (E2·P1) as the only tz authority for the datetime→Sofia-date bucketing;
      confirm the recompute fires strictly **after** commit; `ruff check` clean.

## Notes

The **seam is the deliverable**, not an engine: DB.md §6 says `/sync` ends with "recompute `daily_metrics`
for affected dates", but computing those values is **E6** (epic §3/§7). So this phase ships the
`RecomputeDailyMetrics` protocol + `noop_recompute` default + the `affected_dates(...)` fan-out + an
**injection point**, and proves the hook is fired with the **exact** affected-date set via a spy — E6
later overrides the provider with the real engine and needs **no** route change. Recompute fires **after**
`commit()` so a future engine reads committed data and a recompute failure cannot roll back a successful
ingest. `affected_dates` buckets every datum to its **Europe/Sofia** date (not the wire offset) so the
recompute set is correct across DST/travel offsets (ARCHITECTURE §4). The route remains the only
HTTP-aware piece; the three new modules (`checkin_upsert`, `strength_test_upsert`, `recompute`) are pure.
