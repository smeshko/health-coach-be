"""`POST /sync` wire models (MODELS.md "POST /sync" + "Enums").

Faithful transcription of the eight `/sync` request/response models. Every model
inherits the E1·P1 `CamelModel` base, so the wire is **camelCase** (Swift
`Codable`-friendly) while Python stays **snake_case**, and raw `model_dump_json()`
already emits camelCase (`serialize_by_alias=True`) — no `by_alias=True` at the
call site.

`RecordType` carries the **snake_case wire values** verbatim (MODELS "Enums"),
*not* `HK…Identifier` strings — the wire↔HK bridge that derives storage membership
from E4's `WHITELISTED_TYPES` lives in `app/core/healthkit.py` (TASK-003).

This phase is **models + whitelist filter only**; the `/sync` route, idempotent
upsert, and `SyncResponse` count derivation are E5·P2 / E5·P3.
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from pydantic import Field

from app.api.schemas.base import CamelModel


class RecordType(str, enum.Enum):
    """The wire `HealthRecord.type` enum — exact MODELS "Enums → RecordType" set.

    Values are the snake_case wire strings the Swift client sends. The enum
    accepts every MODELS type (incl. `respiratory_rate`, which is *not* in E4's
    storage whitelist) — acceptance on the wire is decoupled from
    acceptance for storage (`app/core/healthkit.is_record_type_whitelisted`).
    """

    HEART_RATE = "heart_rate"
    HEART_RATE_VARIABILITY_SDNN = "heart_rate_variability_sdnn"
    RESTING_HEART_RATE = "resting_heart_rate"
    SLEEP_ANALYSIS = "sleep_analysis"
    STEP_COUNT = "step_count"
    ACTIVE_ENERGY_BURNED = "active_energy_burned"
    BASAL_ENERGY_BURNED = "basal_energy_burned"
    PHYSICAL_EFFORT = "physical_effort"
    VO2_MAX = "vo2_max"
    BODY_MASS = "body_mass"
    RUNNING_SPEED = "running_speed"
    RUNNING_POWER = "running_power"
    RUNNING_CADENCE = "running_cadence"
    RUNNING_STRIDE_LENGTH = "running_stride_length"
    RUNNING_GROUND_CONTACT_TIME = "running_ground_contact_time"
    RUNNING_VERTICAL_OSCILLATION = "running_vertical_oscillation"
    RESPIRATORY_RATE = "respiratory_rate"
    DIETARY_ENERGY_CONSUMED = "dietary_energy_consumed"
    DIETARY_PROTEIN = "dietary_protein"
    DIETARY_CARBOHYDRATES = "dietary_carbohydrates"
    DIETARY_FAT_TOTAL = "dietary_fat_total"
    DIETARY_FIBER = "dietary_fiber"
    DIETARY_SODIUM = "dietary_sodium"
    DIETARY_WATER = "dietary_water"


class HealthRecord(CamelModel):
    """A single HealthKit sample — **quantity** (`value`+`unit`) **or** category
    (`category`, e.g. a sleep stage). All sample-shape fields are optional
    `T | None = None` so both shapes validate (MODELS "HealthRecord"; "Nulls vs
    absent"). No cross-field "exactly one of" validator — MODELS does not mandate
    it and a category sample may also carry a `value`.
    """

    uuid: str
    type: RecordType
    start: datetime
    end: datetime
    value: float | None = None
    unit: str | None = None
    category: str | None = None
    source: str | None = None
    metadata: dict | None = None


class WorkoutStat(CamelModel):
    """One aggregate stat for a workout (e.g. `avg_hr`, `max_speed`).

    `type` is a free `str` — MODELS shows it as a bare string and lists no
    validation, so a forward-compatible stat type is accepted (PLAN Decisions).
    """

    type: str
    value: float
    unit: str


class Workout(CamelModel):
    """A workout session. `type` is the free HealthKit activity-type string
    (e.g. `boxing`, `running`); `zone_minutes` is a tolerant `str→float` map of
    the `z1…z5` payload rather than a typed `Zone` map (MODELS Workout).
    """

    uuid: str
    type: str
    start: datetime
    end: datetime
    duration_s: float
    distance_m: float | None = None
    active_energy_kcal: float | None = None
    effort_score: int | None = None
    zone_minutes: dict[str, float] | None = None
    statistics: list[WorkoutStat] = []


class ActivitySummary(CamelModel):
    """A per-day activity-ring summary (MODELS ActivitySummary)."""

    date: date
    active_energy_kcal: float
    exercise_minutes: int
    stand_hours: int
    steps: int | None = None


class DailyCheckin(CamelModel):
    """The objective-only daily check-in (epic R7; MODELS DailyCheckin).

    **No body-weight field** — weight arrives as a `body_mass` HealthRecord
    (single live-weight source, DB.md §1). `knee_pain` is bounded 0–10.
    """

    date: date
    gi_symptoms: bool
    knee_pain: int = Field(ge=0, le=10)
    illness: bool


class StrengthTest(CamelModel):
    """The periodic strength benchmark (MODELS StrengthTest)."""

    date: date
    max_pushups: int
    max_pullups: int


class SyncRequest(CamelModel):
    """The `POST /sync` request envelope (MODELS SyncRequest). Every collection
    defaults empty and both top-level singletons default `None`, so a minimal
    `{}` body validates.
    """

    records: list[HealthRecord] = []
    workouts: list[Workout] = []
    activity_summary: list[ActivitySummary] = []
    checkin: DailyCheckin | None = None
    strength_test: StrengthTest | None = None


class SyncResponse(CamelModel):
    """The `POST /sync` response envelope (MODELS SyncResponse). This phase
    defines the *shape*; populating the counts from DB writes is E5·P2.
    """

    records_upserted: int
    records_duplicate: int
    workouts_upserted: int
    activity_days_upserted: int
    checkin_saved: bool
    strength_test_saved: bool
    server_time: datetime
