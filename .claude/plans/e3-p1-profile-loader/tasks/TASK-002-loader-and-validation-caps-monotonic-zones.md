# TASK-002: Loader and validation (caps, monotonic zones)

Depends on: TASK-001
Suggested commit: `feat(core): add profile.yaml loader and constant validation`

## Goal

Add the YAML loader (`load_profile`) and the validators that enforce DB.md §5's constraints — deficit ≤
0.20, protein ≤ 2.0, fat low ≤ high, max_hr > rhr, and zone bounds monotonic **and** contiguous — so a bad
file fails loudly at load with a clear, field-named error.

## Files

- `app/core/profile.py` — extend TASK-001's models with validators and add the loader:
  - `Zones`: a `@model_validator(mode="after")` asserting, for each `zN=(low, high)`: `low < high`; lows
    strictly increasing (`z1.low < z2.low < … < z5.low`); and **contiguity** `z1.high == z2.low`,
    `z2.high == z3.low`, `z3.high == z4.low`, `z4.high == z5.low`. Raise `ValueError` with a message naming
    the offending boundary (Pydantic wraps it into `ValidationError`).
  - `Nutrition`: field constraints `deficit_pct: float = Field(le=0.20)` and
    `protein_g_per_kg: float = Field(le=2.0)` (or a `@field_validator`), plus a
    `@model_validator(mode="after")` asserting `fat_g_per_kg_low <= fat_g_per_kg_high`.
  - `Thresholds`: a `@model_validator(mode="after")` asserting `max_hr > rhr_baseline`.
  - `load_profile(path: Path | None = None) -> Profile` — module-level: resolve `path` (default =
    `PROFILE_PATH`, an app/repo-root anchor; overridable by argument), `yaml.safe_load` the file, construct
    `Profile(**data)`. Let `pydantic.ValidationError` propagate; raise a clear `FileNotFoundError` when the
    path is missing and wrap a YAML parse error with a readable message. Define `PROFILE_PATH` as a
    module-level `Path` resolved from a package anchor (e.g. `Path(__file__).resolve().parents[2] /
    "profile.yaml"`), not cwd-relative.
- `tests/core/test_profile.py` — extend with loader + validation negative cases (write temp yaml files).

## Acceptance

- [ ] `load_profile(<valid temp yaml>)` returns a `Profile`; values match the file.
- [ ] `load_profile(<missing path>)` raises a clear `FileNotFoundError`.
- [ ] `deficit_pct = 0.25` → `ValidationError` naming `deficit_pct` / the 0.20 cap; `0.20` is accepted
      (boundary inclusive).
- [ ] `protein_g_per_kg = 2.5` → `ValidationError` naming `protein_g_per_kg`; `2.0` accepted.
- [ ] Non-monotonic zones (a `zN.low >= zN.high`, or lows not strictly increasing) → `ValidationError`.
- [ ] Non-contiguous zones (`z1 = [96, 124]`, `z2 = [125, 150]` → `z1.high != z2.low`) → `ValidationError`.
- [ ] `fat_g_per_kg_low = 1.2`, `fat_g_per_kg_high = 1.0` → `ValidationError`.
- [ ] `max_hr = 50`, `rhr_baseline = 58` (max_hr ≤ rhr) → `ValidationError`.

## Steps

### RED
- [ ] `tests/core/test_profile.py`: add a `write_yaml(tmp_path, overrides)` helper that dumps the valid
      §5 dict with targeted mutations; one negative test per rule above asserting `ValidationError` (and the
      boundary-accepted cases for the `≤` caps), plus the valid-load and missing-file cases.

### GREEN
- [ ] Add the `Zones`/`Nutrition`/`Thresholds` validators and `load_profile` + `PROFILE_PATH` to
      `app/core/profile.py`. Smallest logic that passes; messages name the field/boundary.

### REFACTOR
- [ ] Prefer declarative `Field(le=...)` for the simple caps; reserve `@model_validator` for cross-field
      (fat low≤high, max_hr>rhr) and zone monotonicity/contiguity. Use `yaml.safe_load` (never `load`).

## Notes

Caps are inclusive (`≤ 0.20`, `≤ 2.0`) — the example uses `0.12` / `1.8`, well inside, but the boundary
values must be accepted, so use `le=` not `lt=`. Zones must be **both** monotonic and contiguous: a
monotonic-but-gapped set must be rejected (DB.md §5 example is exactly contiguous —
`z1:[96,125] z2:[125,150] z3:[150,167] z4:[167,177] z5:[177,192]`). Resolve `PROFILE_PATH` from a package
anchor, not cwd, so the default works under pytest and at runtime.
