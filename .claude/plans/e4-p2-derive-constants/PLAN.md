# Plan: E4·P2 — Derive constants → profile.yaml

Status: draft
Risk: medium
Created: 2026-06-03

> Epic **E4 — Baseline ETL & Bootstrap**, phase **P2**. Source of truth:
> [`epics/E04-baseline-bootstrap.md`](../../../epics/E04-baseline-bootstrap.md) (§1, §2 R2, §3 E4·P2, §4,
> §6, §7) · grounded in [`docs/architecture/DB.md`](../../../docs/architecture/DB.md) §5 (the `profile.yaml`
> five-section block — `athlete`/`thresholds`/`zones`/`nutrition`/`meta`, every field, the caps, the
> static-vs-live split + footnote ¹) and §6 (bootstrap: *derive constants → `profile.yaml`*) and §0/§1
> (`baseline.db` raw shape, TEXT timestamps, Europe/Sofia period keys),
> [`docs/architecture/ARCHITECTURE.md`](../../../docs/architecture/ARCHITECTURE.md) §3 (Bootstrap) + §6
> (deterministic computations; `baseline.db` never opened at runtime), and
> [`HEALTH-CONSITTUTION.md`](../../../HEALTH-CONSITTUTION.md) §3 (zones = %max-HR; Maffetone easy cap;
> cadence ramp) + §7 (the nutrition constants). Curated findings in
> [`RESEARCH.md`](./RESEARCH.md). **Depends on E3·P1** (`app.core.profile` — the `Profile` schema/validator
> this output must pass) and **E4·P1** (`baseline.db` — the corpus this reads).

## Goal

An offline build step (`scripts/derive_constants.py` + `scripts/compute_zones.py`) that reads the read-only
`baseline.db` (E4·P1), derives the athlete / threshold / zone / nutrition constants, and writes a
`profile.yaml` that **passes the E3·P1 `Profile` validator** verbatim, with `meta` stamped.

## Scope

- **`scripts/compute_zones.py`** — a pure, I/O-free function `compute_zones(max_hr: int, rhr: int) ->
  dict[str, tuple[int, int]]` returning `{"z1": (lo, hi), …, "z5": (lo, hi)}`. Zones are **% of `max_hr`**
  (constitution §3): band edges at `[.50, .65, .78, .87, .92, 1.00]·max_hr`, **rounded once to the six
  shared integer edges** `e0..e5`, then `z1=(e0,e1) … z5=(e4,e5)` so adjacent zones **share** an edge →
  **contiguous + monotonic by construction** (passes the E3·P1 zone validator for any `max_hr`). `rhr` is
  in the signature (the §5 `zones` is conceptually a max/RHR pair) but does not move the %max cutpoints.
- **`scripts/derive_constants.py`** — the derivation build step (offline, `scripts/`, not `app/`):
  - Opens `baseline.db` **read-only** (default `../db/baseline.db`; `--db` override).
  - **Data-derived thresholds** from `records` (by `type`): `max_hr` = robust high percentile / max of
    plausibly-bounded `…HeartRate` samples ("observed boxing peaks", constitution §3); `rhr_baseline` =
    median of recent `…RestingHeartRate`; `hrv_baseline_ms` = median of recent
    `…HeartRateVariabilitySDNN` (ms); `cadence_current_spm` = robust recent running-cadence average.
  - **Computed threshold**: `easy_hr_cap = 180 − age` (Maffetone, constitution §3).
  - **Config anchors carried through** (DB.md §5 / constitution §7 — clinician/profile constants, not
    fitted from samples): the `athlete` block (age/sex/height_cm/goal_weight_kg), `cadence_target_spm`
    (ramp END target), and the entire `nutrition` block (activity_factor, deficit_pct, protein/fat g/kg,
    the five carb multipliers, hydration, fiber). Defaults match the DB.md §5 anchors; injectable via a
    small config so a real deploy supplies the true age etc.
  - **Validate-before-write**: assemble the five-section dict, call `compute_zones`, construct
    `Profile(**data)` from `app.core.profile` (the E3·P1 validator) — any `ValidationError` aborts the
    write. Respect the caps (`deficit_pct ≤ 0.20`, `protein_g_per_kg ≤ 2.0`); the `Profile` validator is
    the hard backstop.
  - **Stamp `meta`**: `derived_from = 'baseline.db'`, `computed_at = <today, Europe/Sofia date>`
    (`zoneinfo`; `--computed-at` override for deterministic tests), `constitution_version = 'v1'`
    (`--constitution-version` override).
  - **Write `profile.yaml`** (default repo-root `./profile.yaml` = the E3·P1 `PROFILE_PATH`; `--out`
    override) via `yaml.safe_dump` with the section order preserved.
