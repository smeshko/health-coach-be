"""Card-system enums (E7·P1 TASK-001).

The seven card-system enums, each a ``class X(str, Enum)`` (the repo convention,
see ``app/api/errors.py:ErrorCode``) whose member ``.value`` is the wire string.
``str``-subclassing makes a member equal to and round-trippable from its wire
string (``WorkoutCard.easy_run == "easy_run"``; ``WorkoutCard("vo2") is
WorkoutCard.vo2``), which the rest of the system — and ``CARD_META``'s keying —
relies on.

Value sets are transcribed **verbatim** from ``docs/architecture/MODELS.md``
§ Enums. ``RecordType`` (a HealthKit-sample taxonomy) is **owned by E5**, a
forward dependency not merged in this checkout — it is deliberately **not**
defined here.
"""

from enum import Enum


class Zone(str, Enum):
    """Heart-rate / effort zone (MODELS § Enums)."""

    z1 = "z1"
    z2 = "z2"
    z3 = "z3"
    z4 = "z4"
    z5 = "z5"


class Intensity(str, Enum):
    """Session intensity (MODELS § Enums); ``quality`` is the "hard" intensity."""

    easy = "easy"
    quality = "quality"
    recovery = "recovery"


class DayType(str, Enum):
    """Nutrition carb-cycling axis (MODELS § Enums; §7.3)."""

    hard = "hard"
    moderate = "moderate"
    rest = "rest"


class Tier(str, Enum):
    """Plan tier (MODELS § Enums) — singular ``extra``, not ``extras``."""

    core = "core"
    extra = "extra"


class Weekday(str, Enum):
    """Day of week (MODELS § Enums)."""

    mon = "mon"
    tue = "tue"
    wed = "wed"
    thu = "thu"
    fri = "fri"
    sat = "sat"
    sun = "sun"


class NarrativeType(str, Enum):
    """Coach-prose section kind (MODELS § Enums)."""

    summary = "summary"
    session = "session"
    nutrition = "nutrition"
    caution = "caution"
    plan = "plan"


class WorkoutCard(str, Enum):
    """The 20 prescribable workout cards (MODELS § Enums; CARDS.md §1)."""

    easy_run = "easy_run"
    long_run = "long_run"
    progression_run = "progression_run"
    active_recovery = "active_recovery"
    threshold = "threshold"
    vo2 = "vo2"
    strides = "strides"
    hiit = "hiit"
    jump_rope = "jump_rope"
    steady_cardio = "steady_cardio"
    strength_push = "strength_push"
    strength_pull = "strength_pull"
    strength_lower = "strength_lower"
    strength_full = "strength_full"
    boxing = "boxing"
    boxing_technique = "boxing_technique"
    foot_prehab = "foot_prehab"
    glute_prehab = "glute_prehab"
    mobility = "mobility"
    rest = "rest"
