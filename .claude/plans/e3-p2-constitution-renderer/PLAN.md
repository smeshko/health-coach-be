# Plan: E3·P2 — Constitution template & renderer

Status: draft
Risk: medium
Created: 2026-06-03

> Epic **E3 — Profile & Constitution**, phase **P2**. Source of truth:
> [`epics/E03-profile-constitution.md`](../../../epics/E03-profile-constitution.md) (§2 R4–R6, §3 E3·P2, §4
> acceptance, §6 validation, §7 out-of-scope) · grounded in
> [`docs/architecture/LLM.md`](../../../docs/architecture/LLM.md) §0 (the call envelope — constitution is
> the **system** prompt) and §2 (Jinja2-rendered from `profile.yaml`: maxHR, RHR/HRV baselines, zones,
> cadence cue, nutrition constants; **caching off** — render fresh; **live weight fed via the user context**,
> not baked in; `constitutionVersion` stamps each brief; **§2 medical block = context**, not a code-enforced
> layer) and §5 (caching off at ~2 calls/day) ·
> [`docs/architecture/ARCHITECTURE.md`](../../../docs/architecture/ARCHITECTURE.md) §6 (`HEALTH-CONSITTUTION.md`
> = a Jinja2 template rendered fresh each call; §2 conditions are context, not a code-enforced layer —
> fitness app, not a medical device) ·
> [`docs/architecture/DB.md`](../../../docs/architecture/DB.md) §5 (the `profile.yaml` block — the exact keys
> the placeholders bind to; the static-vs-live split). Builds on **E3·P1**
> (`app/core/profile.py`: `load_profile() -> Profile`, `Profile.{athlete,thresholds,zones,nutrition,meta}`,
> `Profile.zone_bounds()`, `Profile.meta.constitution_version`). Curated findings in
> [`RESEARCH.md`](./RESEARCH.md). This phase **renders** the constitution; it does not derive the constants
> from `baseline.db` (E4) and does not build the LLM call (E9).

## Goal

Render `HEALTH-CONSITTUTION.md` into the LLM system prompt by lifting it into a Jinja2 template whose `{{ }}`
placeholders are filled from `profile.yaml` (via the E3·P1 loader) under `StrictUndefined` — fresh each call,
failing loudly on any missing constant — with the §2 medical block rendered as context, `constitution_version`
surfaced for brief stamping, and a documented seam for injecting live weight at call time (never baked in).

## Scope

- **`app/core/templates/constitution.md.j2`** — the templatized rulebook: `HEALTH-CONSITTUTION.md`'s prose
  copied verbatim with its numeric constants as `{{ … }}` placeholders bound to `Profile` attribute paths
  (`athlete.*`, `thresholds.*`, `zones.zN[0|1]`, `nutrition.*` incl. `nutrition.carbs_g_per_kg.*`, and the
  derived `thresholds.easy_hr_cap - 8`). **Only numeric constants are templatized — prose is unchanged.**
  Live-value rows (current weight, VO₂max, sleep, steps) stay plain prose with **no** placeholder.
- **`app/core/constitution.py`** — the renderer:
  - A module-private Jinja2 `Environment` built with `undefined=StrictUndefined`, `autoescape=False`
    (Markdown, not HTML), `FileSystemLoader` rooted at the package `templates/` dir (resolved relative to
    `__file__`, not cwd), `keep_trailing_newline=True`, `trim_blocks=False`.
  - `render_constitution(profile: Profile) -> str` — renders the template **fresh each call** (no caching/
    memoization) from the profile's sections; a missing constant raises `jinja2.UndefinedError`. The
    template is passed the section objects (`athlete`, `thresholds`, `zones`, `nutrition`) so placeholder
    paths read naturally; `zones.zN` are the `tuple[int,int]` from the loader so `zN[0]`/`zN[1]` work.
  - `constitution_version(profile: Profile) -> str` — returns `profile.meta.constitution_version` (the
    stamp E9 records on each brief).
  - The **live-weight seam**: a documented helper/structure (e.g. `LiveContext` dataclass or a documented
    `build_user_context(profile, live_weight_kg, …)` stub returning the *user-context* payload, NOT the
    system prompt) marking where E9 injects live weight at call time. Live weight is **never** read from
    `profile.yaml` and **never** rendered into the template. (Seam only — the full user-context assembly is E9.)
