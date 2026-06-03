# TASK-002: Renderer filling placeholders from profile.yaml with StrictUndefined

Depends on: TASK-001
Suggested commit: `feat(core): add constitution renderer with StrictUndefined`

## Goal

Add `render_constitution(profile: Profile) -> str` that fills the template from the E3·P1 `Profile` under a
`StrictUndefined` Jinja2 environment (`autoescape=False`, Markdown), rendering **fresh each call** so a
missing constant raises instead of blanking.

## Files

- `app/core/constitution.py` — new: the renderer.
  - Module-private `_env` = `jinja2.Environment(loader=FileSystemLoader(Path(__file__).parent /
    "templates"), undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True,
    trim_blocks=False)`. (Loader rooted at `__file__`, not cwd.)
  - `TEMPLATE_NAME = "constitution.md.j2"`.
  - `render_constitution(profile: Profile) -> str` — `_env.get_template(TEMPLATE_NAME).render(athlete=
    profile.athlete, thresholds=profile.thresholds, zones=profile.zones, nutrition=profile.nutrition)`,
    returning the string. Passes the section objects so the template's `thresholds.max_hr`, `zones.z5[1]`,
    `nutrition.carbs_g_per_kg.hard_low`, etc. resolve directly off the `Profile` graph. **No caching** — a
    fresh `get_template().render()` on every call.
- `tests/core/test_constitution.py` — extend with rendering tests.

## Acceptance

- [ ] `render_constitution(load_profile())` (the shipped E3·P1 example) returns a non-empty `str` with no
      error and **no unresolved real placeholder** in the output — i.e. no `{{ athlete.* }}` /
      `{{ thresholds.* }}` / `{{ zones.* }}` / `{{ nutrition.* }}` survives. (The only `{{ … }}` text left is
      the 3 literal explanatory examples that TASK-001 `{% raw %}`-escaped; the check must allow those.)
- [ ] Output contains the live constants verbatim: `max_hr` `192`, the `z5` bounds `177`/`192`,
      `easy_hr_cap` `146`, the derived `easy_hr_cap - 8` = `138`, the cadence target `172`, and a nutrition
      constant (`protein_g_per_kg` `1.8`, a carb multiplier).
- [ ] **StrictUndefined fails loud:** rendering with a `Profile`/template where a placeholder is unfilled
      raises `jinja2.UndefinedError` (e.g. render a minimal probe template
      `{{ thresholds.does_not_exist }}` through `_env`, or render the real template against a section object
      missing an attribute) — never a blank. Assert `_env.undefined is StrictUndefined`.
- [ ] **Autoescape off:** a prose substring with special chars ("180−age", "≤", "Z1–Z2") appears unescaped.
- [ ] **Fresh each call:** two renders with two `Profile`s differing only in `thresholds.max_hr` produce
      outputs that differ in that value (no stale memoized result).

## Steps

### RED
- [ ] Add tests: load the shipped `profile.yaml` via `load_profile()`; assert `render_constitution(p)` is a
      non-empty str with no unresolved real placeholder (no `{{ athlete.* / thresholds.* / zones.* /
      nutrition.* }}`; the 3 escaped literal `{{ … }}` examples are allowed); assert `"192"`, `"177"`,
      `"146"`, `"138"`, `"172"`, `"1.8"` present;
      assert the special-char prose survives; build a second `Profile` (copy with `max_hr` changed) and
      assert the two renders differ; assert a missing-placeholder render raises `UndefinedError` and
      `_env.undefined is StrictUndefined`.

### GREEN
- [ ] Implement `app/core/constitution.py` with the `StrictUndefined` env (`autoescape=False`,
      `FileSystemLoader` at `__file__`'s `templates/`) and `render_constitution`.

### REFACTOR
- [ ] Keep the env module-private and the render path allocation-light but **un-cached**; type hints on the
      public function; no live/derived value read anywhere.

## Notes

The fail-loud guarantee (epic §4 "no silent blanks") **is** `StrictUndefined` — do not use plain `Undefined`
or a `default()` filter anywhere. `autoescape=False` because the output is a Markdown system prompt, not HTML
(escaping would corrupt `&`/`<`/quotes/`−`/`≤` in the prose). **No caching/memoization** — LLM.md §2/§5
decide caching off; at ~2 calls/day the TTL never hits, so render fresh every call. Pass `Profile`'s section
objects straight through so placeholder paths bind 1:1 (no remap layer to drift). `constitution_version` and
the live-weight seam are TASK-003.
