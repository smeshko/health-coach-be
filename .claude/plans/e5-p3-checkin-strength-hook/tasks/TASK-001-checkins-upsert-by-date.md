# TASK-001: checkins upsert by date

Depends on: None
Suggested commit: `feat(services): add upsert_checkin (upsert checkins by date PK)`

## Goal

Add a pure `upsert_checkin(session, checkin)` service that writes the wire `DailyCheckin` into the
`checkins` table upsert-by-`date` (objective-only, no body weight), so a second post of the same date
updates in place.

## Files

- `app/services/checkin_upsert.py` (new) — `def upsert_checkin(session: Session, checkin: DailyCheckin |
  None) -> bool`:
  - if `checkin is None`: return `False` (nothing to persist; the body field was omitted/null).
  - else build the insert values from the wire model (E5·P1 `app.api.schemas.sync.DailyCheckin`):
    `date = str(checkin.date)` (the `YYYY-MM-DD` Europe/Sofia date — the `checkins.date` TEXT PK),
    `gi_symptoms = int(checkin.gi_symptoms)`, `illness = int(checkin.illness)`,
    `knee_pain = checkin.knee_pain` (0–10), `created_at = now_sofia()`, `updated_at = now_sofia()`.
  - upsert by the `date` PK with `sqlalchemy.dialects.sqlite.insert(Checkins).values(**vals)
    .on_conflict_do_update(index_elements=["date"], set_={"gi_symptoms": ..., "illness": ...,
    "knee_pain": ..., "updated_at": now_sofia()})` — **`created_at` is NOT in `set_`** so it is preserved
    from the first insert; only the mutable flags + `updated_at` change on conflict.
  - execute via `session.execute(stmt)` (no commit — the caller owns the transaction, TASK-003).
  - return `True` (a row was written/updated).
  - import the `Checkins` ORM model from `app.database.models` (E2·P3) and `now_sofia` from
    `app.core.time` (E2·P1/E5·P2). **No** FastAPI/HTTP imports — pure service.
- `tests/services/test_checkin_upsert.py` (new) — unit tests over a **migrated temp-file `app.db`**
  (build a temp engine + `Base.metadata.create_all` or run the E2 Alembic migration; open a
  `SessionLocal`-style session bound to it), asserting the behaviours below.
- `tests/services/__init__.py` — ensure the package marker exists (created by E5·P2; add only if absent).

## Acceptance

- [ ] `upsert_checkin(session, None)` returns `False` and writes **no** `checkins` row.
- [ ] `upsert_checkin(session, DailyCheckin(date=2026-06-02, giSymptoms=True, kneePain=4, illness=False))`
      returns `True` and writes **one** row with `gi_symptoms=1`, `illness=0`, `knee_pain=4`, `date`
      `"2026-06-02"`, and non-null `created_at`/`updated_at`.
- [ ] **Upsert by date:** a second `upsert_checkin` for the **same `date`** with different flags
      (`giSymptoms=False`, `kneePain=0`, `illness=True`) leaves **one** row (`SELECT count(*)` unchanged)
      carrying the **second** values; `created_at` is **unchanged** and `updated_at` is **advanced**
      (or at least re-written) vs the first insert.
- [ ] The written row has **no body-weight column** touched — only
      `date`/`gi_symptoms`/`illness`/`knee_pain`/`created_at`/`updated_at` are set (the check-in is
      objective-only; weight is the HealthKit `body_mass` record — DB.md §1/§3).
- [ ] `created_at`/`updated_at` parse to **timezone-aware** datetimes (`datetime.fromisoformat(...).tzinfo
      is not None`) — DST-aware Europe/Sofia, never a hard-coded offset.
- [ ] `uv run ruff check app/services/checkin_upsert.py tests/services/test_checkin_upsert.py` is clean.

## Steps

### RED
- [ ] Add `tests/services/test_checkin_upsert.py`: fixture builds a migrated temp `app.db` session; assert
      the `None`→`False`/no-row case, the first-insert mapping (`bool→0/1`, `knee_pain`), the
      same-`date`-second-post upsert-in-place (one row, second values, `created_at` preserved,
      `updated_at` advanced), the objective-only column set, and the aware timestamps. Run — fails (no
      `upsert_checkin`).

### GREEN
- [ ] Add `app/services/checkin_upsert.py` per **Files** (`on_conflict_do_update(index_elements=["date"])`,
      `created_at` excluded from `set_`). Run — tests pass.

### REFACTOR
- [ ] Factor the wire→column value dict if it reads cleanly; keep `now_sofia()` as the single timestamp
      source; confirm `ruff check` is clean.

## Notes

`created_at` must be excluded from the `on_conflict_do_update` `set_` so a re-posted check-in preserves
its original creation time while `updated_at` advances — that is what makes "upsert by date" observable.
The service does **not** commit; TASK-003's route owns the one transaction. The check-in is objective-only
(DB.md §3, epic R7): there is no weight field on `DailyCheckin` (E5·P1), so none is mapped here.
