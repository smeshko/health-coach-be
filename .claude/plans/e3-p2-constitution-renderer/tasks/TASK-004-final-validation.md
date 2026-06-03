# TASK-004: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for e3-p2-constitution-renderer`

## Goal

Confirm every PLAN.md acceptance criterion is met with a concrete, non-circular check (named command or
test): the template fills from the shipped `profile.yaml`, a missing constant fails loud via
`StrictUndefined`, the live constants and §2 medical prose appear in the output, `constitution_version` is
surfaced, live weight is not baked into the prompt, the render is fresh each call, and prose special chars
survive (autoescape off).

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked.
- [ ] **Lint:** `uv run ruff check .` passes with no issues.
- [ ] **Tests:** `uv run pytest tests/core/test_constitution.py` passes (template + renderer tests green).

### Acceptance-criteria mapping (1:1, concrete)

- [ ] **Every placeholder is filled from a sample profile** — `uv run pytest tests/core/test_constitution.py
      -k "render and (full or shipped or example)"` proves `render_constitution(load_profile())` returns a
      non-empty str with **no unresolved real placeholder** (no `{{ athlete.* / thresholds.* / zones.* /
      nutrition.* }}` survives; the 3 `{% raw %}`-escaped literal `{{ … }}` examples are allowed); **also**
      `uv run python -c "import re; from app.core.constitution import render_constitution; from
      app.core.profile import load_profile; s=render_constitution(load_profile()); assert s and not
      re.search(r'\{\{\s*(athlete|thresholds|zones|nutrition)\.', s); print(len(s))"` exits 0. (epic §4, §6)
- [ ] **A deliberately missing constant fails loudly (StrictUndefined)** — `uv run pytest
      tests/core/test_constitution.py -k "strict or undefined or missing"` proves an unfilled placeholder
      raises `jinja2.UndefinedError` and that `app.core.constitution._env.undefined is StrictUndefined`.
      (epic §4; LLM.md §2)
- [ ] **Rendered output contains the live constants** — `uv run pytest tests/core/test_constitution.py -k
      "constants or values"` proves `"192"` (max_hr), `"177"`/`"192"` (z5 bounds), `"146"` (easy_hr_cap),
      `"138"` (the derived `easy_hr_cap - 8`), `"172"` (cadence target), and a nutrition constant (`"1.8"`
      protein / a carb multiplier) appear in the rendered output. (epic §4; constitution §1/§3/§7)
- [ ] **The §2 medical block renders as prose context** — `uv run pytest tests/core/test_constitution.py -k
      "medical"` proves `"Never suggest NSAIDs"`, `"Lactose intolerance"`, `"Biliary dyskinesia"`, and the
      §2 scope note `"not a code-enforced compliance layer"` appear in the rendered output. (epic R5;
      ARCHITECTURE §6; LLM.md §2)
- [ ] **Template parses & no prose section silently dropped (drift-guard)** — `uv run pytest
      tests/core/test_constitution.py -k "parse or sections or drift or headers"` proves the `.j2` compiles
      under the StrictUndefined env (no `TemplateSyntaxError` — the 3 literal `{{ … }}` prose examples are
      `{% raw %}`-escaped) and all major section headers `## 1.`–`## 11.` are present in the rendered output
      (so a `.j2` missing safety/progression/etc. fails); **also** the `.j2`-vs-root equivalence check —
      `diff HEALTH-CONSITTUTION.md app/core/templates/constitution.md.j2` differs **only** in the 3 escaped
      prose lines, verified by `uv run python -c "import re; r=open('HEALTH-CONSITTUTION.md').read();
      j=open('app/core/templates/constitution.md.j2').read(); j2=re.sub(r'\{%\s*raw\s*%\}|\{%\s*endraw\s*%\}',
      '', j); assert j2 == r, 'j2 (minus raw tags) must equal root .md'; print('equivalent')"` exiting 0.
      (Codex round-1 #3, round-2 #1; ARCHITECTURE §6)
- [ ] **`constitution_version` is surfaced** — `uv run pytest tests/core/test_constitution.py -k "version"`
      proves `constitution_version(load_profile()) == "v1"` and equals `load_profile().meta.constitution_version`;
      **also** `uv run python -c "from app.core.constitution import constitution_version; from
      app.core.profile import load_profile; print(constitution_version(load_profile()))"` prints `v1`.
      (epic R6; LLM.md §2)
- [ ] **Live weight is NOT baked into the prompt** — `uv run pytest tests/core/test_constitution.py -k
      "weight or seam or context"` proves `inspect.signature(render_constitution)` has exactly one param
      (`profile`, no weight), a sentinel live weight (`"83.4"`) passed only to the user-context seam does
      **not** appear in the rendered system prompt, and the live-weight seam (`LiveContext` /
      `build_user_context`) exists and carries the weight + `constitution_version` as a payload distinct
      from the system prompt; **also** a no-weight-placeholder check —
      `! grep -nE '\{\{[^}]*(body_mass|weight|current_weight)[^}]*\}\}' app/core/templates/constitution.md.j2`
      finds nothing (bans weight inside `{{ … }}` placeholders only — the literal "body_mass" / "current"
      weight prose row from the verbatim §1 copy is allowed) and `! grep -nE "render\(.*weight|weight=" \
      app/core/constitution.py` finds no weight passed into `render`. (epic R4; LLM.md §2; DB.md §5)
- [ ] **Renders fresh each call (no caching)** — `uv run pytest tests/core/test_constitution.py -k "fresh or
      cache or twice"` proves two renders with two `Profile`s differing only in `max_hr` produce outputs
      differing in that value (no stale memoized result). (LLM.md §2, §5; epic R4)
- [ ] **Prose/special chars survive (autoescape off)** — `uv run pytest tests/core/test_constitution.py -k
      "escape or prose or chars"` proves a special-char prose substring (`"180−age"` / `"≤"` / `"Z1–Z2"`)
      appears unescaped in the rendered output. (Decision; constitution prose)
- [ ] **Lint + suite** — `uv run ruff check .` and `uv run pytest tests/core/test_constitution.py` both pass.

- [ ] `PLAN.md` acceptance criteria all met (each mapped above).
