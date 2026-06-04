"""`CARD_META` — the canonical workout-pool table (E7·P1 TASK-002).

The single source of truth for every prescribable workout, transcribed
column-for-column from ``docs/architecture/CARDS.md`` §1A–§1E. It is **one
logical table keyed by ``card``** (a Python ``Mapping``, not a SQL table),
powering three consumers at once: derive-don't-emit (E7·P2 fills
``intensity``/``zoneTarget``/``isHardDay``/``hrCapBpm``/``cadenceSpm``/``flags``/
``dayType`` from here), validation (E7·P3 polices picks against it), and prompt
rendering (the pool the constitution shows is generated from here).

Two load-bearing modelling rules from CARDS.md §0 are encoded here:

* ``is_hard`` (training **load** → the hard-day budget & spacing) and
  ``day_type`` (fuel **demand** → nutrition carb-cycling) are **two independent
  axes**, never aliased — a ``long_run`` is ``is_hard=False`` but
  ``day_type=hard``. They are two distinct fields with no derivation between them.
* ``hr_cap`` / ``cadence`` are **symbolic** — ``hr_cap`` stores the profile
  config **key name** (e.g. ``"easy_hr_cap"``), not a resolved bpm; ``cadence``
  is a bool flag for "carries the cadence cue". E7·P2 resolves the actual values
  from the profile config, so this module imports no profile loader and reads no
  config file.

Pure module: imports only ``enum``/``dataclasses``/``typing``/``types`` and
``app.core.enums``. No FastAPI/SQLAlchemy/PydanticAI/profile import, no I/O.
"""

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from app.core.enums import DayType, Intensity, WorkoutCard, Zone


class Impact(str, Enum):
    """The CARDS.md §1 ``impact`` column — a typed informational/dosing
    attribute (ground-impact level for flat-foot dosing, §8.3).

    **Not the knee-gate input.** The ``knee_pain > 3`` gate (E7·P3 §6.2) keys on
    the §2 ``Flag.impact`` flag, not this column — so a low-impact card that is
    ``Impact.low`` but lacks ``Flag.impact`` (e.g. ``boxing``) is *not* gated.
    """

    yes = "yes"
    no = "no"
    low = "low"
    high = "high"
    conditional = "conditional"


class Flag(str, Enum):
    """The closed flags vocabulary — CARDS.md §2 machine keys ∪ the §1-only
    ``red_day_default`` (which CARDS.md uses on ``mobility`` in §1 but omits from
    the §2 table; the closed set is the union — round-3 #2).

    Machine keys filled by code (never emitted by the LLM); the app reads them,
    the validator (E7·P3) enforces them. The prehab keys preserve the documented
    colon form in ``.value`` (``"prehab:foot"``) while the member name is a valid
    identifier.

    **``Flag.impact`` (the §2 "high ground-impact, subject to the knee gate"
    marker) is distinct from the ``Impact`` column** — the knee gate keys on this
    flag, not the column.
    """

    impact = "impact"
    needs_green_knee = "needs_green_knee"
    quality_day = "quality_day"
    low_impact = "low_impact"
    prefer_low_impact = "prefer_low_impact"
    knee_amber_cap = "knee_amber_cap"
    append_to_easy = "append_to_easy"
    effort_based = "effort_based"
    auto_reg_downgrade = "auto_reg_downgrade"
    big_recovery_cost = "big_recovery_cost"
    long = "long"
    strength = "strength"
    upper = "upper"
    lower = "lower"
    prehab_foot = "prehab:foot"
    prehab_glute = "prehab:glute"
    red_day_default = "red_day_default"


@dataclass(frozen=True)
class CardMeta:
    """One row of ``CARD_META`` — a card's fixed attributes (CARDS.md §1 columns).

    Frozen and hashable: the table is a version-controlled constant, never
    mutated. ``zone`` is the **primary target** (a single ``Zone`` — for a
    ranged/ramped row, the top/effort-defining zone of the range); the full band
    is kept verbatim in ``zone_note`` so nothing is lost. ``hr_cap`` is the
    profile config key name (not a resolved bpm); ``hr_cap_note`` preserves a
    verbatim cap-policy qualifier (e.g. ``long_run``'s "start, drift OK").
    ``cadence`` is ``True`` when the card carries the cadence cue.
    """

    card: WorkoutCard
    intensity: Intensity
    is_hard: bool
    day_type: DayType
    zone: Zone | None
    zone_note: str | None
    hr_cap: str | None
    hr_cap_note: str | None
    cadence: bool
    impact: Impact
    dose_min_low: int
    dose_min_high: int | None
    flags: frozenset[Flag]
    serves: str


