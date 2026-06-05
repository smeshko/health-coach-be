"""`daily_metrics` recompute engine (E6·P1) — the deterministic per-day half.

This is the **engine** behind the E5·P3 seam: `DailyMetricsEngine.__call__(dates)`
rebuilds each affected Europe/Sofia day's `daily_metrics` row from the committed
`records`/`workouts` rows (sleep / HRV / RHR / zone-minutes / steps / active energy /
the seven nutrition aggregates / latest body weight / `hard_day`) and **idempotently
upserts** it with a fresh `computed_at`. It is wired into `/sync` by swapping the
E5·P3 recompute *provider* — no route logic changes.

Two whole families of columns are deliberately left untouched here: the 30-day
rolling baselines `hrv_30d_mean`/`hrv_30d_sd`/`rhr_30d_mean` (E6·P2) and
`readiness_score`/`band` (E8/E11). The `ON CONFLICT(date) DO UPDATE` `set_`
**excludes** those five so a per-day re-run never clobbers a value a later phase
wrote (DB.md §2 note; epic §3/§7).

Recompute-from-source (DECISIONS.md Decision 1): a day's metrics are a pure function
of that day's stored rows, so a re-run is idempotent and a late/duplicate sync
self-heals. Pure service — no FastAPI/HTTP imports (mirrors E5·P2/E5·P3).

The per-metric helpers (`sleep_h`, `hrv_sdnn`, …) are filled by TASK-002/003; this
module lands the engine shape + the idempotent upsert + the provider swap.
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.core.healthkit import RECORD_TYPE_TO_HK
from app.core.profile import Profile, load_profile
from app.core.time import SOFIA, now_sofia, parse_ts, to_sofia
from app.database.engine import SessionLocal
from app.database.models import DailyMetrics, Records, Workouts
from app.services.recompute import RecomputeDailyMetrics

# The seven nutrition-intake columns, in DB.md §2 order (filled by TASK-003).
NUTRITION_COLUMNS: tuple[str, ...] = (
    "kcal_in",
    "protein_in_g",
    "carbs_in_g",
    "fat_in_g",
    "fiber_in_g",
    "sodium_in_mg",
    "water_in_l",
)
# The five HR zone-minute columns (filled by TASK-002).
ZONE_COLUMNS: tuple[str, ...] = ("z1_min", "z2_min", "z3_min", "z4_min", "z5_min")

# The three rolling 30-day readiness-baseline columns (E6·P2 writes these now —
# they were excluded from P1's upsert and are folded into `recompute_day`'s `set_`).
BASELINE_COLUMNS: tuple[str, ...] = ("hrv_30d_mean", "hrv_30d_sd", "rhr_30d_mean")

# Columns a recompute MUST NOT touch: the readiness verdict (E8/E11). They are never
# put in the upsert `values`, so they stay null on a first insert and survive every
# re-run (the `set_` is built from the computed `values`). E6·P2 moved the three 30-day
# baselines OUT of this set — they now update on every recompute (DECISIONS round-1 #4).
PRESERVED_COLUMNS: tuple[str, ...] = ("readiness_score", "band")

# The minimum non-null readings in the trailing-30-day window for a usable baseline;
# below this the baseline column(s) are None (a 30-day SD off 1-2 points is noise) —
# DECISIONS Decision 3. Checked per metric independently.
MIN_BASELINE_SAMPLES = 10


# Category sleep-stage values (stored in `value_text`) that count as ASLEEP — the
# asleep* family, NOT `inBed`/`awake`. Matched case-insensitively (DB.md §1; round-2 #2).
ASLEEP_STAGES: frozenset[str] = frozenset(
    {"asleep", "asleepunspecified", "asleepcore", "asleepdeep", "asleeprem"}
)

# Third-party workout apps — rank 3 (below the iPhone/other rank-2 tier) in the
# source-priority pick (DECISIONS.md Decision 4). Lower-cased, whitespace-normalized.
THIRD_PARTY_WORKOUT_APPS: frozenset[str] = frozenset(
    {"strava", "nike run club", "nike training club", "ntc", "runkeeper", "komoot"}
)

# The five zone keys (without the `_min` suffix), in order.
_ZONE_KEYS: tuple[str, ...] = ("z1", "z2", "z3", "z4", "z5")


# ---------------------------------------------------------------------------
# Stored-type normalization (review round-1 #1, #2).
#
# `app.db.records`/`workouts` hold BOTH origins: live `/sync` rows store the
# snake_case `RecordType` value (E5·P2 `r.type.value`, e.g. `heart_rate`), while the
# E4 seed copies Apple-Health rows VERBATIM — `records.type` as `HK…Identifier`,
# sleep `value_text` as `HKCategoryValueSleepAnalysis…`, `workouts.activity_type` as
# `HKWorkoutActivityType…`. The seed's HK form is load-bearing for E4's aggregate
# queries, so the engine canonicalizes BOTH forms at read time rather than touching
# the seed — otherwise the entire seeded history recomputes to null metrics.
_HK_TO_SNAKE_RECORD_TYPE: dict[str, str] = {hk: snake for snake, hk in RECORD_TYPE_TO_HK.items()}
_SLEEP_VALUE_PREFIX = "HKCategoryValueSleepAnalysis"
_HK_WORKOUT_PREFIX = "HKWorkoutActivityType"
_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _canonical_record_type(type_: str | None) -> str:
    """Map a stored `records.type` to its snake_case form (HK identifier → snake;
    snake passes through). So a seeded `HKQuantityTypeIdentifierStepCount` and a live
    `step_count` collapse to the same `step_count`."""
    return _HK_TO_SNAKE_RECORD_TYPE.get(type_ or "", type_ or "")


def _record_type_aliases(types: set[str]) -> set[str]:
    """Expand snake_case record types to also include the seeded HK-identifier form,
    so a single `Records.type.in_(...)` (index-backed) matches both origins."""
    aliases = set(types)
    aliases.update(RECORD_TYPE_TO_HK[t] for t in types if t in RECORD_TYPE_TO_HK)
    return aliases


def _canonical_sleep_stage(value_text: str | None) -> str:
    """Lower-cased sleep stage with the seeded `HKCategoryValueSleepAnalysis` prefix
    stripped, so `HKCategoryValueSleepAnalysisAsleepCore` and `asleepCore` both →
    `asleepcore`."""
    s = (value_text or "").strip()
    if s.startswith(_SLEEP_VALUE_PREFIX):
        s = s[len(_SLEEP_VALUE_PREFIX) :]
    return s.lower()


def _canonical_activity_type(activity_type: str | None) -> str:
    """Lower-cased snake_case workout activity type. Strips the seeded
    `HKWorkoutActivityType` prefix and splits CamelCase, so
    `HKWorkoutActivityTypeHighIntensityIntervalTraining` and a live
    `high_intensity_interval_training` both → `high_intensity_interval_training`."""
    s = (activity_type or "").strip()
    if s.startswith(_HK_WORKOUT_PREFIX):
        s = _CAMEL_BOUNDARY.sub("_", s[len(_HK_WORKOUT_PREFIX) :])
    return s.lower()


# ---------------------------------------------------------------------------
# Shared readers + source de-duplication (DECISIONS.md Decision 4).
# ---------------------------------------------------------------------------
def source_rank(source_name: str | None) -> int:
    """Source priority for the device-cumulative pick — lower = higher priority.

    Keys on capabilities, not phone hostnames (which change per device), so a phone
    swap can't break it: anything unrecognised falls to the rank-2 "phone/other"
    tier, which the Watch (rank 0) outranks on a normal day (DECISIONS.md Decision 4).
    """
    s = (source_name or "").lower().replace(" ", " ").strip()
    if "apple watch" in s:
        return 0  # wrist truth
    if "garmin" in s or s == "connect":
        return 1  # Garmin Connect
    if s in THIRD_PARTY_WORKOUT_APPS:
        return 3  # strava / nike run club / …
    return 2  # iPhone hostnames & unknown → phone/other


def _window(day: date) -> tuple[str, str]:
    """A ±1-day TEXT `start_date` range around `day` (covers any offset/DST skew).

    `records.start_date` is ISO-8601 TEXT prefixed `YYYY-MM-DD`, so a lexical range
    on the date prefix uses the `(type, start_date)` index while the precise Sofia-date
    filter runs in Python. ±1 day is wide enough for every real offset (< 24h).
    """
    return (day - timedelta(days=1)).isoformat(), (day + timedelta(days=2)).isoformat()


def _days_spanned(start_date: str, end_date: str) -> set[date]:
    """Every Sofia calendar day the interval `[start_date, end_date]` touches (inclusive)."""
    start = to_sofia(parse_ts(start_date)).date()
    end = to_sofia(parse_ts(end_date)).date()
    days, d = set(), start
    while d <= end:
        days.add(d)
        d += timedelta(days=1)
    return days


def _hr_overlap_days(start_date: str, end_date: str) -> set[date]:
    """Sofia days the HR interval `[start, end)` has POSITIVE overlap with (half-open, so
    a sample ending exactly at midnight does NOT count toward the next day) — matches how
    zone-minutes credit in-day overlap (review round-4 #1)."""
    start, end = parse_ts(start_date), parse_ts(end_date)
    if end <= start:
        return {to_sofia(start).date()}
    days: set[date] = set()
    d = to_sofia(start).date()
    last = to_sofia(end).date()
    while d <= last:
        day_start = datetime.combine(d, time.min, tzinfo=SOFIA)
        day_end = day_start + timedelta(days=1)
        if start < day_end and end > day_start:  # half-open overlap > 0
            days.add(d)
        d += timedelta(days=1)
    return days


def _contribution_days(type_: str | None, start_date: str, end_date: str | None) -> set[date]:
    """The Sofia day(s) a row contributes its metric to — exactly how the engine READS
    it: a `heart_rate` interval to every day it positively overlaps (half-open),
    `sleep_analysis` to its wake/end day, every other (instant) record / workout to its
    start day. Coverage uses this so it stays consistent with cross-midnight attribution
    (review round-3 #1, round-4 #1)."""
    canon = _canonical_record_type(type_)
    if end_date is not None:
        if canon == "heart_rate":
            return _hr_overlap_days(start_date, end_date)
        if canon == "sleep_analysis":
            return {to_sofia(parse_ts(end_date)).date()}
    return {to_sofia(parse_ts(start_date)).date()}


def _day_is_sync_covered(session: Session, day: date) -> bool:
    """True iff ≥1 live `origin='sync'` row contributes to Sofia `day` (HR overlap, sleep
    wake, else start day). On such a "fully covered" day the seed estimate for the whole
    day is superseded (mirrors `reconcile_seed.py`'s "live sync is authoritative"), so the
    engine drops `day`'s seed rows at read time — matched to the day being recomputed, so a
    sync interval that only reaches a *neighbour* day never supersedes seed data on a day it
    does not actually cover (review round-3 #1 / round-4 #1)."""
    lo, hi = _window(day)
    rec_rows = session.execute(
        select(Records.type, Records.start_date, Records.end_date)
        .where(Records.origin == "sync")
        .where(Records.start_date >= lo)
        .where(Records.start_date < hi)
    ).all()
    if any(day in _contribution_days(type_, sd, ed) for type_, sd, ed in rec_rows):
        return True
    wk_rows = session.execute(
        select(Workouts.activity_type, Workouts.start_date, Workouts.end_date)
        .where(Workouts.origin == "sync")
        .where(Workouts.start_date >= lo)
        .where(Workouts.start_date < hi)
    ).all()
    return any(day in _contribution_days(at, sd, ed) for at, sd, ed in wk_rows)


def _drop_superseded_seed(rows: Sequence, *, covered: bool) -> list:
    """When the recomputed day is sync-covered, drop ALL `origin='seed'` rows (live sync is
    authoritative for the whole day); otherwise keep every row. Targeted at the day being
    recomputed, so legitimately un-superseded seed data on an uncovered day is never erased
    (review round-4 #1). Works on `Records` or `Workouts` rows."""
    if not covered:
        return list(rows)
    return [r for r in rows if r.origin != "seed"]


def _records_of_types(session: Session, day: date, types: set[str]) -> Sequence[Records]:
    """The `records` rows of the given `type`s within the ±1-day window around `day`,
    with seed rows on sync-covered days dropped (read-time reconcile)."""
    lo, hi = _window(day)
    stmt = (
        select(Records)
        .where(Records.type.in_(_record_type_aliases(types)))
        .where(Records.start_date >= lo)
        .where(Records.start_date < hi)
    )
    rows = session.execute(stmt).scalars().all()
    return _drop_superseded_seed(rows, covered=_day_is_sync_covered(session, day))


def _instant_records(session: Session, day: date, types: set[str]) -> list[Records]:
    """Records whose **start** instant lands on the Sofia `day` (instant attribution)."""
    return [
        r
        for r in _records_of_types(session, day, types)
        if to_sofia(parse_ts(r.start_date)).date() == day
    ]


def _choose_source(rows: Iterable[Records], weight: Callable[[Records], float]) -> str | None:
    """The single source_name for the day: min `source_rank`, then larger weighted
    total, then `source_name` (deterministic) — DECISIONS.md Decision 4."""
    by_source: dict[str | None, list[Records]] = {}
    for r in rows:
        by_source.setdefault(r.source_name, []).append(r)

    def key(item: tuple[str | None, list[Records]]) -> tuple[int, float, str]:
        source, srows = item
        return (source_rank(source), -sum(weight(r) for r in srows), source or "")

    return min(by_source.items(), key=key)[0]


def _picked_source_rows(rows: list[Records], weight: Callable[[Records], float]) -> list[Records]:
    """Keep only the rows of the day's highest-priority source (Decision 4)."""
    if not rows:
        return []
    chosen = _choose_source(rows, weight)
    return [r for r in rows if r.source_name == chosen]


def _sofia_day_bounds(day: date) -> tuple[datetime, datetime]:
    """The `[start, end)` Sofia-local instants bounding `day` (00:00..next 00:00)."""
    start = datetime.combine(day, time.min, tzinfo=SOFIA)
    return start, start + timedelta(days=1)


def _in_day_overlap_seconds(r: Records, day: date) -> float:
    """Seconds of `[start_date, end_date]` that fall inside the Sofia `day`."""
    if r.end_date is None:
        return 0.0
    start, end = parse_ts(r.start_date), parse_ts(r.end_date)
    day_start, day_end = _sofia_day_bounds(day)
    lo, hi = max(start, day_start), min(end, day_end)
    return max(0.0, (hi - lo).total_seconds())


# ---------------------------------------------------------------------------
# Activity / recovery metrics (TASK-002).
# ---------------------------------------------------------------------------
def sleep_h(session: Session, day: date) -> float | None:
    """Last night's asleep hours, anchored WHOLLY to the wake/end Sofia day.

    An asleep `sleep_analysis` block is credited in full to
    `to_sofia(parse_ts(end_date)).date()` — NOT split — so a 23:30→07:00 night puts
    its entire 7.5h on the wake (morning) row and 0 on the prior day (round-2 #2;
    DB.md §2). Sums all asleep blocks whose wake day is `day`; `None` if none.
    """
    asleep = [
        r
        for r in _records_of_types(session, day, {"sleep_analysis"})
        if r.end_date is not None
        and _canonical_sleep_stage(r.value_text) in ASLEEP_STAGES
        and to_sofia(parse_ts(r.end_date)).date() == day
    ]
    if not asleep:
        return None
    seconds = sum((parse_ts(r.end_date) - parse_ts(r.start_date)).total_seconds() for r in asleep)
    return seconds / 3600.0


def _pick_instant_reading(rows: list[Records]) -> float | None:
    """One reading from same-day instant samples: highest `source_rank`, then the
    latest instant (DECISIONS.md Decision 4 instant pick). `None` if no rows."""
    candidates = [r for r in rows if r.value is not None]
    if not candidates:
        return None
    best = min(
        candidates,
        key=lambda r: (source_rank(r.source_name), -parse_ts(r.start_date).timestamp()),
    )
    return best.value


def hrv_sdnn(session: Session, day: date) -> float | None:
    """This-morning HRV SDNN from the day's `heart_rate_variability_sdnn` records."""
    return _pick_instant_reading(_instant_records(session, day, {"heart_rate_variability_sdnn"}))


def rhr(session: Session, day: date) -> float | None:
    """This-morning resting HR from the day's `resting_heart_rate` records."""
    return _pick_instant_reading(_instant_records(session, day, {"resting_heart_rate"}))


def steps(session: Session, day: date) -> int | None:
    """Source-deduped sum of the day's `step_count` records (Decision 4).

    Picks the single highest-priority `source_name` and sums only its rows — a blind
    SUM doubles steps because the Watch and the iPhone both log the same walking
    (≈ ×2). `None` when no `step_count` record; a real `0` from the picked source → 0.
    """
    rows = _instant_records(session, day, {"step_count"})
    if not rows:
        return None
    picked = _picked_source_rows(rows, weight=lambda r: r.value or 0.0)
    return int(round(sum(r.value or 0.0 for r in picked)))


def active_energy(session: Session, day: date) -> float | None:
    """Source-deduped sum of the day's `active_energy_burned` records (kcal; Decision 4)."""
    rows = _instant_records(session, day, {"active_energy_burned"})
    if not rows:
        return None
    picked = _picked_source_rows(rows, weight=lambda r: r.value or 0.0)
    return sum(r.value or 0.0 for r in picked)


def _bucket_zone(bpm: float, bounds: dict[str, tuple[int, int]]) -> str | None:
    """The zone key (`z1`…`z5`) for `bpm` under `low <= bpm < high`; the top bound
    (`bpm == z5.high == max_hr`) lands in z5. `None` below z1 / above z5."""
    for z in _ZONE_KEYS:
        low, high = bounds[z]
        if low <= bpm < high:
            return z
    if bpm == bounds["z5"][1]:
        return "z5"
    return None


def zone_minutes(session: Session, day: date, *, profile: Profile) -> dict[str, float | None]:
    """HR zone-minutes for `day`, bucketed against `profile.zone_bounds()`.

    Restricts to the single highest-priority HR source first (Decision 4 — so
    overlapping dual-device HR can't double-count), then credits each sample's
    **in-day** minutes (split at the Sofia midnight; round-1 #2) to its zone. A day
    with no overlapping HR sample → every `z*_min` is `None` (no-data convention).
    """
    overlapping = [
        r
        for r in _records_of_types(session, day, {"heart_rate"})
        if r.value is not None and _in_day_overlap_seconds(r, day) > 0
    ]
    if not overlapping:
        return {col: None for col in ZONE_COLUMNS}
    picked = _picked_source_rows(overlapping, weight=lambda r: 1.0)
    bounds = profile.zone_bounds()
    minutes = {z: 0.0 for z in _ZONE_KEYS}
    for r in picked:
        zone = _bucket_zone(r.value, bounds)
        if zone is not None:
            minutes[zone] += _in_day_overlap_seconds(r, day) / 60.0
    return {f"{z}_min": minutes[z] for z in _ZONE_KEYS}


# ---------------------------------------------------------------------------
# Nutrition + body weight + hard_day (TASK-003).
# ---------------------------------------------------------------------------
# Dietary `records.type` (snake_case, the form E5·P2 stores) → daily_metrics column.
DIETARY_TYPE_TO_COLUMN: dict[str, str] = {
    "dietary_energy_consumed": "kcal_in",
    "dietary_protein": "protein_in_g",
    "dietary_carbohydrates": "carbs_in_g",
    "dietary_fat_total": "fat_in_g",
    "dietary_fiber": "fiber_in_g",
    "dietary_sodium": "sodium_in_mg",
    "dietary_water": "water_in_l",
}
_KCAL_TYPE = "dietary_energy_consumed"

# `hard_day` predicate constants (DECISIONS.md Decision 3) — matched case-insensitively.
HARD_ACTIVITY_TYPES: frozenset[str] = frozenset(
    {"boxing", "high_intensity_interval_training", "kickboxing", "martial_arts"}
)
LONG_DURATION_MIN: float = 90.0  # minutes; "long" session fallback, BOUNDARY INCLUSIVE (>=)
_SECONDS_UNITS: frozenset[str] = frozenset({"s", "sec", "secs", "second", "seconds"})
_MINUTES_UNITS: frozenset[str] = frozenset({"min", "mins", "minute", "minutes", ""})


def _dominant_dietary_source(rows: list[Records]) -> str | None:
    """The day's dominant nutrition app: largest same-day `kcal_in`, then dietary-record
    count, then `source_name` (DECISIONS.md Decision 4 — nutrition is single-dominant-app,
    NOT a cross-source sum)."""
    by_source: dict[str | None, list[Records]] = {}
    for r in rows:
        by_source.setdefault(r.source_name, []).append(r)

    def kcal(srows: list[Records]) -> float:
        return sum(r.value or 0.0 for r in srows if _canonical_record_type(r.type) == _KCAL_TYPE)

    def key(item: tuple[str | None, list[Records]]) -> tuple[float, int, str]:
        source, srows = item
        return (-kcal(srows), -len(srows), source or "")

    return min(by_source.items(), key=key)[0]


def nutrition_intake(session: Session, day: date) -> dict[str, float | None]:
    """The seven nutrition-intake aggregates from the day's **dominant app** (Decision 4).

    Different nutrition apps hold different food entries, so a cross-source sum would
    double-count an app-switch day. Picks the single dominant `source_name` (max
    same-day `kcal_in`) and sums only its rows by type. A column with no dietary record
    of its type in the dominant source → `None`; a real `0` total → `0`.
    """
    result: dict[str, float | None] = {col: None for col in NUTRITION_COLUMNS}
    rows = _instant_records(session, day, set(DIETARY_TYPE_TO_COLUMN))
    if not rows:
        return result
    dominant = _dominant_dietary_source(rows)
    by_type: dict[str, list[Records]] = {}
    for r in rows:
        if r.source_name == dominant:
            by_type.setdefault(_canonical_record_type(r.type), []).append(r)
    for type_, column in DIETARY_TYPE_TO_COLUMN.items():
        if type_ in by_type:
            result[column] = sum(r.value or 0.0 for r in by_type[type_])
    return result


def body_weight(session: Session, day: date) -> float | None:
    """The **latest** `body_mass` of the day by actual instant (NOT raw TEXT order).

    Stored timestamps carry varying offsets, so a lexical sort can rank an
    earlier-instant reading after a later one (round-1 #3). Parses each timestamp to an
    instant and takes the max (tie-break: creation instant, then `id`). NOT first/avg —
    the single live-weight source for TDEE/macros. `None` when no `body_mass`.
    """
    candidates = [r for r in _instant_records(session, day, {"body_mass"}) if r.value is not None]
    if not candidates:
        return None

    def instant_key(r: Records) -> tuple[float, float, int]:
        creation = parse_ts(r.creation_date) if r.creation_date else parse_ts(r.start_date)
        return (parse_ts(r.start_date).timestamp(), creation.timestamp(), r.id or 0)

    return max(candidates, key=instant_key).value


def current_body_weight(session: Session, anchor: date) -> float | None:
    """The athlete's **current/live** weight: the latest **positive** materialised
    `daily_metrics.body_weight` on or before `anchor` (E13·P3).

    The multi-day ("≤ anchor") counterpart to `body_weight(session, day)` — where that reads
    the single day's live weight, this walks back to the most recent day that *has* one, so a
    week whose anchor day has no scale reading still resolves a real weight. Reads the
    **materialised** column (the recompute engine already deduped the day's `body_mass` into it
    — DECISIONS Decision 1), not raw `Records`. `DailyMetrics.date` is TEXT ISO-8601, so a
    lexical `<=` + `ORDER BY date DESC` selects the chronologically latest reading on/before the
    anchor.

    Only **finite positive** weights qualify: a materialised `0`/negative/NaN/`±inf` from bad
    HealthKit `body_mass` (the sync `value` is an unconstrained float) is garbage, not a usable
    weight, so it is **skipped** — the walk-back continues to the latest valid reading rather
    than letting a bad value reach the macro engine, which would 5xx the brief (a non-positive
    trips the positive-weight guard; `+inf` passes `> 0` and the guard, then `_round_half_up`
    raises `OverflowError` — review rounds 1-2). The SQL `> 0` excludes NULL/NaN/zero/negative;
    `+inf` is a positive REAL in SQLite, so the `math.isfinite` filter drops it in Python.
    Returns `None` when no finite-positive reading exists at/before the anchor (caller falls
    back to `goal_weight_kg`).
    """
    candidates = session.scalars(
        select(DailyMetrics.body_weight)
        .where(
            DailyMetrics.body_weight > 0,
            DailyMetrics.date <= anchor.isoformat(),
        )
        .order_by(DailyMetrics.date.desc())
    ).all()
    return next((w for w in candidates if math.isfinite(w)), None)


def _duration_minutes(w: Workouts) -> float:
    """Normalize a workout's `duration` to minutes via `duration_unit` (s→/60, min
    pass-through; unknown unit → 0 so only `activity_type` can flag it)."""
    if w.duration is None:
        return 0.0
    unit = (w.duration_unit or "").strip().lower()
    if unit in _SECONDS_UNITS:
        return w.duration / 60.0
    if unit in _MINUTES_UNITS:
        return w.duration
    return 0.0


def hard_day(session: Session, day: date) -> int:
    """Deterministic 0/1 hard-session flag from the day's `workouts` (DECISIONS.md
    Decision 3): `1` if any workout's `activity_type` is in `HARD_ACTIVITY_TYPES` **or**
    its duration (normalized to minutes) is `>= LONG_DURATION_MIN`; else `0`. Always a
    real `0`/`1` — never `None` (a flag, not a measurement)."""
    lo, hi = _window(day)
    stmt = select(Workouts).where(Workouts.start_date >= lo).where(Workouts.start_date < hi)
    workouts = _drop_superseded_seed(
        session.execute(stmt).scalars().all(), covered=_day_is_sync_covered(session, day)
    )
    for w in workouts:
        if to_sofia(parse_ts(w.start_date)).date() != day:
            continue
        if _canonical_activity_type(w.activity_type) in HARD_ACTIVITY_TYPES:
            return 1
        if _duration_minutes(w) >= LONG_DURATION_MIN:
            return 1
    return 0


def _sofia_days_spanned(r: Records) -> set[date]:
    """Every Sofia day the interval `[start_date, end_date]` touches (inclusive)."""
    if r.end_date is None:
        return set()
    return _days_spanned(r.start_date, r.end_date)


def expand_affected_dates(session: Session, dates: set[date]) -> set[date]:
    """Expand the handed dates to every Sofia day an overlapping interval reaches.

    E5·P3's `affected_dates` is **start-date** based, so a cross-midnight HR sample
    or a sleep block whose wake day differs from its start day touches a Sofia day it
    did not fan out. The engine owns its work-set, so it widens `dates` here before
    recomputing — both neighbour rows refresh from one sync (round-2 #1). E5·P3's
    `affected_dates` is unchanged.
    """
    expanded = set(dates)
    for day in dates:
        for r in _records_of_types(session, day, {"heart_rate"}):
            if _in_day_overlap_seconds(r, day) > 0:
                expanded |= _sofia_days_spanned(r)
        for r in _records_of_types(session, day, {"sleep_analysis"}):
            if r.end_date is None:
                continue
            start_day = to_sofia(parse_ts(r.start_date)).date()
            wake_day = to_sofia(parse_ts(r.end_date)).date()
            if day in (start_day, wake_day):
                expanded |= {start_day, wake_day}
    return expanded


def _expand_forward_window(session: Session, days: set[date], *, span: int = 29) -> set[date]:
    """Add the existing `daily_metrics` rows in `[d + 1, d + span]` for each day `d`.

    Editing day `d`'s `hrv_sdnn`/`rhr` changes the rolling baseline of every day whose
    trailing-30-day window now contains `d` — i.e. `[d, d + 29]` — so the engine must
    refresh those forward rows or the canonical series goes stale (E6·P2; round-1 #2).
    **Unconditional, not change-gated** (round-2 #1): the seam hands only a `set[date]`
    and `recompute_day` returns `None`, so there is no cheap old-vs-new signal — and none
    is needed, because recompute is idempotent and cheap (a non-changed day recomputes to
    the same baseline, only `computed_at` advances; ≤`span` indexed single-row recomputes
    per day, single-user). Bounded to **existing** rows (a row at `d + 30` can't contain
    `d`); the engine owns its work-set, E5·P3's `affected_dates` is unchanged.
    """
    expanded = set(days)
    for d in days:
        start = (d + timedelta(days=1)).isoformat()
        end = (d + timedelta(days=span)).isoformat()
        forward = session.execute(
            select(DailyMetrics.date).where(DailyMetrics.date.between(start, end))
        ).scalars().all()
        expanded.update(date.fromisoformat(s) for s in forward)
    return expanded


# ---------------------------------------------------------------------------
# Rolling 30-day readiness baselines (E6·P2) — a windowed reduction over the
# MATERIALIZED per-day `hrv_sdnn`/`rhr` columns P1 wrote (DB.md §2 "single source …
# windowed sums"), NOT a re-read of raw `records`. The readiness baseline is the
# rolling daily series, never the monthly `profile.yaml` anchor (DB.md §5 ¹).
# ---------------------------------------------------------------------------
def window_readings(
    session: Session, day: date, *, days: int = 30
) -> tuple[list[float], list[float]]:
    """The non-null `hrv_sdnn` and `rhr` values of the `daily_metrics` rows in the
    trailing calendar window **inclusive of D**: `[day - (days-1), day]`.

    The `date` PK is already a Sofia `YYYY-MM-DD` string, so a lexical `BETWEEN` over
    it **is** the calendar range — no `parse_ts`/tz math (P1 attributed each sample to
    its Sofia date). The two metrics are filtered **independently** (`IS NOT NULL`), so
    a day with HRV but no RHR contributes to the HRV list only, and absence never
    enters the mean/SD as a fabricated 0 (DECISIONS null-vs-zero). `days` is keyword-only
    (default 30) so a test can shrink the window for a small fixture.
    """
    start = (day - timedelta(days=days - 1)).isoformat()
    end = day.isoformat()
    hrv = session.execute(
        select(DailyMetrics.hrv_sdnn).where(
            DailyMetrics.date.between(start, end), DailyMetrics.hrv_sdnn.is_not(None)
        )
    ).scalars().all()
    rhr_vals = session.execute(
        select(DailyMetrics.rhr).where(
            DailyMetrics.date.between(start, end), DailyMetrics.rhr.is_not(None)
        )
    ).scalars().all()
    return list(hrv), list(rhr_vals)


def hrv_baseline(hrv_values: list[float]) -> tuple[float | None, float | None]:
    """The rolling HRV baseline `(mean, population SD)` over the window's non-null
    `hrv_sdnn`, or `(None, None)` when fewer than `MIN_BASELINE_SAMPLES` readings.

    **Population** SD (`statistics.pstdev`, ÷N — DECISIONS Decision 1), not sample SD:
    §6.1 uses it as a "1 SD below my own 30-day spread" distance, and it is defined at
    N=1 (→0); the min-sample floor keeps N well above that for any used baseline. Mean
    and SD reduce over the SAME list and are gated together — never one-set-one-null.
    """
    if len(hrv_values) >= MIN_BASELINE_SAMPLES:
        return statistics.fmean(hrv_values), statistics.pstdev(hrv_values)
    return None, None


def rhr_baseline(rhr_values: list[float]) -> float | None:
    """The rolling RHR baseline **mean** over the window's non-null `rhr`, or `None`
    below `MIN_BASELINE_SAMPLES`. **No SD** — DB.md §2 has only `rhr_30d_mean` (RHR's
    §6.1 penalty is an absolute "+5-7 bpm" band, not an SD distance)."""
    if len(rhr_values) >= MIN_BASELINE_SAMPLES:
        return statistics.fmean(rhr_values)
    return None


# ---------------------------------------------------------------------------
# Per-day assembly + idempotent upsert.
# ---------------------------------------------------------------------------
def _compute_day_values(session: Session, day: date, *, profile: Profile) -> dict[str, object]:
    """Assemble the P1 column values for one Sofia `day` from its source rows.

    Returns only the columns this phase computes (every `daily_metrics` write
    column **except** the five `PRESERVED_COLUMNS` and `date`/`computed_at`, which
    `recompute_day` adds). The per-metric helpers own each value.
    """
    values: dict[str, object] = {
        "sleep_h": sleep_h(session, day),
        "hrv_sdnn": hrv_sdnn(session, day),
        "rhr": rhr(session, day),
        "steps": steps(session, day),
        "active_energy": active_energy(session, day),
        "body_weight": body_weight(session, day),
        "hard_day": hard_day(session, day),
    }
    values.update(zone_minutes(session, day, profile=profile))
    values.update(nutrition_intake(session, day))
    return values


def _upsert_daily_metrics(session: Session, values: dict[str, object]) -> None:
    """Idempotent `INSERT … ON CONFLICT(date) DO UPDATE` over the `date` PK. The `set_`
    rewrites every key except `date`; columns absent from `values` (notably the
    `PRESERVED_COLUMNS` readiness verdict) are never referenced, so they survive."""
    stmt = insert(DailyMetrics).values(**values)
    update_set = {col: stmt.excluded[col] for col in values if col != "date"}
    stmt = stmt.on_conflict_do_update(index_elements=["date"], set_=update_set)
    session.execute(stmt)


def recompute_day(session: Session, day: date, *, profile: Profile) -> None:
    """Rebuild one Sofia day's `daily_metrics` row and idempotently upsert it.

    The row is a pure function of `day`'s stored rows (recompute-from-source), so a
    re-run rewrites the same computed columns with a fresh `computed_at`. Two passes
    over the `date` PK: (1) write D's per-day P1 columns, then **flush** so the
    rolling-baseline read sees D's own fresh `hrv_sdnn`/`rhr` (the trailing window is
    inclusive of D — DECISIONS 2); (2) reduce the trailing-30-day window into
    `hrv_30d_mean`/`hrv_30d_sd`/`rhr_30d_mean` and write them. Neither pass touches
    `PRESERVED_COLUMNS` (`readiness_score`/`band`, E8/E11), so they survive. No commit —
    the engine entry point owns the transaction.
    """
    values = _compute_day_values(session, day, profile=profile)
    values["date"] = day.isoformat()
    values["computed_at"] = now_sofia().isoformat()
    _upsert_daily_metrics(session, values)
    session.flush()  # make D's fresh hrv_sdnn/rhr visible to the inclusive window read

    hrv_vals, rhr_vals = window_readings(session, day)
    hrv_30d_mean, hrv_30d_sd = hrv_baseline(hrv_vals)
    rhr_30d_mean = rhr_baseline(rhr_vals)
    _upsert_daily_metrics(
        session,
        {
            "date": day.isoformat(),
            "hrv_30d_mean": hrv_30d_mean,
            "hrv_30d_sd": hrv_30d_sd,
            "rhr_30d_mean": rhr_30d_mean,
        },
    )


class DailyMetricsEngine:
    """Concrete `RecomputeDailyMetrics` (E5·P3 protocol) — the real `/sync` engine.

    Opens its **own** `SessionLocal()` and commits there: E5·P3 fires recompute
    **after** `/sync`'s commit, so an engine error can't roll back a good ingest
    (the failure instead surfaces as a 5xx; the day re-derives on the next sync —
    round-2 #4). An empty `dates` set returns **before** any DB/profile I/O so an
    empty affected set cannot fail on a DB/settings or `profile.yaml` problem
    (round-1 #1).
    """

    def __call__(self, dates: set[date]) -> None:
        if not dates:
            return
        session = SessionLocal()
        try:
            profile = load_profile()
            work_set = _expand_forward_window(session, expand_affected_dates(session, dates))
            for day in sorted(work_set):  # chronological: a day's window sees earlier rows
                recompute_day(session, day, profile=profile)
            session.commit()
        finally:
            session.close()


def get_engine_recompute() -> RecomputeDailyMetrics:
    """Provider that replaces E5·P3's `noop_recompute` default with the real engine."""
    return DailyMetricsEngine()
