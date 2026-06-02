# Plan: E3·P1 — profile.yaml schema & loader

Status: draft
Risk: small
Created: 2026-06-03

> Epic **E3 — Profile & Constitution**, phase **P1**. Source of truth:
> [`epics/E03-profile-constitution.md`](../../../epics/E03-profile-constitution.md) (§2 R1–R3, §3 E3·P1,
> §4 acceptance, §6 validation, §7 out-of-scope) · grounded in
> [`docs/architecture/DB.md`](../../../docs/architecture/DB.md) §5 (the `profile.yaml` block — the five
> sections `athlete`/`thresholds`/`zones`/`nutrition`/`meta`, every field, the example yaml verbatim, and
> the static-vs-live split table + footnote ¹) and §0 (`profile.yaml` is a file, NOT a table — 9 tables in
> `app.db`, no `profile` table) and
> [`docs/architecture/LLM.md`](../../../docs/architecture/LLM.md) §2 (the constitution renders fresh from
> `profile.yaml` — maxHR, baselines, zones, cadence cue, nutrition constants; `constitutionVersion` stamps
> each brief; live weight is fed via user context, not baked in). Builds on **E1·P1**
> (`app/core/settings.py` typed `pydantic-settings`, the camelCase Pydantic base — though this file is
> internal config, not a wire model). This phase ships the **typed loader + example file only**; it does
> not render the constitution (that is E3·P2) and does not derive the constants from `baseline.db` (E4).

## Goal

Make `profile.yaml` the single, validated source of truth for every numeric constant — a typed Pydantic
loader (`app/core/profile.py`) mirroring DB.md §5's five sections exactly, with cap/monotonicity/contiguity
validation, an example `profile.yaml` shipped verbatim from DB.md §5, and accessors for the zone/nutrition
constants (E8) and `constitution_version` (E9).

## Scope

- **`app/core/profile.py`** — typed Pydantic models mirroring DB.md §5 **exactly**, plus the loader and
  validators:
  - `Athlete` — `age: int`, `sex: str`, `height_cm: int`, `goal_weight_kg: float`.
  - `Thresholds` — `max_hr: int`, `rhr_baseline: int`, `hrv_baseline_ms: int`, `easy_hr_cap: int`,
    `cadence_target_spm: int`, `cadence_current_spm: int`.
  - `Zones` — `z1..z5`, each a `tuple[int, int]` (`[low, high]` bpm bounds).
  - `CarbsPerKg` — `hard_low`, `hard_high`, `moderate`, `rest_low`, `rest_high` (all `float`); all five
    required (no defaults).
  - `Nutrition` — `activity_factor: float`, `deficit_pct: float`, `protein_g_per_kg: float`,
    `fat_g_per_kg_low: float`, `fat_g_per_kg_high: float`, `carbs_g_per_kg: CarbsPerKg`,
    `hydration_l_low: float`, `hydration_l_high: float`, `fiber_g_low: float`, `fiber_g_high: float`.
  - `Meta` — `derived_from: str`, `computed_at: date`, `constitution_version: str`.
  - `Profile` — the root model: `athlete`, `thresholds`, `zones`, `nutrition`, `meta`. `extra="forbid"` on
    every section so a stray/renamed key fails loudly rather than being silently dropped.
  - **Validators** (R2): `Thresholds.max_hr > rhr_baseline`; `Zones` bounds **monotonic** (each
    `low < high`, and `z1.low < z2.low < … < z5.high`) **and contiguous** (`z1.high == z2.low`,
    `z2.high == z3.low`, `z3.high == z4.low`, `z4.high == z5.low`); `Nutrition.deficit_pct ≤ 0.20`
    (hard cap), `protein_g_per_kg ≤ 2.0` (kidney-stone cap), `fat_g_per_kg_low ≤ fat_g_per_kg_high`. All
    five carb multipliers present is enforced structurally by `CarbsPerKg` having no defaults +
    `extra="forbid"`.
  - **Loader** — `load_profile(path: Path | None = None) -> Profile`: reads YAML (`yaml.safe_load`),
    constructs `Profile`, surfaces `pydantic.ValidationError` (and a clear `FileNotFoundError`/parse error)
    with a readable message. Default path resolves to the app-root `profile.yaml` (next to the repo root /
    importable via a module-level constant, overridable by argument and/or a settings key).
  - **Accessors** — methods/functions returning exactly what downstream epics need:
    `Profile.zone_bounds() -> dict[str, tuple[int,int]]` and the nutrition constants (E8), and
    `Profile.constitution_version -> str` / a `constitution_version()` helper (E9). These read **only**
    static fields — no live/derived value is exposed.