- **`tests/core/test_constitution.py`** — renderer tests (see Acceptance).

## Out of Scope

- **Deriving the constants** — writing `profile.yaml` from `baseline.db` (bootstrap, E4·P2) and the monthly
  `RecomputeConstants` rewrite (E8·P5 + E10). This phase only **reads** the loaded `Profile` and renders
  (epic §7; DB.md §5–§6, §10).
- **The profile loader & its validation** — `app/core/profile.py`, the caps/monotonicity/contiguity checks,
  and the example `profile.yaml` are **E3·P1** (already shipped); this phase consumes them, it does not
  re-model or re-validate the constants (epic §3 E3·P1).
- **Building the LLM call** — assembling the full **user context** JSON (readiness, budgets, aggregates,
  flags, live weight), the PydanticAI `Agent`/`AgentNode`, structured `OutputType`, retries, and the brief
  cache are **E9** (LLM.md §0–§4). This phase ships only the system-prompt renderer + the live-weight
  injection **seam**, not the assembly.
- **The macro/zone math** that consumes these constants at call time — BMR/TDEE/macro grams from live `W`,
  zone-minute bucketing — is **E8** (LLM.md §2–§3; constitution §7). The renderer emits the numbers as
  prompt text; it does no arithmetic beyond Jinja2 resolving the one `easy_hr_cap - 8` expression.
- **The current cadence cue** — `cadence_current_spm` is **not** rendered into the constitution (the prose
  templates only `cadence_target_spm`, the end target); the per-card current cue (`cadenceSpm`) is computed
  by code from `profile.yaml cadence_current_spm` and fed via the **user context** at call time — that is
  **E8/E9** (MODELS.md §427/§617; LLM.md §3). See the Decisions note; this is the same static-vs-live
  boundary as live weight.
- **Prompt caching / cache breakpoints** — decided **off** (LLM.md §2, §5); the renderer deliberately adds
  no memoization. Not a future TODO — a design decision.
- **Auto-regenerating the `.j2` from the root `.md` in a build step** — a docs-tooling concern; this phase
  keeps the `.j2` as a verbatim copy guarded by a `diff`-equivalence check + a structural §1–§11
  section-presence test (see Decisions), the root `.md` stays the human doc. Wiring a generator is out of
  scope.
- **Dropped stack** — Postgres/pgvector, Celery, Redis, Supabase, streaming, RAG/`vecs` (ARCHITECTURE §1).

## Research Summary

`HEALTH-CONSITTUTION.md` is **already authored as a Jinja2 template** — reading it shows every numeric
constant is already an `{{ … }}` placeholder bound to the `profile.yaml` keys (verified against DB.md §5):
`thresholds.max_hr`, `thresholds.easy_hr_cap`, `thresholds.cadence_target_spm`, `zones.zN[0]/[1]`, and the
full `nutrition` block (`activity_factor`, `deficit_pct`, `protein_g_per_kg`, `fat_g_per_kg_low/high`,
`carbs_g_per_kg.{hard_low,hard_high,moderate,rest_low,rest_high}`, `hydration_l_low/high`,
`fiber_g_low/high`), plus one derived expression `{{ thresholds.easy_hr_cap - 8 }}` (§3). So E3·P2 is mostly
*plumbing*: lift the file into the package and write the renderer. Per LLM.md §0/§2 the constitution is the
**system** prompt, rendered **fresh each call** (caching off — TTL never hits at ~2 calls/day, LLM.md §5);
the **live weight** is fed via the **user context**, not the template (epic R4; LLM.md §2); the **§2 medical
block renders as context** the brain weighs, never a code-enforced layer (epic R5; ARCHITECTURE §6; LLM.md
§2); and `constitution_version` (`Profile.meta.constitution_version`) stamps each brief (epic R6; LLM.md §2;
MODELS DailyBrief). The fail-loud guarantee (epic §4 — "a missing constant fails loudly, no silent blanks")
maps directly to Jinja2 `StrictUndefined`. The renderer consumes the E3·P1 `Profile`/`load_profile`
contract. See [`RESEARCH.md`](./RESEARCH.md) for the placeholder inventory and the template-loading decision.

## Decisions

