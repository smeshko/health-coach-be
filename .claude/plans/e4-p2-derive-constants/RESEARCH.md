# Research: E4·P2 — Derive constants → profile.yaml

Curated findings only — no raw conversation transcripts. Grounds the plan in
[`epics/E04-baseline-bootstrap.md`](../../../epics/E04-baseline-bootstrap.md) (§1, §2 R2, §3 E4·P2, §4,
§6, §7), [`docs/architecture/DB.md`](../../../docs/architecture/DB.md) §5, §6 (and §0, §1 for the
`baseline.db` shape), [`docs/architecture/ARCHITECTURE.md`](../../../docs/architecture/ARCHITECTURE.md)
§3, §6, and [`HEALTH-CONSITTUTION.md`](../../../HEALTH-CONSITTUTION.md) §3, §7 (the formulas behind the
constants). Depends on the **E3·P1** `Profile` schema/validator and the **E4·P1** `baseline.db`.

## Key Files & Directories

- `scripts/derive_constants.py` — **new** (this phase): the offline derivation build step. NOT part of the
  FastAPI runtime (`app/...`). Reads the read-only `baseline.db` (E4·P1) and writes `profile.yaml`. Stamps
  `meta`. CLI with `--db`/`--out`/`--constitution-version` overrides so tests never touch the real corpus.
- `scripts/compute_zones.py` — **new** (this phase): pure function `compute_zones(max_hr, rhr) ->
  dict[str, tuple[int,int]]` returning the Z1–Z5 bpm bounds. No DB / no I/O — deterministic, unit-tested
  in isolation. Imported by `derive_constants.py` (DB.md §5 `zones` "computed by compute_zones.py").
- `app/core/profile.py` — **existing** (E3·P1): the `Profile` Pydantic model + `load_profile`. This phase
  **reuses it as the validator** — the derivation builds a section dict and constructs `Profile(**data)`
  (round-trip) so an invalid file can never be written. NOT modified here.
- `profile.yaml` — **existing** at the repo root (E3·P1 shipped the DB.md §5 example verbatim). This phase
  **overwrites** it with the derived-and-stamped output (DB.md §5/§6 — written by the bootstrap step).
- `../db/baseline.db` — the read-only corpus (E4·P1 output) in the sibling `../db/` dir. Read-only here.
- `tests/scripts/test_compute_zones.py`, `tests/scripts/test_derive_constants.py` — **new**: unit test the
  zone math (known maxHR/RHR → expected bounds) and an end-to-end derive over a tiny synthetic fixture DB.
- `tests/fixtures/baseline_small.db` (built in-test) — a tiny synthetic `baseline.db` (a handful of HR /
  HRV / RHR / running-cadence `records`) for deterministic, fast derivation tests (no big-file load).

## Architecture Facts

- **`profile.yaml` is the E3 schema** (DB.md §5): five sections — `athlete`, `thresholds`, `zones`,
  `nutrition`, `meta`. The derivation must produce a dict that passes the **E3·P1 validator** verbatim
  (epic R2, §4). The E3·P1 `Profile` constraints this output MUST satisfy (from
  `.claude/plans/e3-p1-profile-loader/`):
  - `thresholds.max_hr > thresholds.rhr_baseline` (model validator).
  - `zones` **monotonic AND contiguous**: each `zN=(low,high)` has `low < high`; lows strictly increasing;
    `z1.high == z2.low`, `z2.high == z3.low`, `z3.high == z4.low`, `z4.high == z5.low`.
  - `nutrition.deficit_pct ≤ 0.20` (hard cap, `le=`), `protein_g_per_kg ≤ 2.0` (kidney-stone cap, `le=`),
    `fat_g_per_kg_low ≤ fat_g_per_kg_high`.
  - `carbs_g_per_kg` requires all five keys `{hard_low, hard_high, moderate, rest_low, rest_high}` (no
    defaults), `extra="forbid"` on every section (a stray/renamed key fails).
  - `meta.computed_at` is typed `datetime.date` (a bare ISO date, e.g. `2026-06-02`); `derived_from` /
    `constitution_version` are `str`.
