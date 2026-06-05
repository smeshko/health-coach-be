"""The daily LLM output contract — the strict `OutputType` `TuneSessionNode`
returns (E11·P1 TASK-001; MODELS `DailyBriefLLMOutput`/`SessionPick`; LLM §1/§1.1).

`DailyBriefLLMOutput { session, alternatives, skipOk, dayType, narrative }` over
slim `SessionPick`s and the **shared** `NarrativeSection` — **only genuine picks +
the `dayType` nutrition lever + `skipOk` + prose**. Every card-derived field
(`intensity`/`zoneTarget`/`hrCapBpm`/`cadenceSpm`/`flags`) is filled downstream by
E7·P2's `SessionPick → SessionBlock` expander, and every number
(`readiness`/`safetyGate`/`macroFocus`/`intakeYesterday`) is code in E11·P2/E11·P3
(derive-don't-emit; MODELS rule 2; LLM §3; CARDS §0). So the model output is
**slim by design**.

`dayType` is the LLM's **one** nutrition lever (LLM §1.1): emitted as a `DayType`,
but its **floor** (a hard/long card floors it at `hard`) is a **validator** rule
(TASK-003 / E7·P3 `day_type_below_floor`), kept out of the type so an under-fuel is
a `ModelRetry` the model sees, not a silent default. Likewise the `alternatives`
≤ 2 cap and the daily narrative subset (`summary|session|nutrition|caution` =
`NarrativeType` minus `plan`) are validator rules — so the Pydantic types stay
permissive (`list[SessionPick]`, `type: NarrativeType`).

Both models subclass the shared `CamelModel` (`app/api/schemas/base.py`) so the
wire JSON is camelCase and Python stays snake_case (MODELS Casing); they reference
E7·P1's `WorkoutCard`/`DayType`/`NarrativeType` enums and redefine none.
`NarrativeSection` is the **one** class shared with the weekly output (re-homed to
`app/api/schemas/narrative.py`). Pure wire models — no FastAPI route, no
PydanticAI/LLM import.
"""

from datetime import date

from app.api.schemas.base import CamelModel
from app.api.schemas.narrative import NarrativeSection
from app.core.enums import DayType, WorkoutCard

__all__ = [
    "SessionPick",
    "DailyBriefLLMOutput",
    "NarrativeSection",
    "IntakeVsTarget",
    "IntakeSummary",
]


class IntakeVsTarget(CamelModel):
    """Yesterday's logged intake vs the day's target (MODELS `IntakeSummary.vsTarget`).

    `caloriesPct` = consumed ÷ target calories; `proteinHit` = the logged protein met
    the day's protein floor. Both code-derived (no LLM).
    """

    calories_pct: float
    protein_hit: bool


class IntakeSummary(CamelModel):
    """What was actually **logged** for a day, vs target (MODELS `IntakeSummary`).

    Code-derived from `daily_metrics` (the ingested HealthKit dietary records); the
    daily brief ships **yesterday's**. Every macro total is nullable (`null` when
    nothing was logged); `vsTarget` reports the calorie ratio + protein-floor hit.
    """

    date: date
    calories_kcal: int | None = None
    protein_g: int | None = None
    carbs_g: int | None = None
    fat_g: int | None = None
    fiber_g: int | None = None
    water_l: float | None = None
    vs_target: IntakeVsTarget


class SessionPick(CamelModel):
    """The slim daily pick the LLM emits (MODELS `SessionPick` — "what the LLM emits").

    Exactly the three LLM fields: the `card` and the `durationMin[Low|High]` dose
    band (the LLM's one numeric pick within the card's band). **No** card-derived
    field (`intensity`/`zoneTarget`/`hrCapBpm`/`cadenceSpm`/`flags` — E7·P2's
    expander fills those; derive-don't-emit) and **no `suggestedDay`** (that is a
    weekly `PlannedPick` field — a daily pick is for today).
    """

    card: WorkoutCard
    duration_min_low: int | None = None
    duration_min_high: int | None = None


class DailyBriefLLMOutput(CamelModel):
    """The strict `OutputType` `TuneSessionNode` returns (MODELS `DailyBriefLLMOutput`).

    **Exactly** these five fields — the `session` + `alternatives` slim picks, the
    `skipOk` flag, the guarded `dayType` lever, and the `narrative`. No
    `readiness`/`safetyGate`/`macroFocus`/`intakeYesterday`/card-derived field (all
    computed/merged downstream — MODELS). The `alternatives` ≤ 2 cap, the `dayType`
    fuel-floor, and the daily narrative subset are policed by `validate_daily`
    (E7·P3) + the thin daily narrative check (TASK-003), **not** Pydantic
    `max_length`/`Literal`/default — so a miss is a `ModelRetry`, not a silent 422
    (the lists / the `DayType` stay permissive here).
    """

    session: SessionPick
    alternatives: list[SessionPick]
    skip_ok: bool
    day_type: DayType
    narrative: list[NarrativeSection]
