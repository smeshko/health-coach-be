# TASK-003: Write valid profile.yaml and stamp meta

Depends on: TASK-002
Suggested commit: `feat(scripts): validate-and-write profile.yaml with stamped meta`

## Goal

Stamp `meta`, **validate the assembled dict via the E3·P1 `Profile`**, and write `profile.yaml` (the CLI
entrypoint) — so the bootstrap produces a file that round-trips through `app.core.profile.load_profile()`,
deterministically.

## Files

- `scripts/derive_constants.py` — **extend** TASK-002 with the stamp / validate / write / CLI:
  - **Stamp `meta`**: `meta = {"derived_from": "baseline.db", "computed_at": <date>,
    "constitution_version": <str>}` where `computed_at` defaults to **today in `Europe/Sofia`**
    (`datetime.now(ZoneInfo("Europe/Sofia")).date()`) and is overridable; `constitution_version` defaults
    to `"v1"` (DB.md §5/§6; epic R2).
  - **Validate-before-write**: `build_profile(con, config) -> Profile` — call `derive_constants`, attach
    `meta`, then construct `Profile(**data)` from `app.core.profile`. Any `pydantic.ValidationError`
    propagates (the write is aborted) — this is the single guarantee the output passes "E3's validator".
  - **Write**: `write_profile(profile: Profile, out_path: Path) -> None` — `yaml.safe_dump` the section
    dict in DB.md §5 order (`athlete`, `thresholds`, `zones`, `nutrition`, `meta`) with stable key order
    (`sort_keys=False`) and `computed_at` rendered as a bare ISO date string. Write once (atomically) — no
    partial file on failure.
  - **CLI** `main(argv)`: `--db` (default `../db/baseline.db`), `--out` (default repo-root `profile.yaml`
    = the E3·P1 `PROFILE_PATH`), `--computed-at` (ISO date; default = today Europe/Sofia),
    `--constitution-version` (default `v1`), plus optional athlete/anchor overrides. Open the DB read-only.
- `tests/scripts/test_derive_constants.py` — **extend** with the round-trip / stamp / caps-raise /
  determinism tests.

## Acceptance

- [ ] **Round-trip**: running the derivation over a synthetic `baseline.db` writes a `profile.yaml` that
      `app.core.profile.load_profile(<out>)` loads into a `Profile` with no error.
- [ ] **Meta stamped**: the loaded `Profile` has `meta.derived_from == "baseline.db"`,
      `meta.computed_at == date.fromisoformat(<injected --computed-at>)` (E3·P1 types it as
      `datetime.date`, so the test compares against the **parsed `date`**, not the raw string), and
      `meta.constitution_version == "v1"` (or the injected version).
- [ ] **Caps backstop**: with an over-cap anchor (`deficit_pct = 0.25` or `protein_g_per_kg = 2.5`),
      `build_profile`/`main` raises `pydantic.ValidationError` and **no** file is written.
- [ ] **max_hr ≤ rhr guard**: a fixture whose RHR ≥ derived `max_hr` makes `build_profile` raise (the
      E3·P1 `Thresholds` validator), not write a broken file.
- [ ] **Determinism**: two runs with the same `--db` and same `--computed-at` produce byte-identical
      `profile.yaml`.
- [ ] **Defaults sane**: `--out` defaults to the repo-root `profile.yaml`; `--db` to `../db/baseline.db`;
      DB opened read-only.

## Steps

### RED
- [ ] `tests/scripts/test_derive_constants.py`: add tests that call `main([...])` (or `build_profile` +
      `write_profile`) over `_make_baseline_db(...)`, then `load_profile(out)` and assert the stamped meta +
      caps; a caps-over-anchor test asserting `ValidationError` + no file written; a max_hr≤rhr fixture test;
      a determinism test diffing two runs' bytes.

### GREEN
- [ ] Implement `build_profile` (validate via `Profile`), `write_profile` (`yaml.safe_dump`, §5 order),
      `meta` stamping, and `main`/argparse. Smallest code that passes.

### REFACTOR
- [ ] Render the `Profile` back to a plain dict for dumping via `profile.model_dump(mode="json")` (so
      `computed_at` serializes as an ISO string) reordered to §5 section order; write to a temp file then
      `os.replace` for atomicity. Keep `app.core.profile` the **only** `app/` import.

## Notes

This is where the plan's correctness guarantee lives: **validate (construct `Profile`) BEFORE writing**, so
an invalid derivation aborts instead of emitting a bad `profile.yaml`. The round-trip test (`load_profile`
on the written file) is the literal check of epic §4 "passes E3's validator". `computed_at` is the only
nondeterministic input → inject it via `--computed-at` so two runs match byte-for-byte; derive its default
from `Europe/Sofia` (DB.md §0), never a hard-coded offset. The written file replaces the E3·P1 example
`profile.yaml` at the repo root (the bootstrap output; DB.md §5/§6).
