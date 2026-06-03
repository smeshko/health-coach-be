# TASK-004: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for e4-p3-seed-reconcile`

## Goal

Confirm every PLAN.md acceptance criterion is met with a concrete, non-circular check (a named command or
test) on the Python/uv stack: the whitelist is finalized and shared with E5, the seed copies the trailing 90
Sofia days with `origin='seed'`/`uuid=NULL` + the three deltas, the reconciliation drops fully-covered seed
days while keeping sync + partial-day seed rows, and nothing leaks `baseline.db` into the runtime or pulls in
the dropped stack.

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked (TASK-001…003).
- [ ] **Lint:** `uv run ruff check .` passes with no issues.
- [ ] **Tests:** `uv run pytest tests/core/test_healthkit.py tests/scripts/test_seed_app_db.py
      tests/scripts/test_reconcile_seed.py` passes.

### Acceptance-criteria checks (1:1 with PLAN.md)

- [ ] **Whitelist set finalized & complete** → `uv run pytest tests/core/test_healthkit.py` passes (asserts
      `WHITELISTED_TYPES` is a `frozenset` with every activity/recovery id + `BodyMass` + all seven
      `Dietary*`; `is_whitelisted` True for an in-set type, False for `…EnvironmentalAudioExposure`).
      Cross-check: `uv run python -c "from app.core.healthkit import WHITELISTED_TYPES, is_whitelisted as w;
      assert w('HKQuantityTypeIdentifierDietaryProtein') and w('HKQuantityTypeIdentifierBodyMass') and not
      w('HKQuantityTypeIdentifierEnvironmentalAudioExposure'); print(len(WHITELISTED_TYPES))"`.
- [ ] **90-day window bounds correct on Europe/Sofia days (incl. DST)** → `uv run pytest
      tests/scripts/test_seed_app_db.py -k "window or bounds or dst or sofia"` passes (in-window kept,
      out-of-window dropped; a near-midnight `+0200`/`+0300` sample lands on the correct Sofia day + side of
      the window).
- [ ] **`origin='seed'` + `uuid IS NULL` on seeded records/workouts** → `uv run pytest
      tests/scripts/test_seed_app_db.py -k "origin or uuid or seed_flag"` passes (all seeded
      `records`/`workouts` rows `origin='seed'` and `uuid IS NULL`; `activity_summary` has no `origin`
      column — seeded by date-PK upsert).
- [ ] **Whitelist filtering applied** → `uv run pytest tests/scripts/test_seed_app_db.py -k "whitelist or
      dietary or body_mass or absent"` passes (dietary + `body_mass` present; a non-whitelisted `type`
      absent from `records`).
- [ ] **Three-delta copy correct** → `uv run pytest tests/scripts/test_seed_app_db.py -k "rename or date or
      stats or effort or fk"` passes (`activity_summary.date` = source Sofia date, addressable by the `date`
      PK, no `origin` column; seed stat `workout_id` = new `workouts.id`; seed workouts'
      `effort_score`/`physical_effort` NULL).
- [ ] **Seed is idempotent** → `uv run pytest tests/scripts/test_seed_app_db.py -k "idempot"` passes (two
      seed runs into the same `app.db` → identical rows, no duplication, stable counts).
- [ ] **Reconciliation drops fully-covered seed days, keeps sync + partial-day seed rows** → `uv run pytest
      tests/scripts/test_reconcile_seed.py -k "covered or drop or keep or sync"` passes (covered-day seed
      rows in `records`/`workouts` deleted; child `workout_statistics` removed before their parent — no FK
      error/orphans; `'sync'` rows untouched; partial-day seed rows kept; `activity_summary` not touched).
- [ ] **Reconciliation is idempotent** → `uv run pytest tests/scripts/test_reconcile_seed.py -k "idempot"`
      passes (second run deletes 0 rows / all-zero counts).
- [ ] **Offline / never opened at runtime** → `grep -REn "baseline\.db" app` returns no hits; `scripts/
      seed_app_db.py` imports from `app/` only `app.core.healthkit` + `app.core.time` (and `app.core.settings`
      for the default path); `scripts/reconcile_seed.py` opens only `app.db`. Manual:
      `grep -REn "baseline\.db" app && echo LEAK || echo clean` → `clean`.
- [ ] **No dropped-stack leakage** → `! grep -REn "psycopg|pgvector|celery|redis|supabase|vecs" scripts`
      returns nothing (the seed/reconcile are stdlib `sqlite3` only).
- [ ] **Tests never read the real corpus** → `! grep -REn "\.\./db/baseline\.db|export\.xml" tests` finds no
      reference to the real corpus (tests use a synthetic `baseline.db` + a migrated temp `app.db` in
      `tmp_path`).
- [ ] **Lint + suite** → `uv run ruff check .` and `uv run pytest tests/core/test_healthkit.py
      tests/scripts/test_seed_app_db.py tests/scripts/test_reconcile_seed.py` both pass.

- [ ] `PLAN.md` acceptance criteria all met (each mapped above to a concrete check, not "all met").