# The 20 cards, transcribed column-for-column from CARDS.md §1A–§1E. Grouped by
# category for reading; it is one logical table keyed by `card`.
_CARD_META: dict[WorkoutCard, CardMeta] = {
    # --- 1A. Running ---------------------------------------------------------
    WorkoutCard.easy_run: CardMeta(
        card=WorkoutCard.easy_run,
        intensity=Intensity.easy,
        is_hard=False,
        day_type=DayType.moderate,
        zone=Zone.z2,
        zone_note=None,
        hr_cap="easy_hr_cap",
        hr_cap_note=None,
        cadence=True,
        impact=Impact.yes,
        dose_min_low=25,
        dose_min_high=50,
        flags=frozenset({Flag.impact}),
        serves="aerobic base, fat ox., recovery",
    ),
    WorkoutCard.long_run: CardMeta(
        card=WorkoutCard.long_run,
        intensity=Intensity.easy,
        is_hard=False,
        day_type=DayType.hard,
        zone=Zone.z2,
        zone_note="z2 (by effort)",
        hr_cap="easy_hr_cap",
        hr_cap_note="start, drift OK",
        cadence=True,
        impact=Impact.yes,
        dose_min_low=60,
        dose_min_high=None,
        flags=frozenset({Flag.impact, Flag.long, Flag.effort_based}),
        serves="endurance, durability, HM progression",
    ),
    WorkoutCard.progression_run: CardMeta(
        card=WorkoutCard.progression_run,
        intensity=Intensity.quality,
        is_hard=True,
        day_type=DayType.hard,
        zone=Zone.z4,
        zone_note="z2→z4",
        hr_cap=None,
        hr_cap_note=None,
        cadence=True,
        impact=Impact.yes,
        dose_min_low=50,
        dose_min_high=80,
        flags=frozenset({Flag.quality_day, Flag.impact, Flag.needs_green_knee}),
        serves="running on tired legs; HM stamina (periodized upgrade)",
    ),
    WorkoutCard.threshold: CardMeta(
        card=WorkoutCard.threshold,
        intensity=Intensity.quality,
        is_hard=True,
        day_type=DayType.hard,
        zone=Zone.z4,
        zone_note=None,
        hr_cap=None,
        hr_cap_note=None,
        cadence=True,
        impact=Impact.yes,
        dose_min_low=30,
        dose_min_high=50,
        flags=frozenset({Flag.quality_day, Flag.impact}),
        serves='lactate threshold, "comfortably hard"',
    ),
    WorkoutCard.vo2: CardMeta(
        card=WorkoutCard.vo2,
        intensity=Intensity.quality,
        is_hard=True,
        day_type=DayType.hard,
        zone=Zone.z5,
        zone_note=None,
        hr_cap=None,
        hr_cap_note=None,
        cadence=True,
        impact=Impact.high,
        dose_min_low=25,
        dose_min_high=45,
        flags=frozenset({Flag.quality_day, Flag.impact, Flag.needs_green_knee}),
        serves="top-end aerobic power, VO₂max",
    ),
    WorkoutCard.strides: CardMeta(
        card=WorkoutCard.strides,
        intensity=Intensity.easy,
        is_hard=False,
        day_type=DayType.moderate,
        zone=Zone.z5,
        zone_note="z5 (brief)",
        hr_cap=None,
        hr_cap_note=None,
        cadence=True,
        impact=Impact.yes,
        dose_min_low=5,
        dose_min_high=12,
        flags=frozenset({Flag.impact, Flag.append_to_easy}),
        serves="running economy, neuromuscular, cadence",
    ),
    WorkoutCard.active_recovery: CardMeta(
        card=WorkoutCard.active_recovery,
        intensity=Intensity.recovery,
        is_hard=False,
        day_type=DayType.rest,
        zone=Zone.z1,
        zone_note=None,
        hr_cap=None,
        hr_cap_note=None,
        cadence=False,
        impact=Impact.no,
        dose_min_low=20,
        dose_min_high=40,
        flags=frozenset({Flag.low_impact}),
        serves="blood flow, gentle recovery (walk/spin/row/mobility)",
    ),
    # --- 1B. Cardio ----------------------------------------------------------
    WorkoutCard.hiit: CardMeta(
        card=WorkoutCard.hiit,
        intensity=Intensity.quality,
        is_hard=True,
        day_type=DayType.hard,
        zone=Zone.z5,
        zone_note="z4–z5",
        hr_cap=None,
        hr_cap_note=None,
        cadence=False,
        impact=Impact.conditional,
        dose_min_low=15,
        dose_min_high=25,
        flags=frozenset({Flag.quality_day, Flag.prefer_low_impact}),
        serves="conditioning, fat loss, time-efficient",
    ),
    WorkoutCard.jump_rope: CardMeta(
        card=WorkoutCard.jump_rope,
        intensity=Intensity.quality,
        is_hard=False,
        day_type=DayType.moderate,
        zone=Zone.z4,
        zone_note="z3–z4",
        hr_cap=None,
        hr_cap_note=None,
        cadence=True,
        impact=Impact.yes,
        dose_min_low=8,
        dose_min_high=20,
        flags=frozenset({Flag.impact, Flag.knee_amber_cap}),
        serves="conditioning, calf/foot stiffness, cadence",
    ),
    WorkoutCard.steady_cardio: CardMeta(
        card=WorkoutCard.steady_cardio,
        intensity=Intensity.easy,
        is_hard=False,
        day_type=DayType.moderate,
        zone=Zone.z2,
        zone_note=None,
        hr_cap=None,
        hr_cap_note=None,
        cadence=False,
        impact=Impact.no,
        dose_min_low=30,
        dose_min_high=50,
        flags=frozenset({Flag.low_impact}),
        serves="low-impact aerobic base (bike/row/elliptical/incline walk)",
    ),
    # --- 1C. Strength --------------------------------------------------------
    WorkoutCard.strength_push: CardMeta(
        card=WorkoutCard.strength_push,
        intensity=Intensity.quality,
        is_hard=False,
        day_type=DayType.moderate,
        zone=None,
        zone_note=None,
        hr_cap=None,
        hr_cap_note=None,
        cadence=False,
        impact=Impact.no,
        dose_min_low=30,
        dose_min_high=45,
        flags=frozenset({Flag.strength, Flag.upper}),
        serves="upper-body muscle (chest/shoulder/triceps)",
    ),
    WorkoutCard.strength_pull: CardMeta(
        card=WorkoutCard.strength_pull,
        intensity=Intensity.quality,
        is_hard=False,
        day_type=DayType.moderate,
        zone=None,
        zone_note=None,
        hr_cap=None,
        hr_cap_note=None,
        cadence=False,
        impact=Impact.no,
        dose_min_low=30,
        dose_min_high=45,
        flags=frozenset({Flag.strength, Flag.upper}),
        serves="upper-body muscle (back/biceps) + posture",
    ),
    WorkoutCard.strength_lower: CardMeta(
        card=WorkoutCard.strength_lower,
        intensity=Intensity.quality,
        is_hard=False,
        day_type=DayType.moderate,
        zone=None,
        zone_note=None,
        hr_cap=None,
        hr_cap_note=None,
        cadence=False,
        impact=Impact.low,
        dose_min_low=25,
        dose_min_high=35,
        flags=frozenset({Flag.strength, Flag.lower}),
        serves="running support, knee stability",
    ),
    WorkoutCard.strength_full: CardMeta(
        card=WorkoutCard.strength_full,
        intensity=Intensity.quality,
        is_hard=False,
        day_type=DayType.moderate,
        zone=None,
        zone_note=None,
        hr_cap=None,
        hr_cap_note=None,
        cadence=False,
        impact=Impact.low,
        dose_min_low=20,
        dose_min_high=35,
        flags=frozenset({Flag.strength}),
        serves="GPP, carryover, time-crunch option",
    ),
    # --- 1D. Boxing ----------------------------------------------------------
    WorkoutCard.boxing: CardMeta(
        card=WorkoutCard.boxing,
        intensity=Intensity.quality,
        is_hard=True,
        day_type=DayType.hard,
        zone=Zone.z5,
        zone_note="z3–z5",
        hr_cap=None,
        hr_cap_note=None,
        cadence=False,
        impact=Impact.low,
        dose_min_low=60,
        dose_min_high=90,
        flags=frozenset({Flag.quality_day, Flag.big_recovery_cost}),
        serves="conditioning, fat loss, adherence, upper-body endurance",
    ),
    WorkoutCard.boxing_technique: CardMeta(
        card=WorkoutCard.boxing_technique,
        intensity=Intensity.easy,
        is_hard=False,
        day_type=DayType.moderate,
        zone=Zone.z3,
        zone_note="z2–z3",
        hr_cap=None,
        hr_cap_note=None,
        cadence=False,
        impact=Impact.low,
        dose_min_low=45,
        dose_min_high=60,
        flags=frozenset({Flag.auto_reg_downgrade}),
        serves="skill on a tired/amber day (footwork/pads light)",
    ),
    # --- 1E. Mobility / prehab ----------------------------------------------
    WorkoutCard.foot_prehab: CardMeta(
        card=WorkoutCard.foot_prehab,
        intensity=Intensity.recovery,
        is_hard=False,
        day_type=DayType.rest,
        zone=None,
        zone_note=None,
        hr_cap=None,
        hr_cap_note=None,
        cadence=False,
        impact=Impact.no,
        dose_min_low=5,
        dose_min_high=10,
        flags=frozenset({Flag.prehab_foot}),
        serves="arch/intrinsic strength (flat feet), ↓ injury",
    ),
    WorkoutCard.glute_prehab: CardMeta(
        card=WorkoutCard.glute_prehab,
        intensity=Intensity.recovery,
        is_hard=False,
        day_type=DayType.rest,
        zone=None,
        zone_note=None,
        hr_cap=None,
        hr_cap_note=None,
        cadence=False,
        impact=Impact.no,
        dose_min_low=5,
        dose_min_high=10,
        flags=frozenset({Flag.prehab_glute}),
        serves="knee tracking, ↓ knee pain",
    ),
    WorkoutCard.mobility: CardMeta(
        card=WorkoutCard.mobility,
        intensity=Intensity.recovery,
        is_hard=False,
        day_type=DayType.rest,
        zone=None,
        zone_note=None,
        hr_cap=None,
        hr_cap_note=None,
        cadence=False,
        impact=Impact.no,
        dose_min_low=10,
        dose_min_high=30,
        flags=frozenset({Flag.red_day_default}),
        serves="recovery, range, stress/sleep (pre-bed OK)",
    ),
    WorkoutCard.rest: CardMeta(
        card=WorkoutCard.rest,
        intensity=Intensity.recovery,
        is_hard=False,
        day_type=DayType.rest,
        zone=None,
        zone_note=None,
        hr_cap=None,
        hr_cap_note=None,
        cadence=False,
        impact=Impact.no,
        dose_min_low=0,
        dose_min_high=0,
        flags=frozenset(),
        serves="full rest (the gate/RED default)",
    ),
}

# Completeness invariant: the table must cover exactly the 20 WorkoutCard
# members — no missing, extra, or duplicate card. Fail fast at import, not at
# derive/validate time.
if set(_CARD_META) != set(WorkoutCard):
    missing = set(WorkoutCard) - set(_CARD_META)
    extra = set(_CARD_META) - set(WorkoutCard)
    raise RuntimeError(
        f"CARD_META is not complete over WorkoutCard: missing={missing}, extra={extra}"
    )

#: The canonical workout-pool table, exposed read-only (mutation raises).
CARD_META: Mapping[WorkoutCard, CardMeta] = MappingProxyType(_CARD_META)