- **`profile.yaml`** (app/repo root) — the **example block from DB.md §5 verbatim** (athlete 34/male/174/75;
  thresholds max_hr 192 etc.; zones z1–z5; nutrition activity_factor 1.65, deficit_pct 0.12, protein 1.8,
  fat 0.8–1.0, carbs `{hard_low:4, hard_high:5, moderate:3, rest_low:2, rest_high:2.5}`, hydration 3.0–3.5,
  fiber 25–35; meta derived_from `baseline.db`, computed_at `2026-06-02`, constitution_version `v1`) so E8
  (macros/zones) and E9 (render inputs) have constants before E4 generates them for real.
- **`tests/core/test_profile.py`** — a valid `profile.yaml` loads into `Profile`; the shipped example file
  loads; each invalid case raises a clear error: `deficit_pct > 0.20`; `protein_g_per_kg > 2.0`;
  non-monotonic zones; non-contiguous zones (`z1.high != z2.low`); a missing carb multiplier; `fat low >
  high`; `max_hr ≤ rhr_baseline`; a stray/unknown key (extra-forbid); a missing section. Plus a
  static-vs-live guard: the model exposes **no** field for current weight / rolling HRV/RHR baselines /
  per-day metrics (those live in the DB), proven by asserting those names are absent from the schema.

## Out of Scope

- **Rendering the constitution** — turning `HEALTH-CONSITTUTION.md` into a Jinja2 template and producing the
  system-prompt string is **E3·P2**; this phase only loads/validates constants and exposes accessors
  (epic §3 E3·P2; LLM.md §2).
- **Deriving the constants from `baseline.db`** — the bootstrap step that *writes* `profile.yaml` from
  `baseline.db` is **E4·P2**, and the monthly `RecomputeConstants` rewrite is **E8·P5 + E10**. This phase
  only **reads** the file and ships a static example; it never generates or recomputes it (epic §7; DB.md
  §5–§6, §10).
- **Live / derived values** — current weight (latest `body_mass` → `daily_metrics.body_weight`), 30d
  HRV mean+SD / 30d RHR mean, per-day sleep / zone-minutes / readiness / nutrition intake live in
  `app.db` (`daily_metrics`) and must **not** be sourced from `profile.yaml`; this phase deliberately does
  not model them (epic R3; DB.md §5 table + footnote ¹).
- **The macro/zone math and the system prompt that consume these constants** — E8 (macro engine, zone
  computation) and E9 (LLM call) are the consumers; this phase only provides the typed accessors they will
  call (epic §3; DB.md §5 "the macro engine reads these"; LLM.md §2–§3).
- **Wiring `profile.yaml` into `pydantic-settings`/env beyond a path** — settings owns env config (E1·P1);
  the loader takes a path (default app-root) and may read a settings-provided path, but it does not move the
  constants into env vars (DB.md §5 — a YAML file is the chosen home, git-diffable).
- **Dropped stack** — Postgres/pgvector, Celery, Redis, Supabase, streaming, RAG/`vecs`
  (ARCHITECTURE §1 stack note).

## Research Summary

DB.md §5 defines `profile.yaml` as the **single source of truth for every numeric constant** — a file, not
a table (`app.db` has 9 tables and **no** `profile` table, DB.md §0/§5). It pins five sections —
`athlete`, `thresholds`, `zones`, `nutrition`, `meta` — and ships an exact example yaml block (reproduced
verbatim as the starting file). The static-vs-live split is load-bearing (epic R3; DB.md §5 table +
footnote ¹): age/sex/height/goal-weight, `max_hr`/`rhr_baseline`/`hrv_baseline_ms`/`easy_hr_cap`/cadence
cues, the Z1–Z5 bpm bounds, and the nutrition constants are **static/monthly-frozen** in the file; current
weight, the 30d HRV/RHR rolling baselines, and per-day metrics live in `daily_metrics` and must **not** be
read from the file. `rhr_baseline`/`hrv_baseline_ms` in the file are the *monthly anchors used to derive
zones* — readiness reads the live rolling values from `daily_metrics`, not these (DB.md §5 ¹). Validation
constraints come straight from the §5 yaml comments (epic R2): `deficit_pct` hard cap 0.20, `protein_g_per_kg`
kidney-stone cap 2.0, `fat_g_per_kg_low ≤ fat_g_per_kg_high`, carb multipliers present for each day type
`{hard_low, hard_high, moderate, rest_low, rest_high}`, and zone bounds monotonic **and** contiguous (each
zone's high is the next zone's low — `z1:[96,125] z2:[125,150] …`). LLM.md §2 confirms the consumers: the
constitution renders fresh each call from these constants (maxHR, baselines, zones, cadence cue, nutrition
constants — E9), and `constitutionVersion` stamps each brief; E8's macro/zone math reads the nutrition/zone
constants. This phase delivers the typed loader + example file so E8/E9 have constants before E4 writes the
real ones.

