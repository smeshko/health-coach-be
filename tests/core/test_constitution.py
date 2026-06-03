"""Constitution template + renderer tests (E3·P2).

The constitution is the LLM **system** prompt, rendered fresh from `profile.yaml`
each call (LLM.md §0/§2). These tests pin: the `.j2` is the root rulebook
verbatim (only the 3 literal explanatory `{{ … }}` prose strings escaped via
`{% raw %}`), every real placeholder fills from the E3·P1 `Profile` under
`StrictUndefined` (a missing constant fails loud), the §2 medical block renders
as context, live weight is never baked into the prompt, and rendering is fresh
each call (caching off).
"""

import re
from pathlib import Path

import app.core
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.core.profile import load_profile

TEMPLATES_DIR = Path(app.core.__file__).parent / "templates"
TEMPLATE_PATH = TEMPLATES_DIR / "constitution.md.j2"
TEMPLATE_NAME = "constitution.md.j2"
ROOT_CONSTITUTION = Path(app.core.__file__).resolve().parents[2] / "HEALTH-CONSITTUTION.md"

# Major section headers (substrings of the actual `## N. …` lines) — a drift
# guard so a `.j2` that silently drops safety/progression/etc. fails.
SECTION_HEADERS = (
    "## 1. Athlete profile",
    "## 2. Medical constraints",
    "## 3. Training zones",
    "## 4. The workout pool",
    "## 5. Weekly planner",
    "## 6. Daily adjuster",
    "## 7. Nutrition framework",
    "## 8. Safety, flares",
    "## 9. Progression rules",
    "## 10. Monthly recompute",
    "## 11. Data contract",
)

# Every real constant the template binds to the Profile attribute graph.
REQUIRED_PLACEHOLDER_PATHS = (
    "athlete.age",
    "athlete.sex",
    "athlete.height_cm",
    "athlete.goal_weight_kg",
    "thresholds.max_hr",
    "thresholds.rhr_baseline",
    "thresholds.hrv_baseline_ms",
    "thresholds.easy_hr_cap",
    "thresholds.cadence_target_spm",
    "zones.z1",
    "zones.z5",
    "nutrition.activity_factor",
    "nutrition.deficit_pct",
    "nutrition.protein_g_per_kg",
    "nutrition.fat_g_per_kg_low",
    "nutrition.fat_g_per_kg_high",
    "nutrition.carbs_g_per_kg.hard_low",
    "nutrition.carbs_g_per_kg.rest_high",
    "nutrition.hydration_l_low",
    "nutrition.fiber_g_low",
)

# Distinctive §2 medical prose that must render as context (epic R5).
MEDICAL_SUBSTRINGS = (
    "Never suggest NSAIDs",
    "Lactose intolerance",
    "Biliary dyskinesia",
    "not a code-enforced compliance layer",
)


def _local_env() -> Environment:
    """A StrictUndefined env mirroring TASK-002's renderer env, for parse/render
    checks of the template in isolation."""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=False,
    )


def _render_with_profile(env: Environment) -> str:
    p = load_profile()
    return env.get_template(TEMPLATE_NAME).render(
        athlete=p.athlete, thresholds=p.thresholds, zones=p.zones, nutrition=p.nutrition
    )


# --- TASK-001: template shape, verbatim-copy drift guard, escaped literals ---


def test_template_file_exists():
    assert TEMPLATE_PATH.is_file()


def test_medical_block_present():
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    for substring in MEDICAL_SUBSTRINGS:
        assert substring in source, f"missing §2 medical prose: {substring!r}"


def test_required_placeholder_paths_present():
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    for path in REQUIRED_PLACEHOLDER_PATHS:
        assert path in source, f"missing placeholder path: {path}"


def test_all_section_headers_present():
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    for header in SECTION_HEADERS:
        assert header in source, f"missing section header: {header}"


def test_no_live_weight_placeholder():
    # Live weight enters via the user context, never the system prompt (epic R4).
    # Ban any `{{ … }}` referencing live weight (`body_mass`/`current_weight`, or
    # a `weight` token that is not the static `goal_weight_kg`). The §1 "Weight
    # (current) → latest HealthKit `body_mass`" prose row (outside `{{ }}`) stays.
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    placeholders = re.findall(r"\{\{[^}]*\}\}", source)
    live_weight = [
        p
        for p in placeholders
        if re.search(r"body_mass|current_weight", p)
        or ("weight" in p and "goal_weight_kg" not in p)
    ]
    assert not live_weight, f"live-weight placeholder(s) found: {live_weight}"
    assert "{{ athlete.goal_weight_kg }}" in source  # the static goal weight is allowed
    assert "latest HealthKit `body_mass`" in source  # §1 prose row survives verbatim


def test_template_compiles_under_strict_undefined():
    # Primary structural guard: the 3 literal explanatory `{{ … }}` prose strings
    # must be `{% raw %}`-escaped, else Jinja2 raises TemplateSyntaxError here.
    _local_env().get_template(TEMPLATE_NAME)


def test_literal_placeholder_examples_escaped_and_render_back():
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert source.count("{% raw %}{{ … }}{% endraw %}") == 3
    rendered = _render_with_profile(_local_env())
    # The escaping is transparent: the literal `{{ … }}` text survives to output.
    assert rendered.count("{{ … }}") == 3


def test_j2_equals_root_constitution_minus_raw_tags():
    # The `.j2` is the root rulebook verbatim except the 3 escaped prose lines —
    # stripping the `{% raw %}`/`{% endraw %}` tags must yield the root byte-for-byte.
    j2 = TEMPLATE_PATH.read_text(encoding="utf-8")
    root = ROOT_CONSTITUTION.read_text(encoding="utf-8")
    stripped = re.sub(r"\{%\s*raw\s*%\}|\{%\s*endraw\s*%\}", "", j2)
    assert stripped == root