- **`tests/scripts/test_compute_zones.py`** — `compute_zones(192, 58)` returns the DB.md §5 bounds exactly
  (`z1=(96,125) … z5=(177,192)`); a second `max_hr` is contiguous + monotonic (each `high == next low`,
  lows strictly increasing); edge invariants hold for a range of `max_hr` values.
- **`tests/scripts/test_derive_constants.py`** — build a tiny synthetic `baseline.db` in `tmp_path` (a
  handful of HR / RHR / HRV / running-cadence `records`), run the derivation, then: the written
  `profile.yaml` **loads + validates** via the E3·P1 `load_profile()` (round-trip); `meta` is stamped
  (`derived_from == 'baseline.db'`, `computed_at == <injected date>`, `constitution_version` set); caps
  respected; `easy_hr_cap == 180 − age`; the derived `max_hr/rhr/hrv/cadence` match the fixture's expected
  values; same inputs + same `computed_at` → identical bytes (determinism).

## Out of Scope

- **Building `baseline.db`** — the `export.xml` → `baseline.db` ETL is **E4·P1** (`build_db.py`); this
  phase only *reads* the corpus (epic §3 E4·P1).
- **The `Profile` schema / loader / validator itself** — owned by **E3·P1** (`app/core/profile.py`); this
  phase **reuses** it as the validator and does not modify it (epic §3 E3·P1; this plan's Decisions).
- **The 90-day seed + seed↔sync reconciliation** — copying trailing samples into `app.db` with
  `origin='seed'` and the reconciliation are **E4·P3** (epic §3 E4·P3, R3/R5).
- **The monthly `RecomputeConstants` rewrite + the cadence +5/2–3wk ramp logic** — re-deriving / ramping
  the constants monthly is **E8·P5 / §10**; this phase writes only the **first month's** values (DB.md §5
  cadence note; constitution §10).