## Decisions

- **Target `app/core/profile.py` (typed models + loader), not a DB table or a `services/` module** — DB.md
  §0/§5 are explicit that the constants are a *file*, and the loader is a core primitive consumed by E8/E9,
  so it sits in `app/core/` alongside `settings.py` (epic §3 notes; DB.md §5). The file `profile.yaml`
  lives at the app/repo root (human-readable, hand-editable, git-diffable — DB.md §5).
- **Section field names mirror DB.md §5 yaml keys 1:1 in snake_case; `extra="forbid"` on every model** — the
  yaml is hand-edited and git-diffed, so a typo'd or renamed key must fail loudly rather than load with a
  silent default; `extra="forbid"` turns an unknown key into a `ValidationError` (epic R1; DB.md §5). This
  is an internal config model, so it does **not** inherit the E1·P1 camelCase wire base (no camelCase
  aliasing — the file is read as-is).
- **Zones modeled as `tuple[int,int]` per zone (z1..z5), validated monotonic AND contiguous** — DB.md §5
  writes each zone as `[low, high]` bpm bounds and the example is contiguous (`z1.high==z2.low`, …), so a
  model-level validator asserts each `low < high`, strictly increasing lows, and `zN.high == z(N+1).low`.
  Contiguity is a real invariant of HR-zone derivation (`compute_zones.py`) — a gap or overlap would
  mis-bucket zone minutes downstream (epic R2; DB.md §5).
- **Caps enforced as `≤` model validators on `Nutrition`** — `deficit_pct ≤ 0.20` and `protein_g_per_kg ≤
  2.0` are hard/medical caps from the §5 comments; they are validated at load (not at use-site) so a bad
  file can never reach the macro engine (epic R2; DB.md §5). `fat_g_per_kg_low ≤ fat_g_per_kg_high` is a
  cross-field validator on the same model.
- **`CarbsPerKg` is its own model with five required fields (no defaults) + `extra="forbid"`** — "all five
  carb multipliers present" (epic R2) is enforced *structurally*: a missing key is a `ValidationError` for
  the required field, and a stray key is rejected by `extra="forbid"`, so the validator needs no manual
  presence check (DB.md §5 `carbs_g_per_kg: {hard_low, hard_high, moderate, rest_low, rest_high}`).
- **Loader exposes accessors that read only static fields; no live/derived value is modeled** — `zone_bounds`
  + nutrition constants (E8) and `constitution_version` (E9) are surfaced; current weight, 30d HRV/RHR
  baselines, and per-day metrics are deliberately **absent** from `Profile`, enforcing the static-vs-live
  split structurally and proven by a schema-absence test (epic R3; DB.md §5 table + ¹).
- **Ship the DB.md §5 example as the starting `profile.yaml` verbatim** — so E8 (macros/zones) and E9
  (render inputs) have valid constants before E4 derives the real ones from `baseline.db`; the example is a
  known-valid fixture the loader test also exercises (epic §3 E3·P1; DB.md §5).
- **`meta.computed_at` typed as `datetime.date`** — DB.md §5 writes it as a bare ISO date (`2026-06-02`);
  modeling it as `date` validates the format and matches its semantics (the day the constants were
  computed), while `derived_from`/`constitution_version` stay `str` (DB.md §5).

## Risks

- **Field names drift from DB.md §5** → the constitution template (E3·P2) or macro engine (E8) reads a key
  that does not exist — mitigation: every field name mirrors the §5 yaml key exactly, `extra="forbid"`
  rejects strays, and the loader test loads the **shipped example** `profile.yaml` (the §5 block verbatim),
  so any rename breaks the test (epic R1; DB.md §5).
- **A cap or monotonicity check is silently skipped** (e.g. validator not wired, or `<` vs `≤`) → an
  out-of-range deficit/protein or a gapped zone set loads cleanly and corrupts downstream math —
  mitigation: one negative test per rule (`deficit>0.20`, `protein>2.0`, non-monotonic, non-contiguous,
  missing carb key, `fat low>high`, `max_hr≤rhr`) asserts a `ValidationError` with a message naming the
  field (epic R2, §4, §6).
- **Contiguity vs monotonicity conflated** → a monotonic-but-gapped zone set (`z1.high < z2.low`) passes a
  monotonic-only check — mitigation: the validator asserts both, and a dedicated test feeds a monotonic but
  **non-contiguous** set and asserts it is rejected (DB.md §5; epic R2).
