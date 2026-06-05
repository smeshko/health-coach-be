"""Wire schema for ``GET /profile`` (E14·P1) — the iOS Settings (PRD §7.7) + zone-chip
(PRD §4.2) read of the ``profile.yaml`` constants.

The core ``Athlete``/``Thresholds``/``Meta`` (``app/core/profile.py``) are plain snake_case
``BaseModel``s with **no** ``alias_generator`` — embedding them directly would serialise
snake_case and silently break the camelCase wire contract. So the wire layer re-declares the
exposed fields in ``CamelModel`` sub-models (populated via ``model_validate`` /
``from_attributes``), which is what produces the documented camelCase response (DECISIONS
Decision 4).

Deliberately **excluded** (DECISIONS Decisions 2 & 3): the nutrition factors
(``activity_factor``/``deficit_pct``/``protein_g_per_kg``/…) — neither §4.2 nor §7.7 needs them
— and current weight, which is a ``daily_metrics`` value (including it would make the endpoint
read the DB, breaking the pure-``load_profile()`` contract; it belongs to a future daily/trends
endpoint).
"""

from __future__ import annotations

from app.api.schemas.base import CamelModel


class AthleteOut(CamelModel):
    """The static athlete block → ``{age, sex, heightCm, goalWeightKg}``."""

    age: int
    sex: str
    height_cm: int
    goal_weight_kg: float


class ThresholdsOut(CamelModel):
    """The HR/cadence anchors → ``{maxHr, rhrBaseline, hrvBaselineMs, easyHrCap,
    cadenceCurrentSpm, cadenceTargetSpm}``."""

    max_hr: int
    rhr_baseline: int
    hrv_baseline_ms: int
    easy_hr_cap: int
    cadence_current_spm: int
    cadence_target_spm: int


class ZoneRange(CamelModel):
    """One HR zone's bpm bounds → ``{low, high}`` (mapped from a ``zone_bounds()`` tuple)."""

    low: int
    high: int


class ZonesOut(CamelModel):
    """The five HR zones, each a ``{low, high}`` range (PRD §4.2 zone chips)."""

    z1: ZoneRange
    z2: ZoneRange
    z3: ZoneRange
    z4: ZoneRange
    z5: ZoneRange


class MetaOut(CamelModel):
    """The brief-stamped version tag + last monthly-recompute week → ``{constitutionVersion,
    constantsRecomputedWeek}``. The internal provenance fields (``derived_from``/``computed_at``)
    are omitted."""

    constitution_version: str
    constants_recomputed_week: str | None = None


class ProfileResponse(CamelModel):
    """The ``GET /profile`` payload — athlete, HR zones, thresholds, meta (all from
    ``profile.yaml`` via ``load_profile()``)."""

    athlete: AthleteOut
    zones: ZonesOut
    thresholds: ThresholdsOut
    meta: MetaOut
