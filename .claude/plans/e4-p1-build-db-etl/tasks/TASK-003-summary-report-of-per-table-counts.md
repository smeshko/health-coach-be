# TASK-003: Summary report of per-table counts

Depends on: TASK-002
Suggested commit: `feat(scripts): print per-table count summary report after build`

## Goal

Add a `summarize(conn)` helper that returns the per-table row counts for the four `baseline.db` tables and
have `main()` print it after a build as a sanity check.

## Files

- `scripts/build_db.py` — extend:
  - `summarize(conn) -> dict[str, int]` — `SELECT COUNT(*)` for each of `records`, `workouts`,
    `workout_statistics`, `activity_summary`; return an ordered mapping `{table: count}`.
  - `main(argv)` — after `build(...)`, print the report, e.g.
    `records=… workouts=… workout_statistics=… activity_summary=…` (one human-readable line; the build
    already returns the counts, so `summarize` re-reads from the DB as the authoritative post-build check).
- `tests/scripts/test_build_db.py` — extend (added in TASK-002): assert `summarize(conn)` returns a mapping
  whose four values equal the actual `COUNT(*)` per table for the fixture, and that the report covers
  exactly the four tables.

## Acceptance

- [ ] `summarize(conn)` returns `{"records": n1, "workouts": n2, "workout_statistics": n3,
      "activity_summary": n4}` where each value equals the table's real `COUNT(*)`.
- [ ] The report contains exactly the four tables (no extras, none missing).
- [ ] `main()` prints the per-table counts after a build (captured via `capsys` or by asserting the
      returned mapping that `main` prints).

## Steps

### RED
- [ ] In `tests/scripts/test_build_db.py`, add a `summarize` test: build the fixture, call `summarize(conn)`
      and assert each value equals an independent `SELECT COUNT(*)`; assert the key set is exactly the four
      tables. (Fails — `summarize` not implemented.)

### GREEN
- [ ] Implement `summarize` and call/print it from `main` after `build`.

### REFACTOR
- [ ] Keep the table list defined **once** (e.g. a module-level `TABLES` tuple reused by `init_schema`'s
      DROP list and `summarize`) so the report can't drift from the schema.

## Notes

A summary report is the phase's lightweight sanity check (epic §3 E4·P1; §4 "non-zero counts across the
four tables") — counts per table after a build, nothing more. Reusing a single `TABLES` constant for both
the `DROP TABLE` list and `summarize` keeps them in lockstep.