- **Ship the template inside the package at `app/core/templates/constitution.md.j2`, loaded via a
  `FileSystemLoader` rooted relative to `__file__`** — the constitution is a runtime artifact (the system
  prompt), so it must travel with the package and load from any cwd; rooting the loader at the module dir
  (not the process cwd) makes rendering deterministic in tests and runtime. The repo-root
  `HEALTH-CONSITTUTION.md` stays the human-facing source; the `.j2` is a verbatim copy **except** for one
  required edit: the root file contains **3 literal explanatory `{{ … }}` strings** (lines 11, 38, 281 —
  prose *about* the templating, not real placeholders) that Jinja2 cannot parse (it would evaluate the `…`
  and raise `TemplateSyntaxError`), so the `.j2` wraps exactly those 3 in `{% raw %}…{% endraw %}` (they
  render back to the literal `{{ … }}` text). A byte-identical copy is therefore *unparseable* — this is
  the one intended divergence. **Drift is guarded three ways**, not left to chance: (1) the template must
  **compile** under the StrictUndefined env (parse test — the primary guard); (2) a structural
  section-presence test asserting all §1–§11 headers render (so a `.j2` that silently drops
  safety/progression/etc. fails — substring checks alone would miss that); and (3) a
  `diff HEALTH-CONSITTUTION.md app/core/templates/constitution.md.j2` check whose **only** allowed
  difference is the 3 `{% raw %}`-escaped prose lines (equivalently: stripping the `{% raw %}`/`{% endraw %}`
  tags yields a file byte-identical to the root `.md`). (LLM.md §2; ARCHITECTURE §6; Codex round-1 #3, round-2 #1)
- **`undefined=StrictUndefined`** — epic §4 demands a missing constant "fail loudly (no silent blanks)";
  `StrictUndefined` raises `UndefinedError` the moment an unfilled `{{ }}` is touched, instead of rendering
  an empty string. This is the core acceptance guarantee and is asserted by a negative test. (epic §4; LLM.md §2)
- **`autoescape=False`** — the output is a **Markdown** system prompt, not HTML; HTML-escaping would corrupt
  `&`, `<`, `>`, and quotes in the prose (e.g. "≤", arrows, "180−age"). Markdown context = no autoescape.
  (constitution prose; LLM.md §2 — the rendered text is fed straight to the model)
- **Render fresh each call — no caching/memoization in the renderer** — LLM.md §2/§5 and ARCHITECTURE §6
  decide caching **off** (at ~2 calls/day the prompt-cache TTL never hits), so `render_constitution` builds
  the string on every call with no memo keyed on the profile. This is a deliberate non-feature, not an
  optimization gap. (LLM.md §2, §5; epic R4)
- **Live weight is injected via the user context, never the template** — a documented seam (a `LiveContext`
  dataclass / a `build_user_context(...)` stub returning the *user-context* payload) marks where E9 feeds
  live `W` at call time; the template has **no** weight placeholder and the renderer never reads weight from
  `profile.yaml`. The §1 "Weight (current)" row stays prose. (epic R4; LLM.md §2; constitution §1/§7)
- **§2 medical block renders as prose context — no medical validation, no denylist in code** — it is context
  the brain weighs (lactose-safe, NSAID-free, gallbladder-aware), explicitly *not* a code-enforced layer
  (fitness app, not a medical device); the only code-enforced safety is the §6.2 training auto-regulation
  gate (out of scope here). The renderer passes the medical prose through unchanged and a test asserts it is
  present in the output. (epic R5; ARCHITECTURE §6; LLM.md §2)
- **`constitution_version` surfaced via a thin `constitution_version(profile)` helper reading
  `profile.meta.constitution_version`** — keeps the version-surfacing seam explicit for E9 to stamp on each
  brief, without coupling the renderer to the brief model. (epic R6; LLM.md §2; MODELS DailyBrief)
- **Templatize only numeric constants; leave prose and live-value snapshots untouched** — `HEALTH-CONSITTUTION.md`
  already does this; the `.j2` preserves the prose verbatim. Live-value rows (VO₂max, sleep, steps, current
  weight) have **no** placeholder — they are computed context, not constants (epic R3/R4; constitution §1).
- **Pass section objects to the template (`athlete`, `thresholds`, `zones`, `nutrition`) and keep zones as
  the loader's `tuple[int,int]`** — so the existing placeholder paths (`thresholds.max_hr`, `zones.z1[0]`,
  `nutrition.carbs_g_per_kg.hard_low`) resolve directly off the `Profile` attribute graph with no
  remapping; a remap layer would be a second place for keys to drift. (E3·P1 `Profile` shape; DB.md §5)
