# Plan: E5·P3 — Check-in & strength-test upsert + recompute hook

Status: draft
Risk: small
Created: 2026-06-03

> Epic **E5 — Sync / Ingest (`POST /sync`)**, phase **P3** (the last of three). Source of truth:
> [`epics/E05-sync-ingest.md`](../../../epics/E05-sync-ingest.md) (§1 summary, §2 **R4** upsert rules /
> **R7** objective-only check-in, §3 **E5·P3**, §4 acceptance — `iso_week` mapping / one-test-per-week /
> no body-weight field / recompute fan-out, §6 validation, §7 out-of-scope) · grounded in
> [`docs/architecture/MODELS.md`](../../../docs/architecture/MODELS.md) **"POST /sync"** —
> **`DailyCheckin`** (`date`/`giSymptoms`/`kneePain`/`illness`), **`StrengthTest`**
> (`date`/`maxPushups`/`maxPullups`, "server maps to the ISO week") and **`SyncResponse`**
> (`checkinSaved`/`strengthTestSaved`), [`docs/architecture/DB.md`](../../../docs/architecture/DB.md)
> **§3** (`checkins` PK `date` / `strength_tests` `UNIQUE(iso_week)` column-by-column) and **§6** (write
> path — "then **recompute `daily_metrics`** for affected dates") and
> [`docs/architecture/ARCHITECTURE.md`](../../../docs/architecture/ARCHITECTURE.md) **§3** (data model —
> coaching-state tables) + **§4** (period key & timezone — derive through the Europe/Sofia tz database).
>
> **Depends on E5·P2** (`app/api/routes/sync.py` `POST /sync` endpoint + `app/services/`
> `upsert_records`/`upsert_workouts`/`upsert_activity` — the records/workouts/activity upsert this phase
> extends; `checkinSaved`/`strengthTestSaved` are stubbed `false` there), **E5·P1**
> (`app/api/schemas/sync.py` `DailyCheckin`/`StrengthTest`/`SyncResponse` wire models +
> `SyncRequest.checkin`/`strength_test`), **E2·P3** (`app/database/models/` `Checkins` PK `date` /
> `StrengthTests` `UNIQUE(iso_week)` ORM models + their migration), **E2·P1**
> (`app/core/time.py` `iso_week(dt)`/`period_date(dt)`/`to_sofia(dt)`/`now_sofia()` Europe/Sofia helpers,
> `app/database/engine.py` `SessionLocal`/`get_session`) and **E6** (the `daily_metrics` recompute
> ENGINE — **not yet built**; this phase defines the clean interface/seam it will implement).
>
> This phase **completes `POST /sync`**: it persists the check-in and the optional weekly strength test,
> wires the `daily_metrics` recompute **fan-out** as an injectable seam (E6 implements the engine), and
> flips the two stubbed `SyncResponse` flags. `/sync` still does **no** readiness computation.

## Goal

Complete `POST /sync` by upserting the daily check-in (by `date`) and the optional weekly strength test
(by **server-derived** `iso_week`), firing the `daily_metrics` recompute interface for **exactly** the
set of Europe/Sofia dates this sync touched, and setting `checkinSaved`/`strengthTestSaved` in
`SyncResponse` — with the recompute **engine** deferred to E6 behind a documented callable seam.

## Scope

- **`app/services/checkin_upsert.py`** (TASK-001) — `upsert_checkin(session, checkin: DailyCheckin |
  None) -> bool`: returns `False` (no write) when `checkin is None`; otherwise maps the wire model →
  a `Checkins` row (`date`→`date` (the `YYYY-MM-DD` string), `gi_symptoms` bool→`0/1` INTEGER,
  `illness` bool→`0/1` INTEGER, `knee_pain` int 0–10→`knee_pain`) and **upserts by the `date` PK** via
  `sqlalchemy.dialects.sqlite.insert(...).on_conflict_do_update(index_elements=["date"], set_={...})`
  so a second post of the same `date` **updates in place** (one row per date). Sets `created_at` on
  insert and `updated_at` on every write to a DST-aware Europe/Sofia timestamp (`now_sofia()`,
  E2·P1/E5·P2). Returns `True` when a row was written (DB.md §3; epic R4/R7; MODELS DailyCheckin).
