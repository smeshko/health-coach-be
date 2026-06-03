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

The example file and accessors land in TASK-003.
"""

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# The default `profile.yaml` lives at the app/repo root. Resolve it from this
# module's location (parents[2] == backend/), never cwd, so the default works
# identically under pytest and at runtime.
PROFILE_PATH = Path(__file__).resolve().parents[2] / "profile.yaml"


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

    @model_validator(mode="after")
    def _max_hr_above_rhr(self) -> "Thresholds":
        if self.max_hr <= self.rhr_baseline:
            raise ValueError(
                f"max_hr ({self.max_hr}) must be greater than rhr_baseline ({self.rhr_baseline})"
            )
        return self


class Zones(BaseModel):
    """HR-zone bpm bounds, each `[low, high]` (DB.md §5 `zones`)."""

    model_config = ConfigDict(extra="forbid")

    z1: tuple[int, int]
    z2: tuple[int, int]
    z3: tuple[int, int]
    z4: tuple[int, int]
    z5: tuple[int, int]

    @model_validator(mode="after")
    def _monotonic_and_contiguous(self) -> "Zones":
        # Each zone's high is the next zone's low — a gap or overlap would
        # mis-bucket zone minutes downstream (compute_zones.py). Validate both
        # per-zone ordering (low < high) and the cross-zone contiguity chain
        # (which, with low < high, forces strictly-increasing lows too).
        names = ("z1", "z2", "z3", "z4", "z5")
        bounds = (self.z1, self.z2, self.z3, self.z4, self.z5)
        for name, (low, high) in zip(names, bounds, strict=True):
            if low >= high:
                raise ValueError(f"zone {name} bounds must be low < high, got [{low}, {high}]")
        for name, (_, cur_high), next_name, (next_low, _) in zip(
            names, bounds, names[1:], bounds[1:], strict=False
        ):
            if cur_high != next_low:
                raise ValueError(
                    f"zones must be contiguous: {name}.high ({cur_high}) != "
                    f"{next_name}.low ({next_low})"
                )
        return self


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
    # Hard/medical caps from the §5 comments, enforced at load (inclusive — the
    # boundary value is valid) so a bad file can never reach the macro engine.
    deficit_pct: float = Field(le=0.20)
    protein_g_per_kg: float = Field(le=2.0)
    fat_g_per_kg_low: float
    fat_g_per_kg_high: float
    carbs_g_per_kg: CarbsPerKg
    hydration_l_low: float
    hydration_l_high: float
    fiber_g_low: float
    fiber_g_high: float

    @model_validator(mode="after")
    def _fat_low_below_high(self) -> "Nutrition":
        if self.fat_g_per_kg_low > self.fat_g_per_kg_high:
            raise ValueError(
                f"fat_g_per_kg_low ({self.fat_g_per_kg_low}) must be <= "
                f"fat_g_per_kg_high ({self.fat_g_per_kg_high})"
            )
        return self


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

    def zone_bounds(self) -> dict[str, tuple[int, int]]:
        """The Z1–Z5 bpm bounds the zone-minute math (E8) buckets against."""
        return {
            "z1": self.zones.z1,
            "z2": self.zones.z2,
            "z3": self.zones.z3,
            "z4": self.zones.z4,
            "z5": self.zones.z5,
        }

    @property
    def constitution_version(self) -> str:
        """The version tag stamped onto each brief (E9). Delegates to `meta`."""
        return self.meta.constitution_version


def load_profile(path: Path | None = None) -> Profile:
    """Load and validate `profile.yaml` into a typed `Profile`.

    `path` defaults to the app-root `PROFILE_PATH`; pass an explicit path to
    override. Raises `FileNotFoundError` when the file is missing, `ValueError`
    on a YAML parse error or a non-mapping document, and lets
    `pydantic.ValidationError` propagate when a constant violates a §5 rule.
    """
    resolved = Path(path) if path is not None else PROFILE_PATH
    if not resolved.is_file():
        raise FileNotFoundError(f"profile.yaml not found at {resolved}")
    try:
        data = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"profile.yaml at {resolved} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"profile.yaml at {resolved} must be a YAML mapping, got {type(data).__name__}")
    return Profile(**data)