- **Zones = % of max HR** (constitution §3 "Primary anchor = % of max HR"; the bpm table is rendered from
  `profile.yaml`'s `zones`). The band edges: Z1 50–65%, Z2 65–78%, Z3 78–87%, Z4 87–92%, Z5 92–100% of
  `max_hr`. Verified against the DB.md §5 example at `max_hr=192`: `round(.50·192)=96`, `round(.65·192)=125`
  (124.8), `round(.78·192)=150` (149.76), `round(.87·192)=167` (167.04), `round(.92·192)=177` (176.64),
  `1.00·192=192` → `z1:[96,125] z2:[125,150] z3:[150,167] z4:[167,177] z5:[177,192]` — **exactly** the §5
  block. So pure %max-HR with rounding reproduces the canonical example.
- **Contiguity is structural, not luck**: `compute_zones` computes the **six band edges once**
  (`e0..e5` = round of `pct·max_hr` for `pct in [.50,.65,.78,.87,.92,1.00]`) and forms
  `z1=(e0,e1), z2=(e1,e2), …, z5=(e4,e5)`. Adjacent zones therefore **share** the same integer edge by
  construction → `zN.high == z(N+1).low` always holds, so the E3·P1 contiguity validator passes for any
  `max_hr` (DB.md §5; epic §3 E4·P2 note "contiguous/monotonic").
- **`easy_hr_cap` = Maffetone 180 − age** (constitution §3 non-negotiables; DB.md §5 comment
  `easy_hr_cap: 146  # Maffetone 180 − age`). At `age=34` → `146`. Deterministic from `athlete.age`, not
  from raw HK data.
- **`max_hr` "from observed boxing peaks"** (constitution §3 row "Max HR … from observed boxing peaks").
  Derived from the **whole corpus** (a near-stationary physiological ceiling — NOT the trailing ≈90-day
  window used for the rolling anchors, which could miss the true peak if no recent max-effort session
  exists): the bounded max of HR `records.value` where `type='HKQuantityTypeIdentifierHeartRate'`, clamped
  to a plausible exercise-HR floor/ceiling to reject artifacts.
- **`rhr_baseline`** is the **monthly anchor used to derive zones**, NOT the live readiness baseline (DB.md
  §5 footnote ¹ — readiness reads the rolling `daily_metrics` values). Derived as a robust central value
  (median) of recent `HKQuantityTypeIdentifierRestingHeartRate` records.
- **`hrv_baseline_ms`** is **informational** (DB.md §5 comment "informational; readiness uses rolling
  daily_metrics"). Derived as the median of recent `HKQuantityTypeIdentifierHeartRateVariabilitySDNN`
  records (unit ms).
- **`cadence_target_spm` / `cadence_current_spm`** (DB.md §5): target is the **END target of the ramp**;
  current is **THIS month's cue** (RecomputeConstants ramps it +5 toward target). Running cadence lives in
  `records` (DB.md §1 "running cadence & dynamics"; §1 `records.type` note "HR / speed / power / cadence").
  The **exact** HK identifier for running cadence/step-rate must be confirmed against the real corpus (E4·P1
  inspected `export.xml`/`health.db` to pin its exact types the same way) — the plan pins it as a named
  `CADENCE_TYPE` constant rather than hard-asserting a possibly-wrong `HK…Identifier`. Current = a robust
  recent median of running cadence; target = the constitution's end target (a config anchor — 172 spm in
  §5; constitution §3 prose says "Current ~155 spm" while the DB.md §5 *example* shows
  `cadence_current_spm: 160` — the plan **derives** current from the corpus so neither literal is
  hard-coded). The +5/2–3wk ramp itself is E8/§10 (out of scope here — this phase writes the first month's
  values).
- **`nutrition` block = §7 medical/config anchors, not HK-derived numbers** (DB.md §5 `nutrition` row;
  constitution §7): `activity_factor` (TDEE multiplier — "very high NEAT"), `deficit_pct` (≤0.20 cap),
  `protein_g_per_kg` (≤2.0 kidney-stone cap), `fat_g_per_kg_low/high`, the five `carbs_g_per_kg`
  multipliers, `hydration_l_low/high`, `fiber_g_low/high`. These are **clinician/constitution constants**,
  not computed from raw samples — the macro engine (E8) reads them; the deficit and protein caps are
  medical limits. The derivation carries them through from the §5 anchor values (the activity_factor may be
  informed by the corpus step-count NEAT, but its value is a config anchor, not a fitted number).
- **`athlete` block = config** (age/sex/height_cm/goal_weight_kg): not reliably present as HK samples;
  these are profile config inputs (the §5 example: 34/male/174/75). `easy_hr_cap` depends on `age`, so age
  is a required input the derivation consumes (constitution §3 Maffetone).
- **`baseline.db` raw shape** (E4·P1 RESEARCH / DB.md §1): `records(type, unit, value, value_text,
  source_name, source_version, device, creation_date, start_date, end_date)` — **no `uuid`/`origin`**, TEXT
  timestamps exactly as Apple emits (`"2016-05-18 16:45:52 +0300"`). HR/HRV/RHR/cadence are all `records`
  rows distinguished by `type`. `baseline.db` is **never opened at runtime** — only by build scripts
  (ARCHITECTURE §6) — so this script lives in `scripts/`, not `app/`.
- **Stamp `meta`** (epic R2; DB.md §5/§6): `meta.derived_from = 'baseline.db'`,
  `meta.computed_at = <today, Europe/Sofia date>`, `meta.constitution_version = 'v1'` (the rulebook version
  the constants target; CLI-overridable).

## Constraints

- **Reuse the E3·P1 validator — never re-implement it.** The derivation constructs `Profile(**data)` from
  `app.core.profile` and lets any `ValidationError` abort the write (write-after-validate). A round-trip
  test reloads the written file via `load_profile()` (epic §4 "passes E3's validator"). This is the single
  guarantee that the output is valid — the script owns no parallel validation logic.
- **Offline, not runtime.** `scripts/` only — plain `sqlite3` + stdlib + `app.core.profile` import + a YAML
  dump. No FastAPI/SQLAlchemy/Alembic. `baseline.db` is read **read-only** and never registered with
  Alembic / never opened by `app/` (DB.md §0, §6; ARCHITECTURE §6).
- **Deterministic.** Same `baseline.db` + same `computed_at` → byte-identical `profile.yaml` (epic §1 §6
  "deterministic computations"). `computed_at` is the only nondeterministic input → CLI-injectable for
  tests so the rest is reproducible.
- **Caps respected at derivation, re-checked by the validator** (epic R2): `deficit_pct ≤ 0.20`,
  `protein_g_per_kg ≤ 2.0`. The derivation clamps to the anchor (well inside), and the `Profile` validator
  is the hard backstop — a bad value would raise before write.
- **Zones contiguous + monotonic by construction** (shared integer edges), so they always pass the E3·P1
  validator regardless of `max_hr` (epic §3 E4·P2).
- **No big-file dependency in tests.** Tests build a tiny synthetic `baseline.db` in `tmp_path`; the real
  `../db/baseline.db` is never read by CI.
- **Period key via `Europe/Sofia` tz** (DB.md §0): `computed_at` is "today" in `Europe/Sofia`
  (`zoneinfo`), never a fixed UTC offset.

## Useful Commands

```bash
# derive (offline, manual) — reads ../db/baseline.db, writes ./profile.yaml
uv run python scripts/derive_constants.py                       # default paths
uv run python scripts/derive_constants.py --db <in.db> --out <out.yaml> --computed-at 2026-06-02

# lint + tests (fixture-only; no big-file load)
uv run ruff check .
uv run pytest tests/scripts/test_compute_zones.py tests/scripts/test_derive_constants.py

# prove the runtime never opens baseline.db (only build scripts do)
grep -REn "baseline\.db" app && echo LEAK || echo clean

# prove the written profile re-validates via the E3·P1 loader
uv run python -c "from app.core.profile import load_profile; load_profile('profile.yaml'); print('valid')"
```

## Uncertainty

- **Zones: %max-HR vs Karvonen (HR-reserve, uses RHR).** The DB.md §5 example is **pure %max** (verified
  above — Karvonen would NOT reproduce `[96,125]…[177,192]`), and constitution §3 states the primary anchor
  is "% of max HR". **Resolved:** `compute_zones(max_hr, rhr)` derives the bpm cutpoints from **%max-HR**;
  `rhr` is accepted in the signature (the §5 `zones` block is conceptually a max/RHR pair and
  RecomputeConstants re-derives from both) but does not move the cutpoints in the §5-faithful derivation.
  Documented as a Decision so a reviewer doesn't expect Karvonen.
- **Which constants are HK-derived vs config anchors.** **Resolved:** `max_hr`, `rhr_baseline`,
  `hrv_baseline_ms`, `cadence_current_spm` come from `baseline.db` records; `easy_hr_cap` is computed
  (Maffetone) from `age`; `cadence_target_spm`, the whole `nutrition` block, and the `athlete` block are
  **config anchors** (medical/clinician constants and profile inputs) carried through from the §5 values —
  the macro engine reads them; they are not fitted from raw samples (DB.md §5 `nutrition` row;
  constitution §7). The athlete/config anchors are injectable so a real deploy supplies the true age etc.
- **`max_hr` estimator robustness.** A single spurious HR spike could inflate `max_hr`. **Resolved:** the
  pinned behaviour is the **bounded max** over plausibly-bounded exercise-HR samples (drop values > a
  physiological ceiling and < a floor) so one artifact doesn't dominate; the test fixture includes an
  out-of-range spike and pins the expected (in-window) max. A high percentile of the in-window samples is an
  acceptable extra-robust variant, but the test asserts the bounded max so the estimator is unambiguous.
- **"Recent" window for the central-value anchors.** `rhr_baseline`/`hrv_baseline_ms`/`cadence_current_spm`
  are *monthly* anchors over a 7-year corpus — "recent" must be a defined window, not the lifetime mean.
  **Resolved:** compute them over the **trailing ≈90 days from the latest sample** (a named `RECENT_DAYS`
  constant; matches the seed-window / monthly-anchor intent of DB.md §5/§6), so the result is a *current*
  anchor and deterministic for a fixed corpus; the fixture pins which rows fall inside the window.
- **Exact HK cadence record `type`.** HealthKit's running-cadence/step-rate identifier varies by export
  version and isn't a single obvious first-class quantity type. **Resolved:** the plan does not hard-assert
  a specific `HK…Identifier`; it pins a named `CADENCE_TYPE` constant to be confirmed against the real
  `baseline.db`/`export.xml` (as E4·P1 confirmed its own types from the corpus). The derivation logic and
  tests are agnostic to the exact string (the fixture inserts rows under whatever `CADENCE_TYPE` is set).
- **Default `--db` / `--out` paths.** **Resolved:** default `--db` = sibling `../db/baseline.db` (E4·P1
  output, DB.md §6); default `--out` = repo-root `./profile.yaml` (the E3·P1 `PROFILE_PATH`); both
  CLI-overridable so tests use `tmp_path`.

## References

- `epics/E04-baseline-bootstrap.md` §1, §2 (R2), §3 (E4·P2), §4, §6, §7
- `docs/architecture/DB.md` §5 (the `profile.yaml` five-section block + the static-vs-live split + the
  `zones`/`nutrition`/`meta` field lists and caps), §6 (bootstrap write paths: derive constants →
  `profile.yaml`), §0/§1 (`baseline.db` raw shape, TEXT timestamps, Europe/Sofia period keys)
- `docs/architecture/ARCHITECTURE.md` §3 (Bootstrap), §6 (deterministic computations; `baseline.db` is a
  build input, never opened at runtime)
- `HEALTH-CONSITTUTION.md` §3 (HR zones = %max; Maffetone easy cap; cadence ramp), §7 (nutrition
  constants: activity_factor / deficit_pct / protein-fat g/kg / carb multipliers / hydration / fiber)
- `.claude/plans/e3-p1-profile-loader/` (the `Profile` schema + validators this output must pass) and
  `.claude/plans/e4-p1-build-db-etl/` (the `baseline.db` raw schema this derivation reads)
