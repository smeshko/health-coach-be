# TASK-004: Final Validation

Depends on: TASK-001, TASK-002, TASK-003
Suggested commit: `chore: final validation for e5-p3-checkin-strength-hook`

## Goal

Confirm every PLAN.md acceptance criterion is met with a concrete, non-circular check, the lint/test gates
are green, and `/sync` is complete with the recompute seam wired (engine deferred to E6).

## Gate commands (run from the repo root)

- [ ] `uv run ruff check .` — clean (no lint errors across the new/edited modules).
- [ ] `uv run pytest tests/services tests/api/routes/test_sync.py` — all pass.
- [ ] `uv run pytest` — the **full** suite is green (E5·P2 records/workouts/activity, auth, and E1/E2
      tests still pass after the route edit + `now_sofia`/helper reuse).

## Acceptance-criterion → concrete check (1:1 with PLAN.md)

- [ ] **Check-in upsert by `date` (second post updates in place).**
      `uv run pytest tests/services/test_checkin_upsert.py` — first insert maps `bool→0/1` + `knee_pain`
      (one row); second post of the same `date` leaves one row with the second values, `created_at`
      preserved, `updated_at` advanced; `None` → no row, returns `False`.
- [ ] **Strength test → correct server-derived `iso_week`, incl. ISO-week-edge dates.**
      `uv run pytest tests/services/test_strength_test_upsert.py -k "iso_week or boundary or year"` — the
      Tuesday→`2026-W23`, the Sunday/Monday boundary (`2026-06-07`→`2026-W23`, `2026-06-08`→`2026-W24`),
      and the year-boundary cases (`2024-12-30`→`2025-W01`, `2021-01-01`→`2020-W53`) all assert the
      derived key.
- [ ] **One strength test per ISO week (second in the same week upserts).**
      `uv run pytest tests/services/test_strength_test_upsert.py -k "upsert or same_week"` — two tests in
      W23 leave one row with the second values, no `IntegrityError`.
- [ ] **No body-weight field on the check-in.**
      `uv run pytest tests/services/test_checkin_upsert.py -k "objective or columns"` — only
      `date`/`gi_symptoms`/`illness`/`knee_pain`/`created_at`/`updated_at` are written; **and**
      `grep -nE "weight|body_mass|bodyMass" app/services/checkin_upsert.py` finds nothing.
- [ ] **Recompute fan-out = exactly the affected Sofia-date set.**
      `uv run pytest tests/services/test_recompute.py` — `affected_dates(...)` returns the de-duplicated
      Sofia-date union; an offset-crossing `start` buckets to the Sofia date.
- [ ] **`/sync` fires the recompute hook with the right dates (spy); `noop` default is harmless.**
      `uv run pytest tests/api/routes/test_sync.py -k "recompute or spy or noop"` — the spy provider is
      called once with `dates == affected_dates(body)`; with the default `noop_recompute`,
      `SELECT count(*) FROM daily_metrics == 0` after a sync.
- [ ] **`checkinSaved`/`strengthTestSaved` set correctly (incl. absent → false).**
      `uv run pytest tests/api/routes/test_sync.py -k "saved or flags"` — present → `true` (+ one row
      each); absent → both `false`.
- [ ] **`/sync` does no readiness computation.**
      `grep -nE "readiness" app/api/routes/sync.py app/services/recompute.py
      app/services/checkin_upsert.py app/services/strength_test_upsert.py` finds nothing; and the test
      asserting no `readiness_score`/`band` is written passes
      (`uv run pytest tests/api/routes/test_sync.py -k "no_readiness or readiness"`).
- [ ] **End-to-end idempotency for the new writers.**
      `uv run pytest tests/api/routes/test_sync.py -k "idempoten or replay"` — replaying the same body
      keeps `checkins`/`strength_tests` at one row each, returns the saved flags `true`, and fires
      recompute again.
- [ ] **`uv run ruff check .` and `uv run pytest tests/services tests/api/routes/test_sync.py` pass**
      (the explicit final gate in PLAN.md Acceptance Criteria).

## Sign-off

- [ ] All TASK checkboxes in `PLAN.md` (TASK-001…TASK-003) are ticked.
- [ ] The recompute **seam** is present (`RecomputeDailyMetrics` protocol + `noop_recompute` +
      `affected_dates` + the route injection point) and the engine is documented as **E6** — no
      `daily_metrics` value is computed in this phase.
- [ ] Boundary check: the two new services and `recompute.py` contain **no** FastAPI/HTTP import
      (`grep -nE "fastapi|APIRouter|Depends|TestClient" app/services/checkin_upsert.py
      app/services/strength_test_upsert.py app/services/recompute.py` finds nothing); only
      `app/api/routes/sync.py` is HTTP-aware.
- [ ] No hard-coded `+03:00`/`+02:00` offset in the new code
      (`grep -nE "\+0[23]:00" app/services/checkin_upsert.py app/services/strength_test_upsert.py
      app/services/recompute.py app/api/routes/sync.py` finds nothing — timestamps/period keys flow
      through `app.core.time`).
