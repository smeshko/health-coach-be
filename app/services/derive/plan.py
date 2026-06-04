"""The weekly `PlannedPick`→`PlannedSession` expander (E7·P2 TASK-003).

`expand_plan_pick(pick, tier, profile)` turns a slim `PlannedPick` into the full,
code-completed `PlannedSession` (MODELS) by filling `intensity`/`isHardDay`/
`zoneTarget`/`flags` from the shared `derive_card_fields` core (TASK-001) and
copying the dose / `suggested_day` verbatim. `expand_plan(core, extras, profile)`
is the wrapper E10 calls on a `WeeklyPlanLLMOutput`: it stamps `tier` from **which
array the pick sat in** (`core[]` → `Tier.core`, `extras[]` → `Tier.extra`) — the
only place membership→tier is decided.

Two load-bearing rules (CARDS.md §0; epic R2/R4):

* **`isHardDay = is_hard`, never `day_type`.** The two-axes rule survives
  expansion: `is_hard` (load → the hard-day budget) drives `isHardDay`; `day_type`
  (fuel → the daily LLM `dayType` lever) is **not** read. A `long_run`
  (`is_hard False`, `day_type hard`) expands to `isHardDay False`.
* **`tier` is implied by array membership**, supplied by the wrapper — `tier` is
  not a `CardMeta` field and not in `PlannedPick` (the LLM never emits it).

`PlannedSession` has **no** `hrCapBpm`/`cadenceSpm` (those are daily — `session.py`;
the weekly cadence cue is `WeeklyTargets.cadenceSpm`, E10). The dose +
`suggested_day` stay with the LLM (LLM.md §3) — copied verbatim, **not** validated
(E7·P3 owns dose-in-band + spacing). `zone_note`/`hr_cap_note` reach E10's `session`
narrative by E10 calling the shared `derive_card_fields` **directly** — they are not
`PlannedSession` fields, so this module adds no notes wrapper (the deliberate
asymmetry with the daily `expand_session_with_notes`).

`PlannedPick`/`PlannedSession` are defined here (co-located, single source —
DECISIONS.md Decision 2) because E10/E11 have not shipped them. Both subclass
`CamelModel` so the wire is camelCase. No FastAPI route, no DB/LLM import, no
`Violation`/`validate_`/`dayType` symbol.
"""

from app.api.schemas.base import CamelModel
from app.core.enums import Intensity, Tier, Weekday, WorkoutCard, Zone
from app.core.profile import Profile
from app.services.derive.card_fields import derive_card_fields


class PlannedPick(CamelModel):
    """The slim weekly pick the LLM emits — `{card, suggestedDay?, durationMin*?}`."""

    card: WorkoutCard
    suggested_day: Weekday | None = None
    duration_min_low: int | None = None
    duration_min_high: int | None = None


class PlannedSession(CamelModel):
    """The full, code-completed weekly session (MODELS `PlannedSession`).

    `card`/`suggestedDay` + the dose are the LLM's; `tier` is implied by array
    membership; everything else is filled in code from `CARD_META`. No
    `hrCapBpm`/`cadenceSpm` — those are daily.
    """

    card: WorkoutCard
    tier: Tier
    intensity: Intensity
    is_hard_day: bool
    suggested_day: Weekday | None
    zone_target: Zone | None
    duration_min_low: int | None
    duration_min_high: int | None
    flags: list[str]


def expand_plan_pick(pick: PlannedPick, tier: Tier, profile: Profile) -> PlannedSession:
    """Expand a slim `PlannedPick` into a full `PlannedSession`.

    `tier` is **caller-supplied** (the array the pick sat in — never read off the
    pick or a card attribute). `is_hard_day` is `CARD_META[card].is_hard` (never
    `day_type` — the two-axes rule). The dose + `suggested_day` are copied
    verbatim — **no** validation (E7·P3 owns dose-in-band + spacing).
    """
    d = derive_card_fields(pick.card, profile)
    return PlannedSession(
        card=pick.card,
        tier=tier,
        intensity=d.intensity,
        is_hard_day=d.is_hard_day,
        suggested_day=pick.suggested_day,
        zone_target=d.zone_target,
        duration_min_low=pick.duration_min_low,
        duration_min_high=pick.duration_min_high,
        flags=d.flags,
    )


def expand_plan(
    core: list[PlannedPick], extras: list[PlannedPick], profile: Profile
) -> tuple[list[PlannedSession], list[PlannedSession]]:
    """Expand a weekly plan's two pick arrays, stamping `tier` from membership.

    Every `core` pick gets `Tier.core` and every `extras` pick gets `Tier.extra`
    (singular `extra`, per MODELS/E7·P1) — so `tier` is implied by which array the
    pick sat in (MODELS PlannedSession; epic R4). The two output lists preserve the
    inputs' order and length. This is the only place membership→tier is decided.
    """
    return (
        [expand_plan_pick(p, Tier.core, profile) for p in core],
        [expand_plan_pick(p, Tier.extra, profile) for p in extras],
    )
