# Research: E3·P2 — Constitution template & renderer

Curated findings only — no raw conversation transcripts.

## Key Files & Directories

- `HEALTH-CONSITTUTION.md` (repo root, ~33 KB) — the rulebook prose. **Already written as a Jinja2
  template**: every numeric constant is already an `{{ … }}` placeholder (verified by reading the file).
  E3·P2 lifts this file into the package as the template and writes the renderer that fills it. No prose
  needs rewriting — only the file location/loading is new.
- `app/core/profile.py` (E3·P1, the prior phase) — the typed loader this phase consumes:
  `load_profile(path: Path | None = None) -> Profile`; `Profile` has `.athlete / .thresholds / .zones /
  .nutrition / .meta`; accessor `Profile.zone_bounds() -> dict[str, tuple[int,int]]`; the version is on
  `Profile.meta.constitution_version` (a `str`, e.g. `"v1"`). Zones are `tuple[int,int]` per zone (`z1..z5`).
- `app/core/` — where core primitives live (alongside `settings.py`); the renderer (`constitution.py`) and
  the template (`templates/constitution.md.j2`) go here.
- `tests/core/` — the test package created in E3·P1 (`tests/core/__init__.py`, `test_profile.py`); the new
  renderer tests live as `tests/core/test_constitution.py`.

## Architecture Facts

- **The constitution is the SYSTEM prompt**, rendered fresh from `profile.yaml` each call. The LLM call
  envelope (LLM.md §0, §2): SYSTEM = Jinja2-rendered constitution; USER = computed context JSON (readiness,
  budgets, aggregates, flags, **live weight**); TOOL = structured OutputType.
- **Caching is off** (LLM.md §2, §5; ARCHITECTURE §6): at ~2 calls/day the prompt-cache TTL never hits, so
  the constitution is rendered fresh every call — no cache layer to maintain. → render fresh, no memoization.
- **Live weight is fed via the USER context, NOT baked into the prompt** (LLM.md §2; epic R4; constitution
  §1/§7). The template's §1 "Weight (current)" row is prose ("live → latest HealthKit `body_mass`") with
  **no placeholder**; the live `W` enters the macro math at call time (E8/E9), not at render time. The
  renderer provides the integration seam (a documented place the user context is assembled) but never reads
  weight from `profile.yaml`.
- **The §2 medical block renders as CONTEXT, not a code-enforced layer** (LLM.md §2; ARCHITECTURE §6; epic
  R5; constitution §2 scope note). It is prose the brain weighs; the only code-enforced safety is the §6.2
  training auto-regulation gate. → the medical prose must appear verbatim in the rendered output; no
  denylist, no medical validation here.
- **`constitution_version` stamps each brief** (LLM.md §2; epic R6; MODELS.md DailyBrief
  `data.constitutionVersion`, e.g. `2026-05-01`). The renderer surfaces it from `Profile.meta.
  constitution_version` so the brief layer (E9) can record which snapshot produced it.
- **Placeholders to fill** (constitution §1/§3/§7 + LLM.md §2; epic §3 E3·P2): `athlete.{age, sex,
  height_cm, goal_weight_kg}`; `thresholds.{max_hr, rhr_baseline, hrv_baseline_ms, easy_hr_cap,
  cadence_target_spm}`; `zones.{z1..z5}[0]/[1]`; `nutrition.{activity_factor, deficit_pct,
  protein_g_per_kg, fat_g_per_kg_low, fat_g_per_kg_high, carbs_g_per_kg.{hard_low, hard_high, moderate,
  rest_low, rest_high}, hydration_l_low, hydration_l_high, fiber_g_low, fiber_g_high}`. The template also
  uses one **derived** expression: `{{ thresholds.easy_hr_cap - 8 }}` (constitution §3) — arithmetic on a
  constant, must still resolve under StrictUndefined.
