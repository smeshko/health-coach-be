# TASK-001: Jinja2 constitution template from HEALTH-CONSITTUTION.md

Depends on: None
Suggested commit: `feat(core): add Jinja2 constitution template from HEALTH-CONSITTUTION.md`

## Goal

Lift `HEALTH-CONSITTUTION.md` into the package as `app/core/templates/constitution.md.j2` — prose verbatim,
numeric constants as `{{ … }}` placeholders bound to the E3·P1 `Profile` attribute paths — so the renderer
(TASK-002) can fill it from `profile.yaml`.

## Files

- `app/core/templates/constitution.md.j2` — new: the templatized rulebook. Copy `HEALTH-CONSITTUTION.md`'s
  prose **verbatim**; keep every numeric constant as an `{{ … }}` placeholder bound to a `Profile` path:
  - `athlete.age`, `athlete.sex`, `athlete.height_cm`, `athlete.goal_weight_kg`
  - `thresholds.max_hr`, `thresholds.rhr_baseline`, `thresholds.hrv_baseline_ms`, `thresholds.easy_hr_cap`,
    `thresholds.cadence_target_spm`, and the derived `thresholds.easy_hr_cap - 8`
  - `zones.z1[0]`/`zones.z1[1]` … `zones.z5[0]`/`zones.z5[1]` (the loader's `tuple[int,int]` bounds)
  - `nutrition.activity_factor`, `nutrition.deficit_pct`, `nutrition.protein_g_per_kg`,
    `nutrition.fat_g_per_kg_low`, `nutrition.fat_g_per_kg_high`,
    `nutrition.carbs_g_per_kg.{hard_low,hard_high,moderate,rest_low,rest_high}`,
    `nutrition.hydration_l_low`, `nutrition.hydration_l_high`, `nutrition.fiber_g_low`, `nutrition.fiber_g_high`
  - **No placeholder** for live values: current weight, VO₂max, sleep, steps, active energy — leave those
    rows as the prose snapshots they already are.
- `tests/core/test_constitution.py` — new (template-shape assertions land here; rendering assertions in TASK-002).

## Acceptance

- [ ] `app/core/templates/constitution.md.j2` exists and contains the §2 medical prose verbatim
      ("Never suggest NSAIDs", "Lactose intolerance", "Biliary dyskinesia", the §2 scope note "not a
      code-enforced compliance layer").
- [ ] Every numeric constant is a `{{ … }}` placeholder bound to a `Profile` path — a static scan asserts
      the template references each required path (`thresholds.max_hr`, `thresholds.easy_hr_cap`,
      `thresholds.cadence_target_spm`, `zones.z5`, `nutrition.protein_g_per_kg`,
      `nutrition.carbs_g_per_kg.hard_low`, `nutrition.hydration_l_low`, `nutrition.fiber_g_low`, …).
- [ ] The template contains **no** live-weight *placeholder* — a scan asserts no `{{ … weight … }}` /
      `{{ … body_mass … }}` placeholder exists. The §1 "Weight (current) → live → latest HealthKit
      `body_mass`" row is **kept verbatim as prose** (the literal string `body_mass` is allowed *outside*
      `{{ }}`); only the `{{ }}`-wrapped form is banned (epic R4 — live weight enters via user context, not
      the prompt).
- [ ] **Structural drift-guard:** the `.j2` contains all major section headers from the source rulebook —
      assert each of `## 1. Athlete profile`, `## 2. Medical constraints`, `## 3. Training zones`,
      `## 4. The workout pool`, `## 5. Weekly planner`, `## 6. Daily adjuster`, `## 7. Nutrition framework`,
      `## 8. Safety, flares`, `## 9. Progression rules`, `## 10. Monthly recompute`, `## 11. Data contract`
      is present, so a `.j2` that silently drops the safety/progression/etc. sections fails (a few §2
      substrings alone would not catch that). (Codex round-1 #3)
- [ ] **The template parses as valid Jinja2** (no `TemplateSyntaxError` when compiled by the env from
      TASK-002) — this is the **primary** structural guard. NB the root `HEALTH-CONSITTUTION.md` contains
      **3 literal explanatory `{{ … }}` strings** (prose *about* the templating mechanism — lines 11, 38,
      281: "every numeric constant … is written as `{{ … }}`"). Those are NOT real placeholders; Jinja2
      would try to evaluate the `…` and raise `TemplateSyntaxError`. The `.j2` must **escape** exactly those
      3 occurrences (wrap each literal `{{ … }}` example in `{% raw %}…{% endraw %}`) so the file parses,
      while every one of the 21 real placeholders renders normally. A test asserts the rendered output still
      shows the literal text "`{{ … }}`" in those 3 prose spots (the escaping is transparent to the reader).
      (Codex round-2 #1)

## Steps

### RED
- [ ] In `tests/core/test_constitution.py`, add a `template_source` fixture that reads the `.j2` file text;
      assert the §2 medical prose substrings and the §2 scope note are present; assert the required
      placeholder paths appear in the source (`{{ thresholds.max_hr }}`, `zones.z5`,
      `nutrition.carbs_g_per_kg.hard_low`, …); assert no weight is inside a `{{ }}` placeholder
      (regex `\{\{[^}]*(weight|body_mass)[^}]*\}\}` matches nothing) while the literal `body_mass` prose row
      still survives the copy; assert every major section header (§1–§11) is present (structural drift-guard);
      assert the `.j2` **compiles** under the StrictUndefined env (no `TemplateSyntaxError`); and assert the
      3 literal `{{ … }}` prose examples are each wrapped in `{% raw %}…{% endraw %}` in the source and
      render back to the literal `{{ … }}` text.

### GREEN
- [ ] Create `app/core/templates/constitution.md.j2` by copying `HEALTH-CONSITTUTION.md` (it is already
      templatized — its 21 real constants are already `{{ … }}` placeholders matching the `profile.yaml`
      keys). **The only edit to the copy:** escape the 3 literal explanatory `{{ … }}` strings (lines 11,
      38, 281 of the root file — prose describing the templating, not real placeholders) by wrapping each in
      `{% raw %}{{ … }}{% endraw %}` so Jinja2 doesn't try to evaluate the `…`. Confirm the 21 placeholder
      paths match the E3·P1 `Profile` attribute graph exactly (snake_case, `zones.zN[0]/[1]`,
      `nutrition.carbs_g_per_kg.*`) and the file compiles under the StrictUndefined env.

### REFACTOR
- [ ] Run `diff HEALTH-CONSITTUTION.md app/core/templates/constitution.md.j2` and confirm the **only**
      differences are the 3 escaped literal-delimiter prose lines (11, 38, 281 — each now wrapped in
      `{% raw %}…{% endraw %}`). Everything else — all prose and all 21 real placeholders — is identical. A
      programmatic check: stripping the `{% raw %}`/`{% endraw %}` tags from the `.j2` must yield a file
      byte-identical to the root `.md`. Fix any placeholder path that doesn't bind to a `Profile` attribute.

## Notes

`HEALTH-CONSITTUTION.md` is **already a Jinja2 template** — its 21 real constants are already `{{ … }}`
placeholders matching the DB.md §5 `profile.yaml` keys. This task is mostly *copying it into the package* and
confirming every placeholder path binds to the E3·P1 `Profile` graph (`athlete.*`, `thresholds.*`,
`zones.zN[i]`, `nutrition.*`). Do **not** rewrite prose or templatize live-value snapshots. The derived
`{{ thresholds.easy_hr_cap - 8 }}` expression stays as-is (it resolves under StrictUndefined because the
operand is defined).

**The one required edit (Codex round-2 #1):** the root file has **3 literal explanatory `{{ … }}` strings**
(lines 11, 38, 281) that are prose *describing* the templating mechanism — NOT real placeholders. Jinja2
would try to evaluate the `…` ellipsis and raise `TemplateSyntaxError`, so a byte-identical copy is
**unparseable**. Escape exactly those 3 with `{% raw %}{{ … }}{% endraw %}`; they then render back to the
literal `{{ … }}` text (transparent to the reader) and the file parses. This is the only place the `.j2`
diverges from the root `.md`.
