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

# `date` is aliased so a wire field *named* `date` can be typed `date_type` without the
# field name shadowing the type at annotation/forward-ref resolution.
from datetime import date as date_type
from datetime import datetime

from app.api.schemas.base import CamelModel
from app.api.schemas.narrative import NarrativeSection
from app.core.enums import DayType, ReadinessBand, WorkoutCard
from app.services.derive.session import SessionBlock
from app.services.macros import MacroFocus

__all__ = [
    "SessionPick",
    "DailyBriefLLMOutput",
    "NarrativeSection",
    "IntakeVsTarget",
    "IntakeSummary",
    "ReadinessPenalty",
    "Readiness",
    "SafetyGate",
    "DailyBriefRequest",
    "DailyBriefData",
    "DailyBrief",
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

    date: date_type
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


# --------------------------------------------------------------------------- #
# POST /brief/daily — request + response wire models (E11·P3; MODELS DailyBrief).
# --------------------------------------------------------------------------- #
class ReadinessPenalty(CamelModel):
    """One itemised readiness penalty (MODELS `ReadinessPenalty`) — wire shape.

    The computation lives in the E8·P1 `app/services/readiness.py` frozen dataclass; this
    `CamelModel` is the JSON-able wire/round-trip form the daily response carries.
    """

    factor: str
    points: int


class Readiness(CamelModel):
    """The readiness result (MODELS `Readiness`) — wire shape (the E8·P1 dataclass twin)."""

    score: int
    band: ReadinessBand
    penalties: list[ReadinessPenalty]


class SafetyGate(CamelModel):
    """The safety-gate result (MODELS `SafetyGate`) — wire shape (the E8·P2 dataclass twin).

    `overrideTo` is the forced recovery card on a trip (`null` when not triggered).
    """

    triggered: bool
    reasons: list[str]
    override_to: WorkoutCard | None = None


class DailyBriefRequest(CamelModel):
    """The ``POST /brief/daily`` request body (MODELS ``DailyBriefRequest``).

    ``date`` is a native Pydantic ``date`` — a malformed value (``"2026-13-40"``,
    ``"garbage"``) raises at request validation → ``422`` ``validation_error`` (no regex
    needed, unlike the weekly ``YYYY-Www`` string). ``None``/absent means "today",
    resolved server-side (Europe/Sofia).
    """

    date: date_type | None = None


class DailyBriefData(CamelModel):
    """The ``DailyBrief.data`` sub-object (MODELS ``DailyBrief`` ``data``).

    Every field except the endpoint-stamped ``date``/``generatedAt``/``cached``/
    ``constitutionVersion`` is carried through from the workflow-produced/cached structured
    data; ``intakeYesterday`` was derived by the E11·P2 ``DeriveSessionNode``.
    """

    date: date_type
    readiness: Readiness
    safety_gate: SafetyGate
    session: SessionBlock
    alternatives: list[SessionBlock]
    skip_ok: bool
    macro_focus: MacroFocus
    intake_yesterday: IntakeSummary | None = None
    generated_at: datetime
    cached: bool
    constitution_version: str | None = None


class DailyBrief(CamelModel):
    """The ``POST /brief/daily`` response (MODELS ``DailyBrief``) — ``{ data, narrative }``.

    A tripped safety gate is a **normal** ``DailyBrief`` (``safetyGate.triggered=true``, a
    code-written ``narrative``, the override ``session``, empty ``alternatives``) — never an
    error envelope.
    """

    data: DailyBriefData
    narrative: list[NarrativeSection]
