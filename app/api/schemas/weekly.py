"""The weekly LLM output contract — the strict `OutputType` `GeneratePlanNode`
returns (E10·P1 TASK-001; MODELS `WeeklyPlanLLMOutput`; LLM §1).

`WeeklyPlanLLMOutput { core, extras, narrative }` over slim `PlannedPick`s and
`NarrativeSection`s — **only genuine picks + prose**. Every card-derived field
(`tier`/`intensity`/`zoneTarget`/`isHardDay`/`flags`) is filled downstream by
E7·P2's `PlannedPick → PlannedSession` expander, and every number
(`targets`/`nutrition`/`budgets`) is code in E10·P2 (derive-don't-emit; MODELS
rule 2; LLM §3). So the model output is **slim by design** and the validation
surface collapses to a handful of judgment checks (LLM §4).

The 2–3 core / 1–2 extras count invariant and the weekly `plan|session|nutrition`
narrative subset (LLM §1) are policed in the **validator** path (E10·P1 TASK-003 /
E7·P3 `validate_weekly`), **not** as Pydantic `min_length`/`Literal` constraints —
so a miss is a `ModelRetry` the model sees, not a silent 422 (DECISIONS Decision
1). The Pydantic types therefore stay permissive (`list[PlannedPick]`, `type:
NarrativeType`).

All three subclass the shared `CamelModel` (`app/api/schemas/base.py`) so the wire
JSON is camelCase and Python stays snake_case (MODELS Casing); they reference
E7·P1's `WorkoutCard`/`Weekday`/`NarrativeType` enums and redefine none. Pure wire
models — no FastAPI route, no PydanticAI/LLM import. (`NarrativeSection` lives here
for the weekly output; E11's daily output imports or re-homes it — RESEARCH
Uncertainty.)
"""

from datetime import date, datetime

from pydantic import field_validator

from app.api.schemas.base import CamelModel

# `NarrativeSection` is re-homed to the shared `narrative` module (E11·P1) so the
# weekly and daily outputs share the **one** class; imported here so existing
# `app.api.schemas.weekly.NarrativeSection` references keep resolving.
from app.api.schemas.narrative import NarrativeSection
from app.core.enums import Weekday, WorkoutCard
from app.services.derive.plan import PlannedSession
from app.services.macros import WeeklyNutrition
from app.services.targets import WeeklyTargets

__all__ = [
    "NarrativeSection",
    "PlannedPick",
    "WeeklyPlanLLMOutput",
    "WeeklyBriefRequest",
    "WeeklyBudgets",
    "WeeklyPlanData",
    "WeeklyPlan",
]


class PlannedPick(CamelModel):
    """The slim weekly pick the LLM emits (MODELS `PlannedPick` — "what the LLM emits").

    Exactly the four LLM fields: the `card`, the `suggestedDay` sequencing hint
    (`Weekday | null` — "not a fixed calendar"), and the `durationMin[Low|High]`
    dose band (the LLM's one numeric pick). **No** card-derived field
    (`tier`/`intensity`/`zoneTarget`/`isHardDay`/`flags`) — E7·P2's expander fills
    those (derive-don't-emit; MODELS rule 2; LLM §3).
    """

    card: WorkoutCard
    suggested_day: Weekday | None = None
    duration_min_low: int | None = None
    duration_min_high: int | None = None


class WeeklyPlanLLMOutput(CamelModel):
    """The strict `OutputType` `GeneratePlanNode` returns (MODELS `WeeklyPlanLLMOutput`).

    **Exactly** these three fields — `core`/`extras` of slim `PlannedPick`s and the
    `narrative`. No `targets`/`nutrition`/`budgets`/card-derived field (all computed
    downstream — MODELS). The 2–3 core / 1–2 extras count is policed by
    `validate_weekly` (E7·P3 `core_size`/`extras_size`), not a Pydantic
    `min_length`/`max_length`, so a bad count is a `ModelRetry`, not a 422
    (DECISIONS Decision 1) — the lists stay permissive here.
    """

    core: list[PlannedPick]
    extras: list[PlannedPick]
    narrative: list[NarrativeSection]


# --------------------------------------------------------------------------- #
# POST /brief/weekly — request + response wire models (E10·P3; MODELS).
# --------------------------------------------------------------------------- #
class WeeklyBriefRequest(CamelModel):
    """The ``POST /brief/weekly`` request body (MODELS ``WeeklyBriefRequest``).

    ``iso_week`` is ``YYYY-Www`` or ``None`` (absent → the current Europe/Sofia ISO week,
    resolved server-side in the route — never trusted from the client). The validator
    **parses** the week with ``date.fromisocalendar`` (not a shape-only regex), so a
    malformed shape **or** an out-of-range week (``2026-W00``/``2026-W54``/an invalid
    ``W53`` for a 52-week year) raises at request-validation time → ``422``
    ``validation_error`` via the E1 handler, never reaching the route's later
    ``date.fromisocalendar`` (which would otherwise ``ValueError`` → ``500``) — codex
    round-1 #4.
    """

    iso_week: str | None = None

    @field_validator("iso_week")
    @classmethod
    def _validate_iso_week(cls, value: str | None) -> str | None:
        if value is None:
            return None
        year_str, _, week_str = value.partition("-W")
        if not year_str or not week_str or not week_str.isdigit() or not year_str.isdigit():
            raise ValueError("isoWeek must be 'YYYY-Www'")
        # Parsing the Monday rejects out-of-range weeks (W00, W54, an invalid W53).
        date.fromisocalendar(int(year_str), int(week_str), 1)
        return value


class WeeklyBudgets(CamelModel):
    """The §5.1 weekly budget envelope (MODELS ``WeeklyBudgets``) — the wire shape.

    ``WeeklyBudgets`` is a frozen ``app.core.constraints`` dataclass (not a wire model),
    serialised into ``plans.payload`` via ``dataclasses.asdict`` (snake_case keys); this
    ``CamelModel`` accepts that snake_case input (``populate_by_name``) and re-emits
    camelCase on the wire. ``long_run_km`` is nullable (no prior long-run history).
    """

    hard_days: int
    strength_sessions: int
    long_run_km: float | None = None
    deload: bool


class WeeklyPlanData(CamelModel):
    """The ``WeeklyPlan.data`` sub-object (MODELS ``WeeklyPlan`` ``data``).

    The code budgets + the LLM picks expanded (``core``/``extras``) + derived
    targets/nutrition + the endpoint-stamped ``isoWeek``/``weekStart`` (Monday of the ISO
    week, Europe/Sofia)/``generatedAt``/``cached``/``constantsRecomputed``.
    """

    iso_week: str
    week_start: date
    budgets: WeeklyBudgets
    core: list[PlannedSession]
    extras: list[PlannedSession]
    targets: WeeklyTargets
    nutrition: WeeklyNutrition
    constants_recomputed: bool
    generated_at: datetime
    cached: bool


class WeeklyPlan(CamelModel):
    """The ``POST /brief/weekly`` response (MODELS ``WeeklyPlan``) — ``{ data, narrative }``."""

    data: WeeklyPlanData
    narrative: list[NarrativeSection]
