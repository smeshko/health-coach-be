# TASK-005: Let a valid effort_score replace an invalid stored one

Depends on: TASK-002
Suggested commit: `fix(sync): let a valid effort_score replace an invalid stored one`

## Goal

An out-of-range `effort_score` that reached the DB can still be corrected by a later sync,
so TASK-002's validity gate can't strand a workout as permanently "effort absent".

## Files

- `app/services/workout_upsert.py` — `_backfill_effort_scores` (line ~85): widen the
  `WHERE effort_score IS NULL` guard so a **valid** incoming score also replaces a stored
  value outside `HARD_EFFORT_VALID_RANGE`; NULL-or-invalid is overwritable, a valid stored
  score is still never clobbered.
- `tests/services/test_workout_upsert.py` — new tests (confirm the module's actual test
  file path before writing).

## Acceptance

- [ ] Stored `effort_score = 99`, later sync sends `9` for the same uuid → row becomes `9`.
- [ ] Stored `effort_score = 8` (valid), later sync sends `9` → row stays `8` (the
      never-clobber contract for valid data is unchanged).
- [ ] Stored `NULL`, later sync sends `9` → row becomes `9` (existing behaviour preserved).
- [ ] An **invalid** incoming score (99, -3) never overwrites anything — it is not a
      correction, so a stored `NULL` stays `NULL` and a stored `99` stays `99`.
- [ ] The valid range comes from one shared place with `hard_day` (import the constant
      rather than re-declaring the bounds in the upsert module).
- [ ] **Same-batch duplicate** (round-3 #1): one payload carrying the same uuid twice —
      first with `99`, then with `9` — ends with `9` stored. `insert_new_by_uuid` keeps the
      *first* occurrence of a uuid (`_upsert.py:56-61`) and reports it in `new_uuids`, so
      the corrected second copy is currently dropped twice over: skipped by the insert and
      excluded from the backfill.

Evidence: `uv run pytest tests/services/test_workout_upsert.py -q` output showing the new
tests passing, plus the existing upsert suite still green.

## Steps

### RED
- [ ] Tests for the cases above, driven through `upsert_workouts` (not by calling the
      private helper directly), so the duplicate-row path is genuinely exercised.
- [ ] Same-batch duplicate test: `upsert_workouts([w(uuid=X, effort=99), w(uuid=X,
      effort=9)])` → stored score is `9`.

### GREEN
- [ ] Extend the `update(...).where(...)` predicate to
      `effort_score IS NULL OR effort_score NOT BETWEEN <lo> AND <hi>`, and skip any
      incoming score that is itself out of range.
- [ ] Run the guarded repair over **all** incoming uuids, not just the `new_uuids`
      complement (round-3 #1). The WHERE guard already makes this safe — a valid stored
      score is never touched — so dropping the `new_uuids` exclusion costs nothing and
      closes the same-batch case. Where a batch carries the same uuid more than once, the
      last valid incoming score wins.

### REFACTOR
- [ ] Update the `_backfill_effort_scores` docstring — it currently states the guard
      "never overwrites a score already on the row", which stops being true for invalid
      stored values.

## Notes

Found in validation round-2 #5. Without this, the classifier-side validity gate
(DECISIONS.md Decision 7) is one-way: it correctly refuses to trust a stored `99`, but the
`WHERE effort_score IS NULL` guard then blocks the corrected value forever, so the workout
stays "effort absent" for the rest of its life.

Scope note: this deliberately does **not** add `Field(ge=1, le=10)` bounds at the `/sync`
schema — that remains the deferred round-1 #7 follow-up, since rejecting payloads is an
API-contract change.