- **3 literal explanatory `{{ … }}` strings** (root `HEALTH-CONSITTUTION.md` lines 11, 38, 281) are prose
  *describing* the templating ("every numeric constant … is written as `{{ … }}`") — NOT real placeholders.
  Jinja2 would try to evaluate the `…` ellipsis and raise `TemplateSyntaxError`, so a byte-identical copy is
  **unparseable**. The `.j2` must wrap exactly those 3 in `{% raw %}…{% endraw %}` (they render back to the
  literal text). This is the only intended divergence of the `.j2` from the root `.md`. (Codex round-2 #1)

## Constraints

- **StrictUndefined** (Jinja2): a missing/unfilled placeholder must raise (`UndefinedError`) at render time
  — never render blank (epic §4; LLM.md §2 "no silent blanks"). This is the primary failure-loudly
  guarantee. Configure the `Environment(undefined=StrictUndefined)`.
- **Render fresh each call** — no cache, no module-level memoization keyed on profile (LLM.md §2, §5).
- **No live/derived value sourced from the template/renderer** — current weight, 30d HRV/RHR baselines,
  per-day metrics come from the DB / user context, never `profile.yaml` (epic R3; DB.md §5 table + ¹). The
  template's live-value rows (VO₂max, sleep, steps, current weight) stay prose snapshots with no placeholder.
- **Field names mirror DB.md §5 / `profile.yaml` keys 1:1** (snake_case). The template's placeholder paths
  must match `Profile`'s attribute paths exactly (e.g. `thresholds.cadence_target_spm`,
  `nutrition.carbs_g_per_kg.hard_low`).
- **Autoescape off / Markdown context** — the output is a Markdown system prompt, not HTML; do **not**
  HTML-escape (would corrupt `&`, `<`, quotes in prose). Set `autoescape=False`.
- Stack (E1·P1): FastAPI, `app/core` primitives, PydanticAI, **Jinja2**, SQLAlchemy/Alembic. Dropped (never
  reference): Postgres/pgvector, Celery, Redis, Supabase, streaming, RAG/vecs.

## Useful Commands

```bash
uv run pytest tests/core/test_constitution.py
uv run ruff check .
# smoke: render the shipped profile and confirm a constant + version surface
uv run python -c "from app.core.constitution import render_constitution, constitution_version; \
from app.core.profile import load_profile; p=load_profile(); \
s=render_constitution(p); assert '192' in s; print(constitution_version(p))"
```

## Uncertainty

- **Where the template file lives & how it is loaded.** Resolved: ship the template inside the package at
  `app/core/templates/constitution.md.j2` and load it via a `FileSystemLoader` rooted at that dir (path
  resolved relative to the module file, not cwd) — so it works from any working directory and is packaged
  with the app. The repo-root `HEALTH-CONSITTUTION.md` stays the human-facing source of truth; the `.j2` is
  its templatized copy (identical prose + placeholders).
- **Whether to keep two copies of the prose in sync** (`HEALTH-CONSITTUTION.md` vs the `.j2`). Resolved for
  this phase: the `.j2` is the rendered artifact's source and a verbatim copy of the root `.md` **except**
  for the 3 `{% raw %}`-escaped literal-delimiter prose lines (above). Drift is guarded three ways: a parse
  test (must compile), a structural §1–§11 section-presence test, and a `.j2`-vs-root equivalence check
  (stripping `{% raw %}`/`{% endraw %}` from the `.j2` yields the root `.md` byte-for-byte). Auto-regenerating
  the `.j2` from the root in a build step is a docs-tooling concern, out of scope here.
- **`easy_hr_cap - 8` derived expression** — resolved: it is plain Jinja2 arithmetic on a filled constant;
  it resolves fine under StrictUndefined (the operand is defined). A test asserts the computed value
  (`146 - 8 = 138`) appears in the output.

## References

- `epics/E03-profile-constitution.md` — §2 R4/R5/R6, §3 E3·P2, §4 acceptance, §6 validation, §7 out-of-scope.
- `docs/architecture/LLM.md` §0 (call envelope), §2 (constitution as system prompt; caching off; live weight
  via user context; `constitutionVersion`; §2 medical = context), §5 (caching off, cost).
- `docs/architecture/ARCHITECTURE.md` §6 (constitution = Jinja2 template rendered fresh; §2 medical = context).
- `docs/architecture/DB.md` §5 (`profile.yaml` block — the exact keys the placeholders bind to; static-vs-live split).
- `HEALTH-CONSITTUTION.md` (repo root) — the templatized rulebook prose (§1 profile, §2 medical, §3 zones, §7 nutrition).
- `.claude/plans/e3-p1-profile-loader/` — the prior phase: `load_profile` / `Profile` contract this renderer consumes.
