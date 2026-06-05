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

import os
import tempfile
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The default `profile.yaml` lives at the app/repo root. Resolve it from this
# module's location (parents[2] == backend/), never cwd, so the default works
# identically under pytest and at runtime.
PROFILE_PATH = Path(__file__).resolve().parents[2] / "profile.yaml"


class _ProfilePathSettings(BaseSettings):
    """Auth-free resolver for the `profile.yaml` location override.

    Reads `PROFILE_PATH` from the process env **and** `.env` — full parity with
    the main `Settings` (which mirrors the same knob as `Settings.profile_path`)
    — but without the required `api_token`/`app_db_path` fields, so loading
    constants never depends on the auth secret. A deployed runtime whose
    `profile.yaml` is not at the source-tree root sets `PROFILE_PATH` to point
    the loader at the real file.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    profile_path: str | None = None


def _default_profile_path() -> Path:
    """The path `load_profile()` uses when no explicit path is passed.

    Honours the `PROFILE_PATH` override from **either** the process env or `.env`
    (the deployment seam, parity with `Settings`), falling back to the repo-root
    `PROFILE_PATH` anchor for the source-tree runtime.
    """
    override = _ProfilePathSettings().profile_path
    return Path(override) if override else PROFILE_PATH


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """`SafeLoader` that rejects duplicate mapping keys.

    Plain `yaml.safe_load` keeps the *last* of duplicate keys, silently
    discarding a value. For a hand-edited single source of truth, that is the
    same class of error `extra="forbid"` guards against — a duplicate must fail
    loudly, not silently override. (review round-1 #3)
    """

    def construct_mapping(self, node, deep=False):  # type: ignore[override]
        seen: set = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


class Athlete(BaseModel):
    """Static athlete profile (DB.md §5 `athlete`)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    # Physical measures are strictly positive — a negative/zero age, height, or
    # goal weight is a bad hand-edit that would corrupt TDEE/BMR math (E8).
    age: int = Field(gt=0)
    sex: str
    height_cm: int = Field(gt=0)
    goal_weight_kg: float = Field(gt=0)


class Thresholds(BaseModel):
    """HR/cadence anchors, monthly-frozen (DB.md §5 `thresholds`)."""

    model_config = ConfigDict(extra="forbid")

    # All HR/cadence anchors are strictly positive bpm/spm values.
    max_hr: int = Field(gt=0)
    rhr_baseline: int = Field(gt=0)
    hrv_baseline_ms: int = Field(gt=0)
    easy_hr_cap: int = Field(gt=0)
    cadence_target_spm: int = Field(gt=0)
    cadence_current_spm: int = Field(gt=0)

    @model_validator(mode="after")
    def _hr_cadence_consistent(self) -> "Thresholds":
        # The anchors must agree with each other, not just be individually
        # positive — an inconsistent set would feed E8 (zone bucketing) one
        # ceiling while E9 renders another.
        if self.max_hr <= self.rhr_baseline:
            raise ValueError(
                f"max_hr ({self.max_hr}) must be greater than rhr_baseline ({self.rhr_baseline})"
            )
        if self.easy_hr_cap >= self.max_hr:
            raise ValueError(
                f"easy_hr_cap ({self.easy_hr_cap}) must be below max_hr ({self.max_hr})"
            )
        if self.cadence_current_spm > self.cadence_target_spm:
            raise ValueError(
                f"cadence_current_spm ({self.cadence_current_spm}) must be <= "
                f"cadence_target_spm ({self.cadence_target_spm})"
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
        if self.z1[0] <= 0:
            raise ValueError(f"zone z1 low must be a positive bpm, got {self.z1[0]}")
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

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    # All multipliers are g/kg per day — strictly positive; a negative/zero
    # multiplier is a bad hand-edit that would zero out or invert carb targets.
    hard_low: float = Field(gt=0)
    hard_high: float = Field(gt=0)
    moderate: float = Field(gt=0)
    rest_low: float = Field(gt=0)
    rest_high: float = Field(gt=0)

    @model_validator(mode="after")
    def _carb_bands_low_below_high(self) -> "CarbsPerKg":
        # Each day-type band (hard, rest) is a `low..high` range; an inverted
        # band would invert the carb target the macro engine reads.
        for low_name, low, high_name, high in (
            ("hard_low", self.hard_low, "hard_high", self.hard_high),
            ("rest_low", self.rest_low, "rest_high", self.rest_high),
        ):
            if low > high:
                raise ValueError(f"{low_name} ({low}) must be <= {high_name} ({high})")
        return self


class Nutrition(BaseModel):
    """§7 macro/hydration constants the macro engine reads (DB.md §5 `nutrition`)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    # Every numeric constant feeds the macro/hydration engine (E8), so each has
    # a positive floor — a hand-edited negative/zero value is a bad file and must
    # fail loudly rather than corrupt downstream guidance (PLAN R2).
    activity_factor: float = Field(gt=0)
    # Hard/medical caps from the §5 comments, enforced at load (inclusive — the
    # boundary value is valid) so a bad file can never reach the macro engine.
    # `deficit_pct` floors at 0 (== maintenance; negative would be a surplus).
    deficit_pct: float = Field(ge=0, le=0.20)
    protein_g_per_kg: float = Field(gt=0, le=2.0)
    fat_g_per_kg_low: float = Field(gt=0)
    fat_g_per_kg_high: float = Field(gt=0)
    carbs_g_per_kg: CarbsPerKg
    hydration_l_low: float = Field(gt=0)
    hydration_l_high: float = Field(gt=0)
    fiber_g_low: float = Field(gt=0)
    fiber_g_high: float = Field(gt=0)

    @model_validator(mode="after")
    def _ranges_low_below_high(self) -> "Nutrition":
        # The three low/high pairs must be correctly ordered — an inverted range
        # would invert the target band the macro/hydration engine reads.
        for low_name, low, high_name, high in (
            ("fat_g_per_kg_low", self.fat_g_per_kg_low, "fat_g_per_kg_high", self.fat_g_per_kg_high),
            ("hydration_l_low", self.hydration_l_low, "hydration_l_high", self.hydration_l_high),
            ("fiber_g_low", self.fiber_g_low, "fiber_g_high", self.fiber_g_high),
        ):
            if low > high:
                raise ValueError(f"{low_name} ({low}) must be <= {high_name} ({high})")
        return self


class Meta(BaseModel):
    """Provenance + the version tag stamped onto each brief (DB.md §5 `meta`)."""

    model_config = ConfigDict(extra="forbid")

    derived_from: str
    computed_at: date
    constitution_version: str
    # The ISO week (`YYYY-Www`) the §10 monthly constants recompute last fired (E10·P2).
    # Nullable so a fresh profile that never recomputed is **due** on its first weekly
    # brief; `RecomputeConstants` stamps it on a due run and `is_recompute_due` reads it.
    constants_recomputed_week: str | None = None


class Profile(BaseModel):
    """Root model — the five §5 sections. `extra="forbid"` so a stray top-level
    key (e.g. a `daily_metrics`/`body_mass` block) fails rather than loading."""

    model_config = ConfigDict(extra="forbid")

    athlete: Athlete
    thresholds: Thresholds
    zones: Zones
    nutrition: Nutrition
    meta: Meta

    @model_validator(mode="after")
    def _zones_consistent_with_max_hr(self) -> "Profile":
        # The top zone's high bound is the max HR — `compute_zones.py` derives Z5
        # from `max_hr`, so a mismatch means E8 buckets against a different
        # ceiling than `thresholds.max_hr` and the rendered constitution (E9).
        if self.zones.z5[1] != self.thresholds.max_hr:
            raise ValueError(
                f"zones.z5 high ({self.zones.z5[1]}) must equal thresholds.max_hr "
                f"({self.thresholds.max_hr})"
            )
        return self

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

    When `path` is omitted, resolves the `PROFILE_PATH` env override (deployment
    seam) and falls back to the repo-root anchor. Raises `FileNotFoundError`
    when the file is missing, `ValueError` on a YAML parse error or a non-mapping
    document, and lets `pydantic.ValidationError` propagate when a constant
    violates a §5 rule.
    """
    resolved = Path(path) if path is not None else _default_profile_path()
    if not resolved.is_file():
        raise FileNotFoundError(f"profile.yaml not found at {resolved}")
    try:
        data = yaml.load(resolved.read_text(encoding="utf-8"), Loader=_UniqueKeySafeLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"profile.yaml at {resolved} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"profile.yaml at {resolved} must be a YAML mapping, got {type(data).__name__}")
    return Profile(**data)


def write_profile(profile: Profile, *, path: Path | None = None) -> None:
    """Atomically (re)write `profile.yaml` from a validated `Profile` (E10·P2; §10).

    The single `profile.yaml` **writer** in the repo (E8·P5 deferred it to E10). Resolves
    `path` via the same `_default_profile_path()` (`PROFILE_PATH` override) `load_profile`
    uses, serialises `profile` back to the §5 mapping (`model_dump(mode="json")` — `date`
    fields ISO-stamped, enums as wire strings), `yaml.safe_dump`s to a **temp file in the
    same directory**, `flush`+`fsync`, then `os.replace(tmp, target)` (atomic rename — a
    concurrent `load_profile` never sees a torn file). On any dump/write error the temp
    file is removed and the error re-raised, leaving the original `profile.yaml` intact.

    Round-trips: `load_profile(path)` after `write_profile(p, path=path)` re-reads an
    **equal** `Profile`. The caller (`PersistPlanNode`) holds a `Profile` already rebuilt
    via `Profile.model_validate(...)` (re-validated), so a §10 helper can never persist an
    invalid file.
    """
    target = Path(path) if path is not None else _default_profile_path()
    data = profile.model_dump(mode="json")
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".profile-", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        # Leave the original file untouched on any failure; clean up the temp file.
        tmp_path.unlink(missing_ok=True)
        raise
