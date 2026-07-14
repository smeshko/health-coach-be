# Research: Runtime measured max-HR anchor source (Phase 19.6)

Curated findings only — no raw conversation transcripts. Every pointer below was
verified against the worktree at plan-authoring time.

## Key Files & Directories

- `app/services/recompute.py` — home of `rederive_zones`, `ZoneRederivation`,
  `ANCHOR_MIN_DELTA_BPM` (~L252-299); imports `from scripts.compute_zones import
  compute_zones` (L33). Chosen home for `measured_max_hr` (D1).
- `app/core/weekly_planner.py` — `RecomputeConstants.process` (~L298-368). Injection
  point at L329-337: `rederive_zones(current_max_hr=…, new_max_hr=profile.thresholds.max_hr, …)`.
  `session = _session_of(task_context)` at L299 is in scope; `_session_of` reads
  `task_context.metadata["session"]` (L114-125). Merge logic L339-368 is
  correct-when-reachable (Phase 19.4) — do NOT touch.
- `app/database/models/records.py` — `class Records`, `__tablename__ = "records"`.
  Columns: `type: Text NOT NULL`, `value: Float NULLABLE`, `start_date: Text NOT NULL`
  (ISO-8601 TEXT, device offset preserved verbatim — NOT a `DateTime`). Index on
  `(type, start_date)` and on `start_date`.
- `app/core/healthkit.py` — `RECORD_TYPE_TO_HK` (L89-115): the wire↔HK bridge, single
  source of truth for the dual alias. `RECORD_TYPE_TO_HK["heart_rate"] ==
  "HKQuantityTypeIdentifierHeartRate"`.
- `app/core/time.py` — `SOFIA = ZoneInfo("Europe/Sofia")` (L16), `parse_ts` (L40,
  offset-aware, raises on naive), `to_sofia` (L74). NB: `measured_max_hr`'s `as_of` cutoff
  does NOT use these — validation chose a device-local-date, conservative-inclusive lexical
  bound (`start_date < (as_of + 1 day)`) rather than a Sofia-precise one, because a single
  `func.max()` can't re-narrow in Python (see PLAN R3 / D-note below).
- `scripts/derive_constants.py` — OFFLINE reference. `derive_max_hr(con)` (L141-152):
  `SELECT MAX(value) FROM records WHERE type = ? AND value >= ? AND value <= ?` over the
  WHOLE corpus (docstring: "NOT date-windowed — a recent window could miss the true
  peak"), raises `ValueError` on empty. Constants: `HR_TYPE =
  "HKQuantityTypeIdentifierHeartRate"` (L52), `HR_FLOOR = 80.0` (L67), `HR_CEILING =
  205.0` (L68), `_TS_FORMAT = "%Y-%m-%d %H:%M:%S %z"` (L76).
- `scripts/compute_zones.py` — `compute_zones(max_hr, rhr) -> dict[str, tuple[int,int]]`
  (L19); `%max` cutpoints, `z5.high == max_hr`. Reused by `rederive_zones`.

## Architecture Facts

- **Dual HR type-alias is real and load-bearing.** Live `/sync` rows store the
  snake_case wire value: `app/services/record_upsert.py:_to_row` sets `"type":
  record.type.value` (e.g. `heart_rate`). The offline E4 seed copies Apple-Health rows
  verbatim, so seeded `records.type` is the HK identifier
  `HKQuantityTypeIdentifierHeartRate`. `daily_metrics_engine` already reconciles both at
  read time — see `_HK_TO_SNAKE_RECORD_TYPE`, `_canonical_record_type`, and especially
  `_record_type_aliases(types)` (expands a snake set to include the HK form for a single
  index-backed `Records.type.in_(...)`). `measured_max_hr` must match BOTH; derive the
  alias set from `RECORD_TYPE_TO_HK` the same way.
- **`records.start_date` is TEXT, queried lexically.** `daily_metrics_engine._window(day)`
  (~L159-166) builds a ±1-day ISO date-prefix range so `start_date >= lo AND start_date
  < hi` uses the `(type, start_date)` index; the precise Sofia-date filter then runs in
  **Python**. **Validation decision (R3):** `measured_max_hr` deliberately does NOT follow
  this widen-then-Python-narrow convention — a single `func.max()` aggregate can't re-filter
  in Python. Instead it uses ONE conservative-inclusive upper bound
  (`start_date < (as_of + 1 day)` prefix): device-local-date precise, never drops an in-week
  peak, may include a near-future row within ~1 day (immaterial for an up-only whole-corpus
  ceiling; production carries no future HR).
- **Session ownership.** The endpoint injects an open `Session` into
  `task_context.metadata["session"]`; nodes read it via `_session_of` and never open
  their own. The caller owns the transaction (tests commit explicitly).
- **Ratchet + gate interaction.** `rederive_zones` treats an anchor as moved only when
  `abs(new - current) >= ANCHOR_MIN_DELTA_BPM` (=1). If `measured_max_hr` ratchets to
  `>= current`, the gate can only ever fire on an upward move.

## Constraints

- Runtime code must never open `baseline.db` (ARCHITECTURE §6) and must not crash a
  weekly brief on a thin/empty corpus (⇒ D3: empty ⇒ return `current_max_hr`).
- Do not import `scripts/derive_constants.py` from `app/`: its L37 `from compute_zones
  import compute_zones` is a bare import and `scripts/` has no `__init__.py`. Mirror the
  physiological constants app-side (D4) instead.
- Physiological safety only — no PII/security concern (self-hosted single-user app).

## Useful Commands

```bash
uv run pytest tests/services/test_recompute.py tests/core/test_weekly_planner.py
uv run pytest            # full suite
uv run ruff check
```

## Test Conventions

- `tests/services/conftest.py` provides a `session` fixture: a migrated temp-file
  `app.db` (real Alembic schema, WAL + FK on) via `make_engine`.
- Record-seed style (`tests/services/test_daily_metrics_engine.py` ~L218-240): build
  `Records(type=…, start_date=…, end_date=…, value=…, origin=…)`, `session.add`,
  `session.commit`.
- `tests/services/test_recompute.py` imports helpers from `app.services.recompute`
  (`rederive_zones`, `ZoneRederivation`, `compute_zones`) — the natural home for the new
  unit tests.
- Weekly-planner node tests (`tests/core/test_weekly_planner.py`) drive nodes through a
  `TaskContext(event=…, metadata={"session": session})` and seed via `session.add`.
- Offline constant parity: `tests/scripts/test_derive_constants.py` loads the
  `derive_constants` module via a fixture (module has no package import path) — reuse
  that loading pattern for the D4 parity assertion.

## Uncertainty

- Whether to import `HR_FLOOR`/`HR_CEILING` from the offline module — resolved (D4): no,
  define app-side + parity-test, because the offline module isn't cleanly importable
  from `app/`.

## References

- Epic 19 spec (iOS repo): `docs/artifacts/epics/19-trustworthy-numbers.md`, Phase 19.6.
- Phase 19.4 plan (archived) — established the correct-when-reachable merge and the
  standalone-plan header convention this plan mirrors.