- **Consuming the constants** — the macro/TDEE engine and HR-zone bucketing (E8) and the constitution
  render (E3·P2 / E9) are downstream readers; this phase only *produces* the file (DB.md §5 "the macro
  engine reads these"; LLM.md §2).
- **`daily_metrics` / live-derived values** — current weight, 30d HRV/RHR rolling baselines, per-day
  metrics live in the DB and are **not** written to `profile.yaml` (DB.md §5 table + ¹; the E3·P1
  static-vs-live guard).
- **Dropped stack** — Postgres/pgvector, Celery, Redis, Supabase, streaming, RAG/`vecs` (ARCHITECTURE §1).

## Research Summary

DB.md §5 fixes `profile.yaml` as the single source for every numeric constant — five sections
(`athlete`/`thresholds`/`zones`/`nutrition`/`meta`), with hard caps (`deficit_pct ≤ 0.20`,
`protein_g_per_kg ≤ 2.0`) and zone bounds that must be **monotonic and contiguous**; E3·P1 already encodes
all of this in the `Profile` validator. The bootstrap (DB.md §6; ARCHITECTURE §3/§6) is an **offline,
deterministic** step that derives these constants from the read-only `baseline.db` and writes the file —
`baseline.db` is never opened at runtime, so the script lives in `scripts/`, not `app/`. Zones are **% of
max HR** (constitution §3): the DB.md §5 example `[96,125]…[177,192]` is exactly `round(pct·192)` for
`pct ∈ {.50,.65,.78,.87,.92,1.00}`, so `compute_zones` rounds the **six shared edges once** and pairs
them → contiguity holds by construction (not luck). `max_hr/rhr_baseline/hrv_baseline_ms/cadence_current`
are data-derived from `records` (by HK `type`); `easy_hr_cap = 180 − age` (Maffetone); and the `athlete`
block, `cadence_target_spm`, and the whole `nutrition` block are clinician/profile **config anchors**
(constitution §7) carried through, not fitted from samples. The single correctness guarantee is the
**validate-before-write round-trip**: the derivation constructs the E3·P1 `Profile(**data)` and a test
reloads the written file via `load_profile()`. See [`RESEARCH.md`](./RESEARCH.md).

## Decisions

- **Reuse `app.core.profile` (E3·P1) as the validator; never re-implement validation** — the derivation
  assembles the five-section dict and constructs `Profile(**data)`; any `ValidationError` aborts the write,
  and a round-trip test reloads the file via `load_profile()`. This is the single guarantee that the output
  passes "E3's validator" (epic §4) and prevents a parallel, drifting copy of the cap/zone rules (DB.md §5;
  E3·P1 PLAN). The script owns **zero** validation logic of its own.
- **Zones derived from %max-HR (not Karvonen/HR-reserve)** — constitution §3 states the primary anchor is
  "% of max HR", and the DB.md §5 example is **pure %max** (`round(pct·192)` reproduces `[96,125]…[177,192]`
  exactly; Karvonen with RHR would **not**). `compute_zones(max_hr, rhr)` keeps `rhr` in the signature (the
  §5 `zones` is conceptually a max/RHR pair, and RecomputeConstants re-derives from both) but the bpm
  cutpoints come from %max only. Flagged so a reviewer doesn't expect HR-reserve math.
- **Contiguity guaranteed by shared integer edges, not post-hoc patching** — `compute_zones` rounds the
  **six band edges once** (`e0..e5`) and forms `z1=(e0,e1) … z5=(e4,e5)`, so `zN.high` *is* `z(N+1).low`
  (the same int) for every `max_hr`. This makes the E3·P1 contiguity validator pass structurally rather
  than relying on rounding coincidences (epic §3 E4·P2 "contiguous/monotonic"; DB.md §5).
- **Split: data-derived vs computed vs config-anchor constants** — `max_hr`, `rhr_baseline`,
  `hrv_baseline_ms`, `cadence_current_spm` are derived from `baseline.db` `records` (by HK `type`);
  `easy_hr_cap = 180 − age` is computed (Maffetone); the `athlete` block, `cadence_target_spm`, and the
  whole `nutrition` block are **config anchors** (medical/clinician constants + profile inputs) carried
  through from the DB.md §5 / constitution §7 values — they are not fitted from raw samples (the deficit
  and protein values are medical limits; the carb multipliers and hydration/fiber are clinician picks).
  The anchors are injectable so a real deploy supplies the true `age`/`goal_weight_kg` etc. (DB.md §5
  `nutrition`/`athlete` rows; constitution §7).
- **Robust estimators; rolling anchors windowed, `max_hr` corpus-wide** — `max_hr` = the **bounded max**
  over plausibly-bounded exercise-HR samples across the **whole corpus** (a near-stationary physiological
  ceiling "from observed boxing peaks"; windowing it could miss the true peak), dropping values outside a
  physiological floor/ceiling so one artifact spike can't inflate it. `rhr_baseline`/`hrv_baseline_ms`/
  `cadence_current_spm` = medians over the **trailing ≈90 days from the latest sample** (a named
  `RECENT_DAYS` constant) so a 7-year corpus yields a *current monthly* anchor (DB.md §5 "monthly anchor"/§6
  trailing-window intent), not a lifetime mean, and the result is deterministic for a fixed corpus. The test
  fixture pins each expected value, the window membership, and the spike exclusion (RESEARCH Uncertainty).
- **Exact HK cadence record type confirmed against the corpus, not guessed** — HealthKit's running-cadence
  identifier varies by export version, so the plan pins a named `CADENCE_TYPE` constant to be confirmed
  against the real `baseline.db`/`export.xml` (as E4·P1 confirmed its own types from the corpus) rather
  than hard-asserting a possibly-wrong `HK…Identifier`; the derivation/tests are agnostic to the exact
  string (DB.md §1 "running cadence & dynamics"; RESEARCH Uncertainty).
- **Validate-before-write + write-once `yaml.safe_dump`** — never write a partially-built or invalid file:
  build the dict, validate via `Profile`, then dump with the DB.md §5 section order (`athlete`,
  `thresholds`, `zones`, `nutrition`, `meta`). Uses `yaml.safe_dump` (never `dump`) so only plain
  scalars/lists are emitted (DB.md §5 — human-readable, git-diffable).
- **`meta.computed_at` is today in Europe/Sofia via `zoneinfo`; `--computed-at` injectable** — DB.md §0
  derives period keys through the `Europe/Sofia` tz database (never a fixed offset). `computed_at` is the
  only nondeterministic input, so the CLI accepts `--computed-at` (an ISO date) to make the rest of the
  output reproducible/testable; `derived_from`/`constitution_version` are constants (`baseline.db` / `v1`,
  `--constitution-version` override) (epic R2; DB.md §5/§6).
- **Offline build script in `scripts/`, `baseline.db` read-only, never touched by `app/`** — ARCHITECTURE
  §6 / DB.md §0 say `baseline.db` is never opened at runtime; the derivation imports `app.core.profile`
  (the validator) but `app/` never imports the script or opens `baseline.db`. Plain `sqlite3` + stdlib + a
  YAML dump; no FastAPI/SQLAlchemy/Alembic (DB.md §0, §6).

## Risks

- **Derived `profile.yaml` fails the E3·P1 validator** (a bad estimator yields `max_hr ≤ rhr_baseline`, an
  over-cap `deficit_pct`, or a renamed key) → the bootstrap writes nothing usable — mitigation: the
  derivation constructs `Profile(**data)` **before** writing (any `ValidationError` aborts), the section
  keys mirror DB.md §5 1:1, and a round-trip test reloads the written file via `load_profile()`; a negative
  test feeds a fixture whose RHR ≥ derived max_hr and asserts the derivation raises rather than writes
  (epic §4; DB.md §5).
- **Zones non-contiguous from independent rounding** (rounding each zone's low and high separately could
  make `z1.high != z2.low`) → the E3·P1 contiguity validator rejects the file — mitigation: round the
  **six shared edges once** and pair adjacent edges so the shared int is reused; a test asserts
  `zN.high == z(N+1).low` across a range of `max_hr` values (DB.md §5; epic §3 E4·P2).
- **A single HR artifact inflates `max_hr`** (a spurious 230 bpm sample) → zones shift up and easy/threshold
  caps drift — mitigation: bound HR samples to a physiological window and use a high percentile / max over
  the filtered set; the fixture includes an out-of-range spike and asserts it is excluded (RESEARCH
  Uncertainty).
- **Determinism breaks** (same corpus → different file across runs) → the bootstrap isn't reproducible —
  mitigation: `computed_at` is the only nondeterministic input and is `--computed-at`-injectable; a test
  runs the derivation twice with a fixed `--computed-at` and asserts byte-identical output (epic §1/§6
  "deterministic computations").
- **Caps silently exceeded** (an anchor edited to `deficit_pct = 0.25`) → an unsafe deficit/protein reaches
  the macro engine — mitigation: the anchors default well inside the caps, and the `Profile` validator
  (`deficit_pct ≤ 0.20`, `protein_g_per_kg ≤ 2.0`) is the hard backstop that aborts the write; a negative
  test feeds an over-cap anchor and asserts the derivation raises (epic R2; DB.md §5; E3·P1 validator).
- **Confusing `rhr_baseline` (monthly zone anchor) with the live readiness baseline** → two competing RHR
  baselines — mitigation: the derivation writes only the §5 monthly anchor into `profile.yaml`; the live
  rolling 30d RHR/HRV stays in `daily_metrics` (E6) and is **not** sourced from the file; the static-vs-live
  split (DB.md §5 ¹) is documented and the file carries no live/derived field (E3·P1 guard).
- **`baseline.db` opened at runtime / script imported by `app/`** → violates the never-at-runtime rule —
  mitigation: the script lives in `scripts/`, opens the DB read-only, and `app/` never imports it; a check
  (`grep -REn "baseline\.db" app` → no hits) guards it (ARCHITECTURE §6; DB.md §0).

## Acceptance Criteria

- [ ] **Zones from a known maxHR/RHR match expected bounds** — `compute_zones(192, 58)` returns exactly
      `{"z1": (96,125), "z2": (125,150), "z3": (150,167), "z4": (167,177), "z5": (177,192)}` (the DB.md §5
      example). (`tests/scripts/test_compute_zones.py`; epic §4/§6; DB.md §5)
- [ ] **Zones are contiguous + monotonic for any maxHR** — for a range of `max_hr`, every
      `zN.high == z(N+1).low`, each `low < high`, and lows strictly increasing (so the E3·P1 zone validator
      passes). (`tests/scripts/test_compute_zones.py`; epic §3 E4·P2; DB.md §5)
- [ ] **The generated `profile.yaml` loads + validates via the E3·P1 `Profile` (round-trip)** — running the
      derivation over a synthetic `baseline.db` writes a `profile.yaml` that `app.core.profile.load_profile()`
      loads without error into a `Profile`. (`tests/scripts/test_derive_constants.py`; epic §4 "passes E3's
      validator"; DB.md §5)
- [ ] **`meta` is stamped** — the written file has `meta.derived_from == 'baseline.db'`,
      `meta.computed_at == date.fromisoformat(<injected --computed-at>)` (E3·P1 types it as `date`, so the
      test compares the parsed date), and a non-empty `meta.constitution_version` (e.g. `'v1'`).
      (`tests/scripts/test_derive_constants.py`; epic R2; DB.md §5/§6)
- [ ] **`easy_hr_cap` is Maffetone 180 − age** — for `age=34` the derived `thresholds.easy_hr_cap == 146`.
      (`tests/scripts/test_derive_constants.py`; constitution §3; DB.md §5)
- [ ] **Data-derived thresholds match the fixture** — `max_hr`, `rhr_baseline`, `hrv_baseline_ms`,
      `cadence_current_spm` derived from the synthetic `baseline.db` equal the fixture's expected values,
      and an injected out-of-range HR spike is excluded from `max_hr`.
      (`tests/scripts/test_derive_constants.py`; constitution §3; DB.md §1/§5)
- [ ] **Caps respected** — the derived `nutrition.deficit_pct ≤ 0.20` and `protein_g_per_kg ≤ 2.0`; an
      over-cap anchor makes the derivation **raise** (via the `Profile` validator) instead of writing.
      (`tests/scripts/test_derive_constants.py`; epic R2; DB.md §5)
- [ ] **Determinism** — two derivations over the same `baseline.db` with the same `--computed-at` produce
      byte-identical `profile.yaml`. (`tests/scripts/test_derive_constants.py`; epic §1/§6)
- [ ] **Offline-only** — `grep -REn "baseline\.db" app` returns no hits (the script lives in `scripts/`,
      `app/` never opens the corpus). (ARCHITECTURE §6; DB.md §0)
- [ ] `uv run ruff check .` and `uv run pytest tests/scripts/test_compute_zones.py
      tests/scripts/test_derive_constants.py` pass.

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [ ] TASK-001: compute_zones from maxHR and RHR
- [ ] TASK-002: Derive athlete, threshold and nutrition constants from baseline.db
- [ ] TASK-003: Write valid profile.yaml and stamp meta
- [ ] TASK-004: Final Validation
