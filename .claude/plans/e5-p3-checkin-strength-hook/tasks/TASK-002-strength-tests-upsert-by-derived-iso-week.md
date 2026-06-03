# TASK-002: strength_tests upsert by derived iso_week

Depends on: TASK-001
Suggested commit: `feat(services): add upsert_strength_test (server-derived iso_week, one per week)`

## Goal

Add a pure `upsert_strength_test(session, test)` service that derives the ISO week server-side (Europe/
Sofia) from the test's `date` via the E2·P1 helper and upserts the `strength_tests` row by the
`UNIQUE(iso_week)` column, so there is exactly one test per week.

## Files

- `app/services/strength_test_upsert.py` (new) — `def upsert_strength_test(session: Session, test:
  StrengthTest | None) -> bool`:
  - if `test is None`: return `False`.
  - **derive `iso_week` server-side** from `test.date` (a `datetime.date` on the wire model, E5·P1):
    the E2·P1 `iso_week(dt: datetime)` helper takes an **aware datetime** and rejects naive ones, so
    combine the bare calendar date to **midnight in Europe/Sofia** —
    `datetime.combine(test.date, time.min, tzinfo=ZoneInfo("Europe/Sofia"))` — then call
    `iso_week(<that>)` to get the `YYYY-Www` key. Using **midnight-Sofia** (not a UTC combine) keeps the
    derived ISO week equal to the calendar date's own ISO week (`test.date.isocalendar()`): a UTC combine
    near the day boundary could shift the resulting Sofia day and thus the week, so the combine must be
    local-midnight. Never read an `iso_week` off the client — it is server-derived (epic R4).
  - build insert values: `date = str(test.date)`, `iso_week = <derived>`, `max_pushups =
    test.max_pushups`, `max_pullups = test.max_pullups`, `created_at = now_sofia()`.
  - upsert by the UNIQUE `iso_week` column: `sqlalchemy.dialects.sqlite.insert(StrengthTests)
    .values(**vals).on_conflict_do_update(index_elements=["iso_week"], set_={"date": ..., "max_pushups":
    ..., "max_pullups": ...})` — a second test in the same ISO week overwrites the one row (the surrogate
    `id` PK stays; `iso_week` is the conflict target). `created_at` is excluded from `set_` (preserve the
    first write time).
  - execute via `session.execute(stmt)` (no commit — caller owns the transaction).
  - return `True`.
  - import `StrengthTests` from `app.database.models` (E2·P3), `iso_week`/`now_sofia` from `app.core.time`
    (E2·P1). No FastAPI/HTTP imports.
- `tests/services/test_strength_test_upsert.py` (new) — unit tests over a migrated temp-file `app.db`
  session, covering the `iso_week` derivation edge cases and one-per-week upsert.

## Acceptance

- [ ] `upsert_strength_test(session, None)` returns `False` and writes **no** `strength_tests` row.
- [ ] `upsert_strength_test(session, StrengthTest(date=2026-06-02, maxPushups=42, maxPullups=11))` returns
      `True` and writes **one** row with `iso_week="2026-W23"` (2026-06-02 is a Tuesday in ISO week 23),
      `date="2026-06-02"`, `max_pushups=42`, `max_pullups=11`, non-null `created_at`.
- [ ] **ISO-week edge — Sunday/Monday boundary:** a Sunday date maps to the **ending** ISO week and the
      following Monday to the **next** ISO week (e.g. 2026-06-07 Sunday → `2026-W23`; 2026-06-08 Monday →
      `2026-W24`).
- [ ] **ISO-week edge — year boundary:** 2024-12-30 (Mon) → `2025-W01`; 2021-01-01 (Fri) → `2020-W53`
      (the ISO week-numbering year differs from the calendar year at the boundary).
- [ ] **Midnight-Sofia combine is week-stable:** for every tested `date`, the derived `iso_week` equals
      `"%04d-W%02d" % test.date.isocalendar()[:2]` — i.e. combining at local midnight does not shift the
      week vs the calendar date itself (guards against a UTC-combine off-by-one near a day boundary).
- [ ] **One test per ISO week (upsert):** two `StrengthTest`s whose dates fall in the **same** ISO week
      (e.g. 2026-06-02 then 2026-06-04, both W23) leave **one** row at that `iso_week` carrying the
      **second** values; `SELECT count(*)` is `1`, no `IntegrityError`; `created_at` preserved.
- [ ] `created_at` parses to a **timezone-aware** datetime (no hard-coded offset).
- [ ] `uv run ruff check app/services/strength_test_upsert.py tests/services/test_strength_test_upsert.py`
      is clean.

## Steps

### RED
- [ ] Add `tests/services/test_strength_test_upsert.py`: fixture builds a migrated temp `app.db` session;
      assert the `None`→`False` case, the base mapping + `iso_week` (Tuesday W23), the Sunday/Monday
      boundary pair, the two year-boundary cases (`2025-W01`, `2020-W53`), and the same-week upsert (one
      row, second values, `created_at` preserved). Run — fails (no `upsert_strength_test`).

### GREEN
- [ ] Add `app/services/strength_test_upsert.py` per **Files** (derive `iso_week` via the E2·P1 helper;
      `on_conflict_do_update(index_elements=["iso_week"])`, `created_at` out of `set_`). Run — tests pass.

### REFACTOR
- [ ] Extract the `date → aware Europe/Sofia datetime → iso_week` derivation into a small local helper if
      it clarifies; keep the E2·P1 `iso_week`/`now_sofia` as the only time authority; `ruff check` clean.

## Notes

The whole point of this task is that **the server derives `iso_week`** — the client sends only a `date`
(MODELS StrengthTest "server maps to the ISO week"; epic R4). All week-numbering edge cases (Sunday vs the
next Monday, and the year boundary where the ISO week-numbering year ≠ the calendar year) flow from
`datetime.isocalendar()` inside the E2·P1 `iso_week` helper — the tests pin them so a regression in the
derivation is caught. The E2·P1 helper rejects naive datetimes, so the wire `date` must be combined to an
aware Europe/Sofia datetime before the call. `UNIQUE(iso_week)` (E2·P3) is the conflict target so a
re-test for the week updates rather than raising.