- **`app/services/strength_test_upsert.py`** (TASK-002) — `upsert_strength_test(session, test:
  StrengthTest | None) -> bool`: returns `False` when `test is None`; otherwise **derives `iso_week`
  server-side** from the test's `date` via the E2·P1 `iso_week(...)` Europe/Sofia helper (`YYYY-Www`;
  the date is parsed/localized to Europe/Sofia first), maps the wire model → a `StrengthTests` row
  (`date`→`date`, derived `iso_week`→`iso_week`, `max_pushups`→`max_pushups`, `max_pullups`→
  `max_pullups`, `created_at`=`now_sofia()`) and **upserts by `iso_week`** (the `UNIQUE(iso_week)`
  column) via `on_conflict_do_update(index_elements=["iso_week"], set_={...})` so a second test in the
  same ISO week **updates the one row** (one test per week). Returns `True` when written (DB.md §3
  `strength_tests`; epic R4 "server-derived `iso_week`"; MODELS StrengthTest; ARCHITECTURE §4).
- **`app/services/recompute.py`** (TASK-003) — the **recompute SEAM** (the E6 contract, engine deferred):
  - a `RecomputeDailyMetrics` `typing.Protocol` (callable `(dates: set[date]) -> None`) documenting the
    interface E6's engine implements;
  - a default **no-op** implementation `noop_recompute(dates: set[date]) -> None` (this phase ships no
    engine — DB.md §6 recompute is E6; epic §3/§7);
  - `affected_dates(request: SyncRequest) -> set[date]` — computes the set of **Europe/Sofia** dates this
    sync touched: the `date` of each `records`/`workouts` sample (its `start` localized to Europe/Sofia
    via `period_date`/`to_sofia`), each `activity_summary[].date`, the `checkin.date`, and the
    `strength_test.date` (each `date`-typed field used directly; each datetime field via `period_date`).
    This is the canonical affected-day set DB.md §6 says to recompute (ARCHITECTURE §4 period key).
- **`app/api/routes/sync.py`** (TASK-003) — **extend** the E5·P2 route: after the existing
  records/workouts/activity upserts, call `checkin_saved = upsert_checkin(session, body.checkin)` and
  `strength_test_saved = upsert_strength_test(session, body.strength_test)` **inside the same
  transaction**, `commit()`, then call the injected `recompute(affected_dates(body))` **after commit**
  (so the engine reads committed data). The recompute callable is an **injectable dependency**
  (`Depends`-provided / module-level provider defaulting to `noop_recompute`) so a test can supply a spy
  and E6 can swap in the real engine without touching the route. Return `SyncResponse(...,
  checkin_saved=checkin_saved, strength_test_saved=strength_test_saved, ...)` — completing E5·P2's
  stubbed `False` flags. Still **no** readiness computation (MODELS SyncResponse; epic §3).
