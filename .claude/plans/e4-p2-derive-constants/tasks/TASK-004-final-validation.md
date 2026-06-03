# TASK-004: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for e4-p2-derive-constants`

## Goal

Confirm the plan is fully implemented and every PLAN.md acceptance criterion is met by a concrete,
non-circular check (named command/test) on the Python/uv stack.

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked (TASK-001…003).
- [ ] **Lint**: `uv run ruff check .` passes with no issues.
- [ ] **Tests**: `uv run pytest tests/scripts/test_compute_zones.py tests/scripts/test_derive_constants.py`
      passes.

### Acceptance-criteria checks (1:1 with PLAN.md)

- [ ] **Zones match the §5 example** → `uv run pytest tests/scripts/test_compute_zones.py -k "db_md_example
      or known_bounds"` passes (asserts `compute_zones(192,58) == {"z1":(96,125),…,"z5":(177,192)}`).
- [ ] **Zones contiguous + monotonic for any maxHR** → `uv run pytest tests/scripts/test_compute_zones.py
      -k "contiguous or monotonic"` passes (asserts `zN.high == z(N+1).low`, `low<high`, lows increasing
      across several `max_hr`). Cross-check: `uv run python -c "from scripts.compute_zones import
      compute_zones; z=compute_zones(200,55); assert all(z[f'z{i}'][1]==z[f'z{i+1}'][0] for i in range(1,5)), z"`.
- [ ] **Generated profile.yaml round-trips through E3·P1** → `uv run pytest tests/scripts/test_derive_constants.py
      -k "round_trip or load_profile"` passes (derive over synthetic DB → `load_profile(out)` returns a
      `Profile`). Manual: `uv run python scripts/derive_constants.py --db <fixture.db> --out /tmp/p.yaml
      --computed-at 2026-06-02 && uv run python -c "from app.core.profile import load_profile;
      load_profile('/tmp/p.yaml'); print('valid')"`.
- [ ] **meta stamped** → `uv run pytest tests/scripts/test_derive_constants.py -k "meta or stamp"` passes
      (asserts `derived_from=='baseline.db'`, `computed_at==<injected>`, `constitution_version=='v1'`).
- [ ] **easy_hr_cap = 180 − age** → `uv run pytest tests/scripts/test_derive_constants.py -k "easy_hr_cap
      or maffetone"` passes (`easy_hr_cap == 146` at age 34).
- [ ] **Data-derived thresholds match fixture + spike excluded** → `uv run pytest
      tests/scripts/test_derive_constants.py -k "derive_max_hr or thresholds or spike"` passes (pinned
      max_hr/rhr/hrv/cadence; the out-of-range HR spike is excluded from max_hr).
- [ ] **Caps respected / backstop** → `uv run pytest tests/scripts/test_derive_constants.py -k "cap"`
      passes (derived `deficit_pct ≤ 0.20`, `protein_g_per_kg ≤ 2.0`; an over-cap anchor raises
      `ValidationError` and writes no file).
- [ ] **Determinism** → `uv run pytest tests/scripts/test_derive_constants.py -k "determinis"` passes (two
      runs, same `--computed-at`, byte-identical output). Manual: run the derivation twice to two paths and
      `diff` them — identical.
- [ ] **Offline-only** → `grep -REn "baseline\.db" app` returns no hits (the corpus is never opened by
      runtime code; only `scripts/` reads it). `scripts/derive_constants.py` imports only `app.core.profile`
      from `app/` (the validator), nothing else.
- [ ] `PLAN.md` acceptance criteria all met (each mapped above to a concrete check, not "all met").
