# TASK-001: Add measured_max_hr(session, as_of, current_max_hr) query fn + unit tests

Depends on: None
Suggested commit: `feat(recompute): runtime measured max-HR anchor source`

## Goal

Add `measured_max_hr(session, as_of, current_max_hr)` to `app/services/recompute.py` — a
SQLAlchemy port of the offline `derive_max_hr`: a whole-corpus bounded MAX over both HR
type aliases, physiologically clamped, cut off at `as_of` (conservative-inclusive,
device-local-date bound — see R3), and ratcheted so it never drops below `current_max_hr`.

## Files

- `app/services/recompute.py` — add module-level HR constants (`_HR_FLOOR = 80.0`,
  `_HR_CEILING = 205.0`, mirrored from `scripts/derive_constants.py` with a citing
  comment) and `measured_max_hr(session, as_of, current_max_hr)`; import
  `RECORD_TYPE_TO_HK` from `app.core.healthkit`, `Records` from `app.database.models`, and
  `func`/`select` from `sqlalchemy`. The `as_of` cutoff needs only `datetime.timedelta` on
  the passed-in `date` (`(as_of + 1 day).isoformat()`) — NO `app.core.time` tz helper, since
  the bound is device-local-date, not Sofia (R3).
- `tests/services/test_recompute.py` — add a `measured_max_hr` unit-test block using the
  `session` fixture from `tests/services/conftest.py` (all behavioural cases EXCEPT the
  offline-constant parity assertion).
- `tests/scripts/test_derive_constants.py` — add the `_HR_FLOOR`/`_HR_CEILING` parity
  assertion HERE, not in `tests/services/`: this dir's `conftest.py` already provides the
  `derive_constants` fixture and the `sys.path.insert(0, scripts/)` the offline module needs
  (pytest fixtures are directory-scoped; neither is visible to `tests/services/`). Import the
  app-side constants from `app.services.recompute`. (PLAN D4.)

## Acceptance

- [ ] `measured_max_hr` returns the bounded, aliased, corpus-wide MAX ratcheted to
      `>= current_max_hr`, with the `as_of` cutoff applied as a conservative-inclusive
      device-local-date bound.
- [ ] Unit tests cover: corpus-wide peak (not windowed), physiological clamp (both a
      below-`_HR_FLOOR` and an above-`_HR_CEILING` artifact excluded), dual alias (peak in
      the HK-identifier origin AND peak in the `heart_rate` origin), `as_of` boundary — TWO
      assertions: (a) an in-week peak at a non-UTC offset straddling the cutoff is NEVER
      dropped (conservative-inclusive; R3), and (b) a HIGHER peak dated well AFTER the `as_of`
      window (far-future) IS excluded from the result (guards the `start_date < bound`
      clause), ratchet floor (quiet corpus ⇒ `current_max_hr`), and empty corpus ⇒
      `current_max_hr` (no raise).
      Plus, in `tests/scripts/` (see Files / PLAN D4), a parity assertion that the app-side
      `_HR_FLOOR`/`_HR_CEILING` equal the offline `derive_constants` `HR_FLOOR`/`HR_CEILING`.

Evidence: `uv run pytest tests/services/test_recompute.py -k measured_max_hr` output
showing all new behavioural cases green, PLUS `uv run pytest tests/scripts/test_derive_constants.py`
showing the D4 `_HR_FLOOR`/`_HR_CEILING` parity assertion green (it lives there, not in
`tests/services/`, so the `-k measured_max_hr` run above does not exercise it).

## Steps

### RED
- [ ] In `tests/services/test_recompute.py`, add tests seeding `Records` rows (both
      `type="heart_rate"` and `type="HKQuantityTypeIdentifierHeartRate"`) via the
      `session` fixture and asserting `measured_max_hr(...)` for each property above.
      Import `measured_max_hr` (does not yet exist → RED).
- [ ] In `tests/scripts/test_derive_constants.py` (where the `derive_constants` fixture +
      `scripts/` sys.path already exist), add the parity test: import `_HR_FLOOR`/`_HR_CEILING`
      from `app.services.recompute` and assert they equal the offline module's
      `HR_FLOOR`/`HR_CEILING`. Do NOT try to reuse that fixture from `tests/services/` — it is
      not in scope there.

### GREEN
- [ ] Implement `measured_max_hr(session, as_of, current_max_hr)`:
      - Build the alias set: `{"heart_rate", RECORD_TYPE_TO_HK["heart_rate"]}`.
      - `select(func.max(Records.value)).where(Records.type.in_(aliases))
        .where(Records.value >= _HR_FLOOR).where(Records.value <= _HR_CEILING)
        .where(Records.start_date < <as_of upper bound>)`.
      - Compute the `as_of` upper bound as a single lexical ISO date-prefix string
        `(as_of + 1 day).isoformat()` — conservative-inclusive so an in-week peak is never
        dropped. Do NOT re-narrow in Python (a `func.max()` aggregate can't), and do NOT
        widen ±1 day in both directions like `_window` (that convention is only sound because
        `_window` re-filters by Sofia date in Python afterwards). The bound is
        device-local-date precise (R3); the TEXT `start_date < bound` comparison stays
        index-friendly on the `(type, start_date)` / `start_date` indexes.
      - `raw = session.execute(stmt).scalar_one_or_none()`; if `None` (empty/thin
        corpus) return `current_max_hr`; else `return max(current_max_hr,
        int(round(raw)))`.

### REFACTOR
- [ ] Docstring citing `scripts/derive_constants.py:derive_max_hr` (§ parity) and the
      NOT-date-windowed / ratchet-up rationale; keep the signature keyword-friendly to
      match `rederive_zones` house style.
- [ ] Update the `app/services/recompute.py` MODULE docstring: it currently opens
      "Pure: … no DB persistence" — `measured_max_hr` adds a read-only `session`-scoped
      `func.max` query (plus `sqlalchemy` + `app.database.models` imports), so reword the
      header to note the module now hosts one read-only records query alongside the pure
      helpers (still no writes, no `profile.yaml`).

## Notes

- Do NOT import from `scripts/derive_constants.py` at runtime (bare `from compute_zones
  import` on its L37; no `scripts/__init__.py`). Mirror constants app-side — the parity
  test is the drift guard (PLAN D4 / R1).
- The ratchet clamp lives INSIDE this function (D2), so `rederive_zones`'s
  `ANCHOR_MIN_DELTA_BPM` gate can only fire on an upward move.