- **Tests** (`tests/services/` + `tests/api/routes/`), each over a **migrated temp file `app.db`** (via
  E2's Alembic migration / `Base.metadata.create_all`) so the real `ON CONFLICT` paths run:
  - `tests/services/test_checkin_upsert.py` — first upsert writes one `checkins` row (flags mapped
    `bool→0/1`, `knee_pain` stored); **second post of the same `date` updates in place** (still one row,
    new values, `updated_at` advanced); `None` → no row, returns `False`.
  - `tests/services/test_strength_test_upsert.py` — a `date` maps to the **correct `iso_week`** incl.
    ISO-week-edge dates: a **Sunday/Monday boundary** (Sunday belongs to the ending week, the following
    Monday to the next) and a **year-boundary week** (e.g. 2024-12-30 → `2025-W01`; 2021-01-01 →
    `2020-W53`); a **second test in the same ISO week upserts the one row** (one test per week); `None`
    → no row, returns `False`.
  - `tests/services/test_recompute.py` — `affected_dates(...)` returns **exactly** the union of every
    touched Europe/Sofia date (records/workouts starts, activity dates, checkin date, strength-test
    date), de-duplicated; a record whose `start` offset crosses the Europe/Sofia day boundary is bucketed
    to the **Sofia** date, not the wire-offset date; `noop_recompute` is a safe no-op.
  - `tests/api/routes/test_sync.py` (extend E5·P2's) — `POST /sync` with a `checkin` returns
    `checkinSaved=true` and persists one `checkins` row; with a `strengthTest` returns
    `strengthTestSaved=true` and persists one `strength_tests` row at the derived `iso_week`; **absent**
    `checkin`/`strengthTest` → both flags `false`; the injected **recompute spy** is called **once** with
    **exactly** the affected-date set for the posted body (asserted via a captured-args spy); replay of
    the same body keeps `checkins`/`strength_tests` at one row each and still fires recompute.

## Out of Scope

- **The `daily_metrics` recompute ENGINE** — computing any `daily_metrics` value (sleep/HRV/RHR/zone-min/
  nutrition rollups, 30-day baselines, readiness/band) is **E6** (DB.md §2, §6; epic §3/§7). This phase
  ships **only the seam**: the `RecomputeDailyMetrics` protocol, a `noop_recompute` default, the
  `affected_dates(...)` fan-out set, and the injection point in the route. E6 implements the protocol and
  is wired in as the provider — no route change needed. A test asserts the hook is **fired with the right
  dates**, not that any metric is computed.
- **Readiness / safety-gate computation** — `/sync` performs **no** readiness computation (MODELS
  SyncResponse; epic §3); that is the daily brief (E11). The route imports no readiness module.
- **Records / workouts / activity upsert + the `/sync` endpoint shell + count derivation** — **E5·P2**
  (`app/services/record_upsert.py`/`workout_upsert.py`/`activity_upsert.py`, `app/api/routes/sync.py`).
  This phase **extends** the existing route and **adds two more services**; it does not redefine the
  records/workouts/activity writers or the `recordsUpserted`/`recordsDuplicate`/`workoutsUpserted`/
  `activityDaysUpserted` counts.
- **The wire models** (`DailyCheckin`/`StrengthTest`/`SyncRequest`/`SyncResponse`) — **E5·P1**
  (`app/api/schemas/sync.py`). This phase **consumes** them; it defines no new wire model and adds no
  field (the check-in stays objective-only with no body-weight field — epic R7).
- **The `checkins` / `strength_tests` / `daily_metrics` ORM models + migration** — **E2·P3**
  (`app/database/models/`). This phase **writes into** `checkins`/`strength_tests` and defines no ORM
  model, column, or migration; the `UNIQUE(iso_week)` and `date` PK it upserts on already exist.
- **The period-key / timestamp helpers** (`iso_week`/`period_date`/`to_sofia`/`now_sofia`) — **E2·P1**
  (`app/core/time.py`). This phase **uses** them and never hard-codes `+03:00` or re-derives a week key.
- **The bearer auth dependency / `unauthorized` envelope** — **E1·P2**; already applied to `/sync` by
  E5·P2. This phase changes no auth behaviour (the existing E5·P2 auth tests stay green).
- **`/brief/daily` & `/brief/weekly`** (E10/E11) and the **90-day seed** (E4).
- **Dropped stack** — Postgres/pgvector, Celery, Redis, Supabase, streaming, RAG/`vecs` (ARCHITECTURE §1
  stack note). Synchronous SQLAlchemy over SQLite (WAL).

## Research Summary

This phase finishes the third write path of `POST /sync`. DB.md **§3** fixes the two target tables:
`checkins` has `date` as its **TEXT PK** ("upsertable by date") and is **objective-only** — `gi_symptoms`
/ `illness` (0/1) and `knee_pain` (0–10, 0 = none), **no body-weight field** (weight is the HealthKit
`body_mass` record → `daily_metrics.body_weight`); `strength_tests` keeps a surrogate `id` PK with
`iso_week` carrying a **`UNIQUE` constraint** ("one test per week"), and the server **derives** that
`iso_week` from the test's `date`. Period keys are `YYYY-Www`, derived through the **Europe/Sofia tz
database** (DST-aware), never a fixed offset — so the E2·P1 `iso_week(...)` helper is the single
authority for the week key (MODELS Conventions/Dates; ARCHITECTURE §4). DB.md **§6** is explicit that the
`/sync` write path ends with "**then recompute `daily_metrics` for affected dates**" — but the recompute
engine is **E6** (epic §3/§7 puts E6 as the implementer and lists "computing `daily_metrics` values" as
out of scope for E5), so this phase defines a clean **callable seam** (`RecomputeDailyMetrics` protocol +
`noop_recompute` default + `affected_dates(...)` fan-out + an injection point) and asserts the hook is
fired with the exact affected-date set. E5·P2 already shipped the `/sync` endpoint with
`checkinSaved`/`strengthTestSaved` **stubbed `false`**; this phase flips them by returning the two
services' booleans (MODELS SyncResponse).

## Decisions

- **Two new pure services in `app/services/` (one per coaching-state table); the route stays the thin
  shell** (NOTES; mirrors E5·P2). `upsert_checkin`/`upsert_strength_test` are `(session, wire_model |
  None) -> bool` functions with **no** FastAPI/HTTP imports, so they're unit-testable against a session
  and reusable. The E5·P2 `/sync` route is **extended** (two more calls inside the existing transaction +
  the post-commit recompute), not rewritten.
- **`iso_week` is derived server-side from `StrengthTest.date` via the E2·P1 Europe/Sofia helper, never
  taken from the client** (epic R4 "server-derived"; MODELS StrengthTest "server maps to the ISO week";
  ARCHITECTURE §4). The wire model carries only `date`/`maxPushups`/`maxPullups`; the service computes
  `iso_week = iso_week(<date localized to Europe/Sofia>)`. ISO-8601 week rules (Mon-start, ISO-8601
  week-numbering year) are handled by `datetime.isocalendar()` inside the E2·P1 helper — tested at the
  Sunday/Monday and year boundaries so the off-by-one and year-boundary edge cases are pinned.
- **`checkins` upsert is `ON CONFLICT(date) DO UPDATE` (true upsert), not `DO NOTHING`** (DB.md §3
  "upsertable by date"; epic §4 "second post same date updates"). A re-posted check-in must correct the
  day's flags in place (one row per date), so the writer updates the mutable columns and bumps
  `updated_at`; `created_at` is set only on first insert.
- **`strength_tests` upsert is `ON CONFLICT(iso_week) DO UPDATE` keyed on the UNIQUE column** (DB.md §3
  `UNIQUE(iso_week)`; epic §4 "second test in the same week upserts — one per week"). The surrogate `id`
  is the row identity; `iso_week` is the conflict target so a corrected test for the week overwrites the
  one row rather than inserting a second (which the UNIQUE constraint would reject).
- **The recompute hook is a callable SEAM (`RecomputeDailyMetrics` protocol + `noop_recompute` default),
  injected into the route — the engine is E6** (NOTES; DB.md §6; epic §3/§7). Defining the contract here
  (a `(dates: set[date]) -> None` protocol) and the fan-out (`affected_dates`) is the load-bearing work;
  shipping a no-op default keeps `/sync` correct today and lets E6 drop in the real engine **by swapping
  the provider only** — no route edit. This honours DB.md §6's "recompute affected days on every sync"
  while keeping "computing `daily_metrics` values" in E6 (epic §7).
- **`affected_dates(...)` buckets every touched datum to its Europe/Sofia date, not the wire offset**
  (ARCHITECTURE §4 "always resolve today/this week through the tz database"; DB.md §0). A sample emitted
  at `2026-06-02T23:30:00+03:00` and another at `+00:00` can fall on different Sofia days; the fan-out
  localizes each `start`/datetime via the E2·P1 `period_date`/`to_sofia` helper before taking the date,
  and uses `date`-typed fields (`activity_summary.date`, `checkin.date`, `strength_test.date`) directly.
  The result is a de-duplicated `set[date]` — the exact set DB.md §6 says to recompute.
- **Recompute fires AFTER `commit()`, unconditionally, with `affected_dates(body)`** so the (future) E6
  engine reads committed rows, and a recompute failure can't roll back a successful ingest. The upserts
  (records/workouts/activity/checkin/test) are one transaction; the recompute is a separate post-commit
  fan-out call. The call is **unconditional even when the affected set is empty** (an empty body, or one
  whose only records are non-whitelisted): `noop_recompute(set())` is a no-op and a real E6 engine treats
  `set()` as "nothing to do", so behaviour is deterministic rather than a guess about skip-vs-call.
- **`checkinSaved`/`strengthTestSaved` are the two services' return booleans** (MODELS SyncResponse;
  completes E5·P2's documented stub). `True` when a row was written, `False` when the body field was
  absent (`None`). This makes "check-in present → saved; absent → not saved" observable end-to-end.
- **Timestamps via the E2·P1/E5·P2 `now_sofia()` helper, never a hard-coded offset** (MODELS Conventions
  → Timestamps; DB.md §0). `created_at`/`updated_at` on `checkins` and `created_at` on `strength_tests`
  are DST-aware Europe/Sofia ISO-8601 TEXT, reusing the one shared time helper (no new clock).
- **Bool→INTEGER mapping is explicit at the write boundary** (DB.md §3 stores `gi_symptoms`/`illness` as
  INTEGER 0/1; the wire model carries `bool`). The service maps `int(checkin.gi_symptoms)` /
  `int(checkin.illness)` so the stored value matches the schema; a test reads the column back as `0`/`1`.

## Risks

- **`iso_week` derived wrong at an ISO-week boundary** (Sunday counted into next week, or the year
  boundary off by one) → the wrong week's test is overwritten / a duplicate week is created. Mitigation:
  derive via the E2·P1 `iso_week(...)` helper (which uses `isocalendar()`); tests pin a Sunday/Monday
  boundary **and** a year-boundary week (e.g. 2024-12-30 → `2025-W01`, 2021-01-01 → `2020-W53`).
- **Check-in not upserted (second post inserts a second row or is ignored)** → stale flags or a
  PK-violation error. Mitigation: `ON CONFLICT(date) DO UPDATE`; a test posts the same `date` twice with
  different flags and asserts **one** row carrying the **second** values and an advanced `updated_at`.
- **Strength test inserts a duplicate for the week** (UNIQUE violation) instead of updating → 5xx on a
  re-test. Mitigation: `ON CONFLICT(iso_week) DO UPDATE`; a test posts two tests in the same ISO week and
  asserts **one** row carrying the second values, no `IntegrityError`.
- **Recompute fired with the wrong date set** (missing a touched day, including an untouched one, or
  bucketing to the wire offset instead of Sofia) → E6 recomputes the wrong days. Mitigation:
  `affected_dates(...)` is unit-tested to return **exactly** the de-duplicated union of every touched
  Sofia date (incl. a day-boundary-crossing offset case); the route test asserts the spy is called once
  with that exact set.
- **Recompute coupled into the transaction / a real engine sneaks in** → an ingest rolls back on a
  recompute error, or E5 starts computing metrics (scope creep into E6). Mitigation: recompute fires
  **after** `commit()` via the injected callable, default `noop_recompute`; a boundary check greps the
  route + services for metric computation and finds only the seam; the engine stays E6.
- **`checkinSaved`/`strengthTestSaved` left stubbed / mis-set** → the response lies about what persisted
  (epic §4). Mitigation: the route returns the two services' booleans; tests assert `true` when present,
  `false` when absent, and that the row count matches.
- **A body-weight field creeps onto the check-in write** → two live-weight sources (DB.md §1/§3 forbid
  it). Mitigation: `upsert_checkin` writes only `date`/`gi_symptoms`/`illness`/`knee_pain`/timestamps;
  the wire model has no weight field (E5·P1), so there is nothing to map — asserted by the column set.
- **Timestamp hard-codes `+03:00` / loses the offset** → breaks across DST (MODELS). Mitigation: reuse
  `now_sofia()`; a test asserts the stored `updated_at`/`created_at` parses to a timezone-aware datetime.

## Acceptance Criteria

- [ ] **Check-in upsert by `date` (second post updates in place).** `upsert_checkin` over a fresh DB
      writes one `checkins` row with `gi_symptoms`/`illness` stored as `0/1` and `knee_pain` stored; a
      second `upsert_checkin` with the **same `date`** and different flags leaves **one** row carrying the
      **second** values with an advanced `updated_at`; `checkin=None` writes no row and returns `False`
      (`tests/services/test_checkin_upsert.py`). (DB.md §3; epic R4/R7, §4)
- [ ] **Strength test → correct server-derived `iso_week`, including ISO-week-edge dates.** A
      `StrengthTest.date` maps to the `iso_week` the E2·P1 Europe/Sofia helper yields — verified at a
      **Sunday/Monday boundary** (Sunday → the ending week, the next Monday → the next week) **and** a
      **year-boundary week** (2024-12-30 → `2025-W01`; 2021-01-01 → `2020-W53`)
      (`tests/services/test_strength_test_upsert.py`). (epic R4 "server-derived `iso_week`", §4; MODELS
      StrengthTest; ARCHITECTURE §4)
- [ ] **One strength test per ISO week (second in the same week upserts).** Two `StrengthTest`s whose
      dates fall in the same ISO week leave **one** `strength_tests` row at that `iso_week` carrying the
      **second** values, no `IntegrityError` (`tests/services/test_strength_test_upsert.py`). (DB.md §3
      `UNIQUE(iso_week)`; epic §4)
- [ ] **No body-weight field on the check-in.** `upsert_checkin` writes only
      `date`/`gi_symptoms`/`illness`/`knee_pain`/`created_at`/`updated_at`; weight is never written here
      and `DailyCheckin` has no weight field (`tests/services/test_checkin_upsert.py` asserts the written
      column set; E5·P1 model assertion). (epic R7; DB.md §1/§3)
- [ ] **Recompute fan-out = exactly the affected Sofia-date set.** `affected_dates(request)` returns the
      de-duplicated union of every touched Europe/Sofia date (records/workouts `start`, activity dates,
      check-in date, strength-test date), bucketing offset-crossing samples to the **Sofia** date
      (`tests/services/test_recompute.py`). (DB.md §6; ARCHITECTURE §4)
- [ ] **`/sync` fires the recompute hook with the right dates (spy), and `noop` default is harmless.**
      `POST /sync` calls the **injected** recompute callable **once** with **exactly** `affected_dates(body)`
      (asserted via a captured-args spy); with the default `noop_recompute`, a sync still succeeds and
      computes **no** `daily_metrics` values (`tests/api/routes/test_sync.py`). (DB.md §6; epic §4 "via E6
      hook / a spy in tests"; epic §7 — engine is E6)
- [ ] **`checkinSaved`/`strengthTestSaved` set correctly (incl. absent → false).** `POST /sync` returns
      `checkinSaved=true`/`strengthTestSaved=true` when the body carries them (and persists one row each),
      and **both `false`** when they are absent (`tests/api/routes/test_sync.py`). (MODELS SyncResponse;
      epic §3, §4 — completes E5·P2's stubs)
- [ ] **`/sync` does no readiness computation.** The route + the two new services import no readiness
      module; after a sync no `readiness_score`/`band` is written (`grep`-asserted + a `daily_metrics`
      check) (`tests/api/routes/test_sync.py`). (MODELS SyncResponse; epic §3, §7)
- [ ] **End-to-end idempotency holds for the new writers.** Replaying the same body keeps `checkins` and
      `strength_tests` at **one row each** (upsert, not duplicate) and still returns the saved flags
      `true` (`tests/api/routes/test_sync.py`). (DB.md §3; epic §4)
- [ ] `uv run ruff check .` and `uv run pytest tests/services tests/api/routes/test_sync.py` pass.

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [ ] TASK-001: checkins upsert by date
- [ ] TASK-002: strength_tests upsert by derived iso_week
- [ ] TASK-003: daily_metrics recompute hook fan-out and response flags
- [ ] TASK-004: Final Validation