- **The constitution templates `cadence_target_spm` (the END target) only — `cadence_current_spm` (this
  month's cue) is deliberately NOT a placeholder** — the rulebook prose (constitution §3 line 123, §9 line
  365) references only `{{ thresholds.cadence_target_spm }}`; the *current* ramp cue is the per-run-card
  `cadenceSpm` value computed deterministically from `profile.yaml cadence_current_spm` and fed via the
  **user context** at call time (MODELS.md §427/§617; LLM.md §3 / §207 "code · deterministic progression
  via `profile.yaml cadence_current_spm`"). Baking the current cue into the system prompt would duplicate
  it (and could go stale against the per-card value), so it stays a user-context input — same boundary as
  live weight. This is intentional, not an omission. (DB.md §5; MODELS.md; LLM.md §3; Codex round-1 #2)

## Risks

- **The 3 literal explanatory `{{ … }}` prose strings break Jinja2 parsing** (root lines 11/38/281 are prose
  *about* the templating, not real placeholders; the `…` is not a valid expression) → a byte-identical `.j2`
  raises `TemplateSyntaxError` at compile and the template is unusable — mitigation: wrap exactly those 3 in
  `{% raw %}…{% endraw %}` (they render back to the literal text); a parse test asserts the `.j2` compiles
  and a render test asserts the literal `{{ … }}` text still appears in those 3 spots. (Codex round-2 #1)
- **A placeholder in the `.j2` doesn't match a `Profile` attribute path** (typo, or a key renamed in E3·P1)
  → `StrictUndefined` raises at render and the system prompt can't be built — mitigation: render the
  **shipped** `profile.yaml` (the real E3·P1 example) end-to-end in a test and assert success + specific
  constants present (`max_hr` 192, a zone bound, a nutrition constant); pass the `Profile` section objects
  directly so paths bind 1:1 with no remap. (epic §4, §6)
- **`StrictUndefined` silently downgraded** (e.g. someone uses `Undefined`/`ChainableUndefined`, or a
  `default()` filter creeps in) → a missing constant renders blank and a drifted prompt reaches the model —
  mitigation: a negative test renders a template/profile with one placeholder unfilled and asserts
  `jinja2.UndefinedError` (or `UndefinedError` subclass) is raised; assert the env's `undefined is
  StrictUndefined`. (epic §4; LLM.md §2)
- **Autoescape corrupts the prose** (HTML-escaped `&`/`<`/quotes) → the model reads mangled rules —
  mitigation: `autoescape=False` and a test asserting a known prose substring with special chars (e.g.
  "180−age", "≤", "Z1–Z2") survives verbatim. (constitution prose)
- **Caching/memoization sneaks in** ("render once") → a stale prompt after a monthly `profile.yaml`
  recompute — mitigation: the renderer holds no module-level cache keyed on profile; a test renders twice
  with two different `Profile`s (different `max_hr`) and asserts the outputs differ accordingly. (LLM.md §2, §5)
- **Live weight leaks into the prompt** (a `{{ weight }}` placeholder, or the renderer reading weight) →
  the static-vs-live split is violated, a stale weight is baked into the system prompt — mitigation: the
  `.j2` has no weight placeholder; a test asserts no `body_mass`/`current_weight`/live-weight token from a
  live value appears in the rendered system prompt and that `render_constitution` takes only a `Profile`
  (no weight arg). (epic R3/R4; LLM.md §2; DB.md §5)
- **The §2 medical block gets dropped or summarized** (e.g. a prose edit that trims it) → the brain loses
  the medical context it must weigh — mitigation: a drift-guard test asserts distinctive §2 prose
  ("Never suggest NSAIDs", "Lactose intolerance", "Biliary dyskinesia") and the §2 scope note appear in the
  output. (epic R5; ARCHITECTURE §6)
- **Template path resolved relative to cwd, not the module** → renderer can't find the template under pytest
  or a different working dir — mitigation: `FileSystemLoader` rooted at `Path(__file__).parent / "templates"`;
  a test imports and renders from a different cwd (or just relies on pytest's cwd-independence) and passes.
- **Scope creep into E9/E8** — accidentally assembling the user context or doing macro math here —
  mitigation: ship only the renderer + version helper + the live-weight **seam** (a documented stub); the
  full user-context assembly and macro grams are explicitly E9/E8 (Out of Scope).

## Acceptance Criteria

- [ ] **Every placeholder is filled from a sample profile** — `render_constitution(load_profile())` (the
      shipped E3·P1 example `profile.yaml`) returns a non-empty `str` with **no** error; **no unresolved
      real placeholder** remains (the only `{{ … }}` text left in the output is the 3 literal explanatory
      examples that were `{% raw %}`-escaped — i.e. no `{{ <identifier> }}` of the form `{{ athlete.* }}` /
      `{{ thresholds.* }}` / `{{ zones.* }}` / `{{ nutrition.* }}` survives). (`tests/core/test_constitution.py`;
      epic §4, §6)
- [ ] **A deliberately missing constant fails loudly (StrictUndefined)** — rendering with a profile/template
      whose placeholder is unfilled raises `jinja2.UndefinedError` (no blank substitution); the env's
      `undefined is StrictUndefined`. (epic §4; LLM.md §2)
- [ ] **Rendered output contains the live constants** — `max_hr` (`192`), at least one zone bound (e.g. `177`
      and `192` for `z5`), `easy_hr_cap` (`146`), the cadence target (`172`), and a nutrition constant (e.g.
      `protein_g_per_kg` `1.8`, a carb multiplier) appear verbatim in the output; the derived
      `easy_hr_cap - 8` (`138`) appears. (epic §4; constitution §1/§3/§7)
- [ ] **The §2 medical block renders as prose context** — distinctive §2 prose ("Never suggest NSAIDs",
      "Lactose intolerance", "Biliary dyskinesia") and the §2 scope note ("not a code-enforced compliance
      layer") appear in the output. (epic R5; ARCHITECTURE §6; LLM.md §2)
- [ ] **Template parses & no prose section silently dropped (drift-guard)** — the `.j2` compiles under the
      StrictUndefined env (no `TemplateSyntaxError`, with the 3 literal `{{ … }}` prose examples escaped via
      `{% raw %}`), all major section headers `## 1.`–`## 11.` appear in the rendered output (so a `.j2`
      missing safety/progression/etc. fails), and a `diff HEALTH-CONSITTUTION.md
      app/core/templates/constitution.md.j2` differs **only** in those 3 escaped prose lines (stripping the
      `{% raw %}`/`{% endraw %}` tags yields a file byte-identical to the root `.md`). (ARCHITECTURE §6;
      Codex round-1 #3, round-2 #1)
- [ ] **`constitution_version` is surfaced** — `constitution_version(load_profile()) == "v1"` and it equals
      `Profile.meta.constitution_version`. (epic R6; LLM.md §2)
- [ ] **Live weight is NOT baked into the prompt** — `render_constitution` accepts only a `Profile` (no
      weight argument); the template has no weight *placeholder* (`{{ … weight/body_mass … }}` — though the
      literal §1 "Weight (current) → … `body_mass`" prose row is kept verbatim), the rendered output
      contains no live-weight value sourced from a runtime number (a sentinel like `83.4` passed only to the
      seam never appears), and a live-weight injection seam exists in `app/core/constitution.py` (a
      documented `LiveContext`/`build_user_context` stub for the **user context**, separate from the system
      prompt). (epic R4; LLM.md §2; Codex round-1 #1)
- [ ] **Renders fresh each call (no caching)** — two renders with two `Profile`s differing only in `max_hr`
      produce outputs differing in that value (no stale memoized result). (LLM.md §2, §5; epic R4)
- [ ] **Prose/special chars survive (autoescape off)** — a known prose substring with special characters
      (e.g. "180−age" / "≤" / "Z1–Z2") appears unescaped in the output. (Decision; constitution prose)
- [ ] `uv run ruff check .` and `uv run pytest tests/core/test_constitution.py` pass.

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [ ] TASK-001: Jinja2 constitution template from HEALTH-CONSITTUTION.md
- [ ] TASK-002: Renderer filling placeholders from profile.yaml with StrictUndefined
- [ ] TASK-003: constitution_version surfacing and live-weight injection point
- [ ] TASK-004: Final Validation
