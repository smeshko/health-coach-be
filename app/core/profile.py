"""Typed loader for `profile.yaml` — the single source of truth for constants.

`profile.yaml` (DB.md §5) holds every numeric constant as a hand-edited,
git-diffable file (NOT a table — `app.db` has no `profile` table, DB.md §0/§5).
These models mirror the §5 block 1:1 in snake_case; every section is
`extra="forbid"` so a typo'd or renamed key fails loudly at load rather than
loading with a silent default. This is internal config read as-is, so it does
**not** inherit the camelCase wire base (`app/api/schemas/base.py`).

Only the §5 **static / monthly-frozen** fields are modelled. Live/derived values
that look like profile but move daily — current weight, the 30d HRV/RHR rolling
baselines, per-day sleep/zone-minutes/readiness — live in `daily_metrics`
(`app.db`) and are deliberately absent here (DB.md §5 table + footnote ¹).

Validators (caps, monotonic+contiguous zones) and the YAML loader land in
TASK-002; the example file and accessors in TASK-003.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict


class Athlete(BaseModel):
    """Static athlete profile (DB.md §5 `athlete`)."""

    model_config = ConfigDict(extra="forbid")

    age: int
    sex: str
    height_cm: int
    goal_weight_kg: float


class Thresholds(BaseModel):
    """HR/cadence anchors, monthly-frozen (DB.md §5 `thresholds`)."""

    model_config = ConfigDict(extra="forbid")

    max_hr: int
    rhr_baseline: int
    hrv_baseline_ms: int
    easy_hr_cap: int
    cadence_target_spm: int
    cadence_current_spm: int


class Zones(BaseModel):
    """HR-zone bpm bounds, each `[low, high]` (DB.md §5 `zones`)."""

    model_config = ConfigDict(extra="forbid")

    z1: tuple[int, int]
    z2: tuple[int, int]
    z3: tuple[int, int]
    z4: tuple[int, int]
    z5: tuple[int, int]


class CarbsPerKg(BaseModel):
    """Per-day carb multipliers (g/kg). All five required — a missing key is a
    `ValidationError`, a stray key is rejected by `extra="forbid"`, so "all five
    present" (DB.md §5) is enforced structurally."""

    model_config = ConfigDict(extra="forbid")

    hard_low: float
    hard_high: float
    moderate: float
    rest_low: float
    rest_high: float


class Nutrition(BaseModel):
    """§7 macro/hydration constants the macro engine reads (DB.md §5 `nutrition`)."""

    model_config = ConfigDict(extra="forbid")

    activity_factor: float
    deficit_pct: float
    protein_g_per_kg: float
    fat_g_per_kg_low: float
    fat_g_per_kg_high: float
    carbs_g_per_kg: CarbsPerKg
    hydration_l_low: float
    hydration_l_high: float
    fiber_g_low: float
    fiber_g_high: float


class Meta(BaseModel):
    """Provenance + the version tag stamped onto each brief (DB.md §5 `meta`)."""

    model_config = ConfigDict(extra="forbid")

    derived_from: str
    computed_at: date
    constitution_version: str


class Profile(BaseModel):
    """Root model — the five §5 sections. `extra="forbid"` so a stray top-level
    key (e.g. a `daily_metrics`/`body_mass` block) fails rather than loading."""

    model_config = ConfigDict(extra="forbid")

    athlete: Athlete
    thresholds: Thresholds
    zones: Zones
    nutrition: Nutrition
    meta: Meta
