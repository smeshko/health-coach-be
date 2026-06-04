"""The shared card-field derivation core (E7·P2 TASK-001).

`derive_card_fields(card, profile)` is the **single** place a `WorkoutCard` is
mapped to its code-filled fields: it reads every *function-of-the-card* value
from `CARD_META[card]` (E7·P1) and resolves the card's `hr_cap`/`cadence`
**symbolic** `profile.yaml` references into live bpm/spm from an **injected**
`Profile` (E3). Both expanders (`expand_session`, `expand_plan_pick`) build on
this one mapping, so the daily and weekly paths can never drift on "the easy-run
zone" or "the vo2 flags" — mirroring E7·P1's "express the rule once" discipline.

Two load-bearing rules (CARDS.md §0):

* **The two axes never collapse.** `is_hard` (training load → `is_hard_day`) and
  `day_type` (fuel demand → the LLM's `dayType` lever) are independent. This core
  reads **only** `is_hard`; `meta.day_type` is **deliberately never read** — it is
  not a derived field, it feeds the daily LLM carve-out (out of scope here, E11).
* **`hr_cap`/`cadence` are resolved from the injected profile, not loaded or
  hard-coded.** `meta.hr_cap` is a `profile.thresholds` **key name** (today only
  `"easy_hr_cap"`) → `getattr(profile.thresholds, meta.hr_cap)`; `meta.cadence` is
  a bool cue flag → `cadence_current_spm` iff set. A future `hr_cap` key needs no
  edit here, and a `CARD_META`↔profile drift surfaces as a loud `AttributeError`.

Pure module: imports only `dataclasses`, `app.core.cards`/`app.core.enums`
(E7·P1), and `app.core.profile.Profile` (E3). No FastAPI/SQLAlchemy/PydanticAI
import, no `load_profile()` call, no validation/arithmetic, no `dayType` symbol.
"""

from dataclasses import dataclass

from app.core.cards import get_card
from app.core.enums import Intensity, WorkoutCard, Zone
from app.core.profile import Profile


@dataclass(frozen=True)
class DerivedCardFields:
    """The code-filled, card-derived fields shared by both wire shapes.

    Carries the union of what `SessionBlock` (daily) and `PlannedSession`
    (weekly) need — each expander selects its MODELS subset — plus the two
    annotation notes (`zone_note`/`hr_cap_note`) which MODELS does **not** expose
    as wire fields but which must stay reachable so E10/E11 can fold the band /
    drift policy into the `session` narrative (E7·P1 round-3 #1).
    """

    intensity: Intensity
    zone_target: Zone | None
    is_hard_day: bool
    hr_cap_bpm: int | None
    cadence_spm: int | None
    flags: list[str]
    zone_note: str | None
    hr_cap_note: str | None


def resolve_hr_cap(hr_cap_key: str | None, profile: Profile) -> int | None:
    """Resolve a card's symbolic `hr_cap` key against the injected profile.

    `None` when the card carries no cap; otherwise the `profile.thresholds` field
    **named by** `hr_cap_key` (today `"easy_hr_cap"` → `146`). An unknown key name
    propagates the `AttributeError` — a `CARD_META`↔`profile.yaml` drift bug,
    surfaced loudly rather than swallowed.
    """
    if hr_cap_key is None:
        return None
    return getattr(profile.thresholds, hr_cap_key)


def derive_card_fields(card: WorkoutCard, profile: Profile) -> DerivedCardFields:
    """Map `card` to its code-filled fields from `CARD_META`, resolving the
    `hr_cap`/`cadence` references against the **injected** `profile`.

    A flat read-and-resolve: each field is copied from the **named** `CardMeta`
    attribute (`intensity`/`zone`/`is_hard`/`zone_note`/`hr_cap_note`), `flags` is
    serialized to the sorted `.value` strings (stable wire order, colon form
    preserved — `foot_prehab` → `"prehab:foot"`), and the two symbolic references
    are resolved from the profile. `meta.day_type` is **not** read (the two-axes
    rule); the dose is the expanders' to copy verbatim (no validation here).
    """
    meta = get_card(card)
    return DerivedCardFields(
        intensity=meta.intensity,
        zone_target=meta.zone,
        is_hard_day=meta.is_hard,
        hr_cap_bpm=resolve_hr_cap(meta.hr_cap, profile),
        cadence_spm=profile.thresholds.cadence_current_spm if meta.cadence else None,
        flags=sorted(f.value for f in meta.flags),
        zone_note=meta.zone_note,
        hr_cap_note=meta.hr_cap_note,
    )
