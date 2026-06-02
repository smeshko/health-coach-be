# TASK-003: Europe/Sofia period-key and timestamp helpers

Depends on: None
Suggested commit: `feat(core): add Europe/Sofia period-key and timestamp helpers`

## Goal

Add `Europe/Sofia` (DST-aware) period-key helpers — `period_date` → `YYYY-MM-DD`, `iso_week` →
`YYYY-Www` — and timestamp helpers that parse and **preserve** the per-sample offset HealthKit emits,
never hard-coding `+03:00`.

## Files

- `app/core/time.py` — new:
  - `SOFIA = ZoneInfo("Europe/Sofia")`.
  - `parse_ts(value: str) -> datetime` — parse an ISO-8601 string preserving its tzinfo/offset
    (`datetime.fromisoformat`); raise on a naive/offset-less string (HealthKit always emits an offset).
    Used for **derivation only** (period keys), not for what gets stored.
  - `store_ts(value: str) -> str` — the **storage** helper: **validate** the input is a well-formed
    offset-aware ISO-8601 string (parse it, require an offset) and return the **original string
    unchanged** — the bytes that go into the TEXT column are exactly what HealthKit emitted, no
    reformatting of the offset (`+0200` vs `+02:00`), no fractional-second normalization, no UTC
    rewrite (round-1 #3; DB.md §0; epic R2).
  - `_require_aware(dt: datetime) -> None` — raise `ValueError` if `dt.tzinfo is None` or
    `dt.utcoffset() is None`. Called by `to_sofia`/`period_date`/`iso_week` so a **naive** datetime can
    never silently use the host local timezone (round-2 #3).
  - `to_sofia(dt: datetime) -> datetime` — `_require_aware(dt)` then `dt.astimezone(SOFIA)`.
  - `period_date(dt: datetime) -> str` — Sofia-local calendar date as `YYYY-MM-DD` (via `to_sofia`).
  - `iso_week(dt: datetime) -> str` — Sofia-local ISO week as `YYYY-Www` zero-padded
    (`"%04d-W%02d" % (iso_year, iso_week)` from `to_sofia(dt).isocalendar()`).
  - String convenience wrappers `period_date_of(ts: str)` / `iso_week_of(ts: str)` that `parse_ts` first.
- `tests/core/__init__.py` — ensure present (package marker).
- `tests/core/test_time.py` — new: DST-boundary, travel-offset, ISO-year-boundary, and offset-preservation
  cases.

## Acceptance

- [ ] `period_date` / `iso_week` convert through `Europe/Sofia` (DST-aware): a UTC instant near the
      late-March EET→EEST transition and a late-October EEST→EET transition map to the correct Sofia-local
      date/week (not the UTC date).
- [ ] **Travel offset:** a timestamp with a non-Sofia offset (e.g. `2026-06-15T23:30:00+09:00`) yields the
      correct **Sofia-local** `date`/`iso_week`, proving conversion through the tz db (not the literal
      offset).
- [ ] `iso_week` returns zero-padded `YYYY-Www` (e.g. `2026-W23`) and is correct at an ISO year boundary
      (a date in early January or late December whose ISO week belongs to the adjacent ISO year).
- [ ] **Verbatim storage (string identity):** `store_ts(s) == s` (the **exact** original string is
      returned) for the HealthKit/doc offset forms — `+02:00`, `+03:00`, a compact `+0300`, a non-Sofia
      travel offset, and a fractional-seconds case — proving no offset reformatting / no UTC normalization
      (round-1 #3; DB.md §0; epic R2). `parse_ts(s).utcoffset()` additionally equals the input offset.
- [ ] `parse_ts` / `store_ts` on a naive (offset-less) string raise a clear error.
- [ ] **Naive datetime rejected:** calling `to_sofia` / `period_date` / `iso_week` with a **naive**
      `datetime` (no tzinfo) raises `ValueError` — never falls back to the host local timezone, so cache
      keys are reproducible across dev/CI/containers (round-2 #3).
- [ ] `ZoneInfo("Europe/Sofia")` resolves (tzdata dependency present).

## Steps

### RED
- [ ] `tests/core/test_time.py`: parametrized cases for DST boundary (both directions), travel offset,
      ISO year boundary, zero-padding, `store_ts` **string-identity** preservation across the offset forms
      (round-1 #3), `parse_ts().utcoffset()` preservation, the naive-**string** error for `parse_ts`/
      `store_ts`, and the naive-**datetime** `ValueError` for `to_sofia`/`period_date`/`iso_week`
      (round-2 #3).

### GREEN
- [ ] Implement `app/core/time.py`.

### REFACTOR
- [ ] Module docstring: timestamps are stored as ISO-8601 TEXT carrying the emitted offset; period keys go
      through `Europe/Sofia`. No fixed offset anywhere.

## Notes

DB.md §0 / ARCHITECTURE §4: period keys are derived through the `Europe/Sofia` tz database (EET `+02:00`
winter, EEST `+03:00` summer, plus travel) — never a fixed offset; timestamps are stored as ISO-8601 TEXT
with the offset the sample carries. These helpers are used by E5/E6/E10/E11 (sync, daily_metrics, brief
cache keys) — hence they live in `app/core`, not the DB layer. `iso_week` format `YYYY-Www` is the
`plans.iso_week` cache key (DB.md §4, e.g. `2026-W23`).
