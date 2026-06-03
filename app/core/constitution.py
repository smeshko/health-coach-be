"""Render the health constitution into the LLM system prompt.

`HEALTH-CONSITTUTION.md` is a Jinja2 template whose numeric constants are
`{{ … }}` placeholders bound to `profile.yaml` (E3·P1 `Profile`). This module
fills it into the **system** prompt, rendered **fresh each call** — caching is
off (LLM.md §2/§5; at ~2 calls/day the prompt-cache TTL never hits), so there is
no memoization here.

The env uses `StrictUndefined` so a missing constant raises `UndefinedError`
rather than rendering a silent blank (epic §4 "no silent blanks"), and
`autoescape=False` because the output is Markdown, not HTML (escaping would
corrupt `&`/`<`/quotes/`−`/`≤` in the prose).

`constitution_version` and the live-weight injection seam are added in TASK-003.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.core.profile import Profile

TEMPLATE_NAME = "constitution.md.j2"

# Loader rooted at this module's `templates/` dir (not cwd) so rendering is
# deterministic under pytest and at runtime, and the template travels with the
# package.
_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=True,
    trim_blocks=False,
)


def render_constitution(profile: Profile) -> str:
    """Render the constitution system prompt fresh from `profile`'s constants.

    Passes the section objects straight through so the template's placeholder
    paths (`thresholds.max_hr`, `zones.z5[1]`, `nutrition.carbs_g_per_kg.hard_low`,
    …) resolve 1:1 off the `Profile` graph. Renders fresh on every call (no
    cache); a missing constant raises `jinja2.UndefinedError`. Takes only a
    `Profile` — live weight is never an argument (it enters via the user
    context, not the system prompt; LLM.md §2).
    """
    return _env.get_template(TEMPLATE_NAME).render(
        athlete=profile.athlete,
        thresholds=profile.thresholds,
        zones=profile.zones,
        nutrition=profile.nutrition,
    )