- **A live/derived value leaks into `profile.yaml`/the model** (current weight, rolling baselines) → the
  static-vs-live split (epic R3) is violated and stale numbers reach the brain — mitigation: `Profile`
  models only the §5 static fields; a test asserts `body_weight`/`current_weight`/`hrv_30d`/`rhr_30d`/
  `readiness` (and similar) are **absent** from the schema, and `extra="forbid"` would reject them if added
  to the file (epic R3; DB.md §5 table + ¹).
- **YAML scalar coercion surprises** (e.g. `rest_high: 2.5` as float, dates parsed by the YAML loader) →
  type mismatch or an unexpected `datetime` — mitigation: use `yaml.safe_load`, type the numeric fields
  explicitly (`int`/`float`), type `computed_at` as `date`, and assert the example file's parsed types in
  the load test (DB.md §5).
- **Default-path resolution is wrong in tests/runtime** (cwd-relative vs package-relative) → loader can't
  find `profile.yaml` — mitigation: the default path is resolved from a module-level anchor (app/repo
  root), `load_profile(path=...)` takes an explicit override, and tests always pass an explicit temp path
  for the negative cases while one test loads the real shipped file via its resolved default.
- **Scope creep into rendering/derivation** → this phase accidentally renders the constitution or reads
  `baseline.db` — mitigation: scope is loader + example + accessors only; rendering is E3·P2 and derivation
  is E4 (epic §7).

## Acceptance Criteria

- [ ] **Valid file loads into the typed model** — `load_profile(<valid temp yaml>)` returns a `Profile`
      with all five sections populated and the field values equal to the yaml (e.g.
      `p.thresholds.max_hr == 192`, `p.nutrition.carbs_g_per_kg.hard_low == 4`,
      `p.zones.z1 == (96, 125)`). (`tests/core/test_profile.py`; epic §4; DB.md §5)
- [ ] **Shipped example loads** — `load_profile()` (default app-root path) loads the committed
      `profile.yaml` (the DB.md §5 block verbatim) into a `Profile` with no error. (epic §3 E3·P1; DB.md §5)
- [ ] **Deficit cap** — a yaml with `nutrition.deficit_pct = 0.25` raises `pydantic.ValidationError` whose
      message names `deficit_pct` / the 0.20 cap. (epic R2, §4; DB.md §5)
- [ ] **Protein cap** — a yaml with `nutrition.protein_g_per_kg = 2.5` raises a `ValidationError` naming
      `protein_g_per_kg` / the 2.0 cap. (epic R2, §4; DB.md §5)
- [ ] **Non-monotonic zones** — a yaml where a zone's `low ≥ high` (or lows not strictly increasing) raises
      a `ValidationError` naming the zone bounds. (epic R2, §4; DB.md §5)
- [ ] **Non-contiguous zones** — a yaml where `z1.high != z2.low` (monotonic but gapped/overlapping) raises
      a `ValidationError`. (epic R2; DB.md §5)
- [ ] **Missing carb multiplier** — a yaml missing one of `{hard_low, hard_high, moderate, rest_low,
      rest_high}` raises a `ValidationError` naming the missing field. (epic R2, §4; DB.md §5)
- [ ] **Fat low > high** — a yaml with `fat_g_per_kg_low > fat_g_per_kg_high` raises a `ValidationError`.
      (epic R2; DB.md §5)
- [ ] **max_hr > rhr** — a yaml with `thresholds.max_hr ≤ thresholds.rhr_baseline` raises a
      `ValidationError`. (epic R2; DB.md §5)
- [ ] **Unknown / stray key rejected** — a yaml with an extra key in any section raises a `ValidationError`
      (`extra="forbid"`). (Decision; epic R1)
- [ ] **Accessors return the constants E8/E9 need** — `Profile` exposes the zone bounds and nutrition
      constants (E8) and `constitution_version` (E9): e.g. `p.zone_bounds()["z5"] == (177, 192)`,
      `p.nutrition.deficit_pct == 0.12`, `p.meta.constitution_version == "v1"`. (epic R1; DB.md §5; LLM.md §2)
- [ ] **No live/derived value is sourced from the file** — `Profile`'s schema contains **no** field for
      current weight / rolling HRV/RHR baselines / per-day metrics (asserted by name-absence over
      `Profile.model_fields` and the nested sections). (epic R3; DB.md §5 table + ¹)
- [ ] `uv run ruff check .` and `uv run pytest tests/core/test_profile.py` pass.

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [ ] TASK-001: Pydantic models for profile.yaml sections
- [ ] TASK-002: Loader and validation (caps, monotonic zones)
- [ ] TASK-003: Example profile.yaml and constant accessors
- [ ] TASK-004: Final Validation
