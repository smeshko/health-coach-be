"""The daily `SessionPick`→`SessionBlock` expander (E7·P2 TASK-002).

`expand_session(pick, profile)` turns a slim `SessionPick` (`card` + dose — the
LLM's genuine pick) into the full, code-completed `SessionBlock` (MODELS) by
filling `intensity`/`zoneTarget`/`hrCapBpm`/`cadenceSpm`/`flags` from the shared
`derive_card_fields` core (TASK-001) and copying the dose **verbatim**. So every
code-derived field equals `CARD_META[card]` and the run/cue cards carry the
cadence cue (epic §4 bullet 2). `SessionBlock` is the merged shape used for
**both** `data.session` and each `data.alternatives` entry (MODELS), so E11 calls
this per pick.

The **dose stays with the LLM** (LLM.md §3): `duration_min_*` is copied unchecked
— **no** dose-in-band validation here (E7·P3 owns it; a test pins an out-of-band
dose passing through). `card` passes through unchanged. `SessionBlock` has **no**
`isHardDay`/`tier` (those are weekly — `plan.py`). `zone_note`/`hr_cap_note` are
**not** `SessionBlock` fields but stay reachable via `expand_session_with_notes`
so E11 folds the band / drift policy into the `session` narrative (E7·P1 round-3
#1).

`SessionPick`/`SessionBlock` are defined here (co-located, single source —
DECISIONS.md Decision 2) because E10/E11 have not shipped them; when they do they
import these. Both subclass `CamelModel` so the wire is camelCase. No FastAPI
route, no DB/LLM import, no `Violation`/`validate_`/`dayType` symbol.
"""

from app.api.schemas.base import CamelModel
from app.core.enums import Intensity, WorkoutCard, Zone
from app.core.profile import Profile
from app.services.derive.card_fields import DerivedCardFields, derive_card_fields


class SessionPick(CamelModel):
    """The slim daily pick the LLM emits — `{card, durationMinLow, durationMinHigh}`."""

    card: WorkoutCard
    duration_min_low: int
    duration_min_high: int


class SessionBlock(CamelModel):
    """The full, code-completed daily workout (MODELS `SessionBlock`).

    `card` + the dose (`durationMin*`) are the LLM's; everything else is filled in
    code from `CARD_META` / the injected profile. No `isHardDay`/`tier` — a single
    workout carries neither (those are weekly).
    """

    card: WorkoutCard
    intensity: Intensity
    zone_target: Zone | None = None
    duration_min_low: int
    duration_min_high: int
    hr_cap_bpm: int | None = None
    cadence_spm: int | None = None
    flags: list[str]


def _block_from(pick: SessionPick, d: DerivedCardFields) -> SessionBlock:
    """Assemble a `SessionBlock` from a pick + its derived fields (one place)."""
    return SessionBlock(
        card=pick.card,
        intensity=d.intensity,
        zone_target=d.zone_target,
        duration_min_low=pick.duration_min_low,
        duration_min_high=pick.duration_min_high,
        hr_cap_bpm=d.hr_cap_bpm,
        cadence_spm=d.cadence_spm,
        flags=d.flags,
    )


def expand_session(pick: SessionPick, profile: Profile) -> SessionBlock:
    """Expand a slim `SessionPick` into a full `SessionBlock`.

    Fills the card-derived fields from `derive_card_fields(pick.card, profile)` and
    copies the dose (`pick.duration_min_*`) and `card` through verbatim — **no**
    band check (E7·P3 owns dose-in-band).
    """
    return _block_from(pick, derive_card_fields(pick.card, profile))


def expand_session_with_notes(
    pick: SessionPick, profile: Profile
) -> tuple[SessionBlock, DerivedCardFields]:
    """Expand a pick **and** return the `DerivedCardFields`, so E11 can read
    `zone_note`/`hr_cap_note` to render the band / drift policy in the `session`
    narrative without re-deriving (the notes are not `SessionBlock` fields —
    MODELS — but must stay reachable; E7·P1 round-3 #1).
    """
    d = derive_card_fields(pick.card, profile)
    return _block_from(pick, d), d
