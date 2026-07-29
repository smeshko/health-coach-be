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

# The live iOS exporter sends `HKCategoryValueSleepAnalysis.rawValue` as a bare digit
# (observed in the first real sync 2026-07-23: every `sleep_analysis.value_text` was
# "1".."5", so 62 days of sleep computed to NULL). Map the numeric enum to the same
# canonical stage names the seed's `HKCategoryValueSleepAnalysis…` strings collapse to.
_NUMERIC_SLEEP_STAGES: dict[str, str] = {
    "0": "inbed",
    "1": "asleepunspecified",
    "2": "awake",
    "3": "asleepcore",
    "4": "asleepdeep",
    "5": "asleeprem",
}

# Third-party workout apps — rank 3 (below the iPhone/other rank-2 tier) in the
# source-priority pick (DECISIONS.md Decision 4). Lower-cased, whitespace-normalized.
THIRD_PARTY_WORKOUT_APPS: frozenset[str] = frozenset(
    {"strava", "nike run club", "nike training club", "ntc", "runkeeper", "komoot"}
)

# The five zone keys (without the `_min` suffix), in order.
_ZONE_KEYS: tuple[str, ...] = ("z1", "z2", "z3", "z4", "z5")

# Live Apple-Watch HR samples are POINT samples (`start_date == end_date`; every one of
# the 68k rows in the first real sync), so interval overlap credits them 0 seconds and
# zone-minutes computed to NULL for 62 straight days. An instant sample instead
# represents the HR *until the next reading*: credit it the gap to the next instant
# sample from the same picked source, capped so sparse background readings (Watch
# off-wrist, overnight) can't smear one reading across hours. 5 min ≈ the Watch's
# background sampling cadence; workout-dense sampling (every few seconds) is unaffected.
_INSTANT_HR_MAX_CREDIT_S = 300.0


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
    `asleepcore`. A bare numeric `rawValue` (the live exporter's form, e.g. `"3"`)
    maps through `_NUMERIC_SLEEP_STAGES` to the same canonical name."""
    s = (value_text or "").strip()
    if s.startswith(_SLEEP_VALUE_PREFIX):
        s = s[len(_SLEEP_VALUE_PREFIX) :]
    return _NUMERIC_SLEEP_STAGES.get(s, s.lower())


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


def _overlap_seconds(r: Records, lo: datetime, hi: datetime) -> float:
    """Seconds of the interval `[start_date, end_date]` that fall inside `[lo, hi]`.

    The window-generic core behind `_in_day_overlap_seconds` — a Sofia day and a
    workout's start–end window credit interval samples by exactly the same rule, so
    the two callers cannot drift (corroborated-hard-day TASK-001).
    """
    if r.end_date is None:
        return 0.0
    start, end = parse_ts(r.start_date), parse_ts(r.end_date)
    a, b = max(start, lo), min(end, hi)
    return max(0.0, (b - a).total_seconds())


def _in_day_overlap_seconds(r: Records, day: date) -> float:
    """Seconds of `[start_date, end_date]` that fall inside the Sofia `day`."""
    return _overlap_seconds(r, *_sofia_day_bounds(day))


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


def _is_instant(r: Records) -> bool:
    """A point sample: no end, or end == start (the live Watch HR form)."""
    return r.end_date is None or r.end_date == r.start_date


def _instant_credit_seconds(
    instants: list[Records], lo: datetime, hi: datetime
) -> list[tuple[Records, float]]:
    """Credit each instant sample **starting inside `[lo, hi)`** the gap to the NEXT
    instant sample, capped at `_INSTANT_HR_MAX_CREDIT_S` and clipped to `hi`.

    The window-generic core behind `_instant_hr_credit_seconds`. `instants` is always
    the wider (±1-day) source list, not the in-range subset: the successor supplying a
    boundary sample's gap routinely sits **outside** `[lo, hi)`, so filtering first
    would zero the last in-range sample (corroborated-hard-day round-1 #5). Only the
    very last sample of the whole list has no successor and credits 0 (conservative —
    one background reading's worth at most).
    """
    ordered = sorted(instants, key=lambda r: parse_ts(r.start_date))
    credits: list[tuple[Records, float]] = []
    for i, r in enumerate(ordered):
        start = parse_ts(r.start_date)
        if not lo <= start < hi:
            continue  # a window neighbour: successor material only, credits nothing here
        if i + 1 == len(ordered):
            credits.append((r, 0.0))
            continue
        gap = (parse_ts(ordered[i + 1].start_date) - start).total_seconds()
        credit = min(gap, _INSTANT_HR_MAX_CREDIT_S, (hi - start).total_seconds())
        credits.append((r, max(0.0, credit)))
    return credits


def _instant_hr_credit_seconds(instants: list[Records], day: date) -> list[tuple[Records, float]]:
    """In-day credit for each of `day`'s instant HR samples (see `_instant_credit_seconds`;
    `[lo, hi)` is the Sofia day, and `to_sofia(start).date() == day` is exactly that range)."""
    return _instant_credit_seconds(instants, *_sofia_day_bounds(day))


def _zone_minutes_in_range(
    window_rows: list[Records], lo: datetime, hi: datetime, *, profile: Profile
) -> dict[str, float] | None:
    """Zone-minutes credited inside `[lo, hi)` from `window_rows`, or `None` when no
    sample contributes to that range at all (the "no data" convention).

    The shared crediting core: `zone_minutes` passes the Sofia day bounds,
    `_workout_z45_minutes` passes one workout's start–end window, so the day-level
    column and the classifier's per-workout signal can never drift apart
    (corroborated-hard-day TASK-001). `window_rows` must be the WIDER (±1-day) row set,
    not the in-range subset — the source pick reads the in-range rows, but crediting
    then runs over that source's full row set so a boundary instant still finds its
    successor.
    """

    def contributes(r: Records) -> bool:
        if _is_instant(r):
            return lo <= parse_ts(r.start_date) < hi
        return _overlap_seconds(r, lo, hi) > 0

    in_range = [r for r in window_rows if contributes(r)]
    if not in_range:
        return None
    chosen = _choose_source(in_range, weight=lambda r: 1.0)
    picked_window = [r for r in window_rows if r.source_name == chosen]
    bounds = profile.zone_bounds()
    minutes = {z: 0.0 for z in _ZONE_KEYS}
    credited = [
        (r, _overlap_seconds(r, lo, hi))
        for r in picked_window
        if not _is_instant(r) and contributes(r)
    ]
    credited += _instant_credit_seconds([r for r in picked_window if _is_instant(r)], lo, hi)
    for r, seconds in credited:
        zone = _bucket_zone(r.value, bounds)
        if zone is not None:
            minutes[zone] += seconds / 60.0
    return minutes


def _hr_window_rows(session: Session, day: date) -> list[Records]:
    """`day`'s ±1-day `heart_rate` rows with a value (seed-superseding already applied)."""
    return [r for r in _records_of_types(session, day, {"heart_rate"}) if r.value is not None]


def zone_minutes(session: Session, day: date, *, profile: Profile) -> dict[str, float | None]:
    """HR zone-minutes for `day`, bucketed against `profile.zone_bounds()`.

    Restricts to the single highest-priority HR source first (Decision 4 — so
    overlapping dual-device HR can't double-count), then credits each sample's
    **in-day** minutes (split at the Sofia midnight; round-1 #2) to its zone.
    Interval samples (the seeded form) credit their in-day overlap; instant samples
    (the live Watch form) credit the capped gap to the next instant sample — see
    `_INSTANT_HR_MAX_CREDIT_S`. A day with no in-day HR sample of either form →
    every `z*_min` is `None` (no-data convention).
    """
    # Choose the day's source from the in-day rows, then credit from the full window's
    # rows of that source, so an instant sample just before midnight still finds its
    # next-day successor for the gap computation — see `_zone_minutes_in_range`.
    minutes = _zone_minutes_in_range(
        _hr_window_rows(session, day), *_sofia_day_bounds(day), profile=profile
    )
    if minutes is None:
        return {col: None for col in ZONE_COLUMNS}
    return {f"{z}_min": minutes[z] for z in _ZONE_KEYS}


def _workout_z45_minutes(
    session: Session, w: Workouts, *, profile: Profile
) -> tuple[float, float] | None:
    """One workout's **in-window** `(z4+z5 minutes, credited minutes)`, or `None` when no
    HR sample overlaps its `[start_date, end_date]` window.

    The corroboration signal `hard_day` reads (DECISIONS.md Decisions 3 & 6). Credit is
    strictly per workout: minutes earned elsewhere in the day never contribute, and two
    workouts' windows are never summed. `credited_minutes` is the total across **all five
    zones**, not just z4/z5 — it is what the coverage gate uses to tell a genuinely easy
    session (fully recorded, no hard minutes) from one the watch barely recorded.

    `None` means *the signal is absent*, mirroring `zone_minutes`' all-`None` no-data
    convention; a covered-but-easy window returns `(0.0, credited)`, which is a real
    reading. An undefined window (`end_date is None`, or end at/before start) is absent
    too — there is nothing to credit against.
    """
    if w.end_date is None:
        return None
    lo, hi = parse_ts(w.start_date), parse_ts(w.end_date)
    if hi <= lo:
        return None
    day = to_sofia(lo).date()
    minutes = _zone_minutes_in_range(_hr_window_rows(session, day), lo, hi, profile=profile)
    if minutes is None:
        return None
    return minutes["z4"] + minutes["z5"], sum(minutes.values())


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
# These four types are the *fallback* heuristic, consulted only when a workout carries
# neither corroborating signal (corroborated-hard-day DECISIONS.md Decision 2).
HARD_ACTIVITY_TYPES: frozenset[str] = frozenset(
    {"boxing", "high_intensity_interval_training", "kickboxing", "martial_arts"}
)
LONG_DURATION_MIN: float = 90.0  # minutes; "long" session fallback, BOUNDARY INCLUSIVE (>=)

# Corroboration thresholds (corroborated-hard-day DECISIONS.md Decisions 1, 6, 7). Every
# comparison against them is BOUNDARY INCLUSIVE (>=, or <= for the effort range's top).
HARD_EFFORT_MIN: float = 7.0  # Apple RPE: 7-8 "hard", 9-10 "max"
HARD_EFFORT_MIN_DURATION_MIN: float = 20.0  # a short 7-RPE burst is not a hard *day*
HARD_Z45_MIN: float = 15.0  # in-window z4+z5 minutes that confirm on their own
# The usable Apple RPE range. `sync.py` declares a bare `int | None` into an unconstrained
# `Float` column, so 99 and -3 are storable; outside this range a score is nonsense, not
# evidence, and is treated exactly as NULL (Decision 7).
HARD_EFFORT_VALID_RANGE: tuple[float, float] = (1.0, 10.0)
# Fraction of a workout's duration that must carry credited in-window HR before the zones
# signal counts as *present* (Decision 6). Below it — dead battery, manual log — zones are
# absent, so the typed fallback still protects the session instead of demoting it on three
# warm-up minutes. Promotion by `HARD_Z45_MIN` is deliberately NOT gated on this.
HARD_HR_COVERAGE_MIN_FRAC: float = 0.5
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


# The human-plausible body-weight range (kg) for a usable live weight. The sync
# `HealthRecord.value` is an unconstrained float, so a materialised `body_weight` may be garbage:
# 0/negative/NaN/`±inf`, a finite-but-absurd outlier (e.g. 1e308), or a corrupted sub-physiological
# sample (e.g. 0.1). Both ends break the weekly brief — over the ceiling, `+inf`/overflow makes
# `bmr → tdee → _round_half_up` raise (5xx); under the floor, a tiny weight yields impossible
# macros (protein/fat/carbs round to ~0) and a bogus adherence target (review rounds 1-4).
# Bounding the reader to `MIN <= body_weight <= MAX` rejects the whole class at once (NaN/`±inf`
# comparisons are false in SQLite, so they fail the range too). The bounds are deliberately wide
# sanity guards — the heaviest human ever recorded was ~635 kg and no adult athlete is < 30 kg —
# so a real weight is never excluded.
MIN_PLAUSIBLE_BODY_WEIGHT_KG = 30.0
MAX_PLAUSIBLE_BODY_WEIGHT_KG = 1000.0


def current_body_weight(session: Session, anchor: date) -> float | None:
    """The athlete's **current/live** weight: the latest **plausible** materialised
    `daily_metrics.body_weight` on or before `anchor` (E13·P3).

    The multi-day ("≤ anchor") counterpart to `body_weight(session, day)` — where that reads
    the single day's live weight, this walks back to the most recent day that *has* one, so a
    week whose anchor day has no scale reading still resolves a real weight. Reads the
    **materialised** column (the recompute engine already deduped the day's `body_mass` into it
    — DECISIONS Decision 1), not raw `Records`. `DailyMetrics.date` is TEXT ISO-8601, so a
    lexical `<=` + `ORDER BY date DESC` selects the chronologically latest reading on/before the
    anchor.

    Only a **plausible** weight qualifies — `MIN_PLAUSIBLE_BODY_WEIGHT_KG <= body_weight <=
    MAX_PLAUSIBLE_BODY_WEIGHT_KG` — so a garbage materialised value (0/negative/NaN/`±inf`/absurd
    finite/sub-physiological) is **skipped** and the walk-back continues to the latest valid
    reading, rather than letting it reach the macro engine and either 5xx the brief or emit
    impossible nutrition (review rounds 1-4; see the range constants). Returns `None` when no
    plausible reading exists at/before the anchor (caller falls back to `goal_weight_kg`).
    """
    return session.scalars(
        select(DailyMetrics.body_weight)
        .where(
            DailyMetrics.body_weight >= MIN_PLAUSIBLE_BODY_WEIGHT_KG,
            DailyMetrics.body_weight <= MAX_PLAUSIBLE_BODY_WEIGHT_KG,
            DailyMetrics.date <= anchor.isoformat(),
        )
        .order_by(DailyMetrics.date.desc())
        .limit(1)
    ).first()


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


def is_valid_effort_score(score: float | int | None) -> bool:
    """True when `score` is a usable Apple RPE — finite and inside
    `HARD_EFFORT_VALID_RANGE` (inclusive at both ends).

    The single home of the validity rule (corroborated-hard-day DECISIONS.md Decision 7):
    `hard_day` uses it to decide whether an effort signal is *present*, and
    `workout_upsert` uses the same predicate to decide whether a stored score is
    repairable, so the two can never disagree about what "valid" means.
    """
    if score is None:
        return False
    try:
        value = float(score)
    except (TypeError, ValueError):
        return False
    lo, hi = HARD_EFFORT_VALID_RANGE
    return math.isfinite(value) and lo <= value <= hi


def _workout_effort(w: Workouts) -> float | None:
    """`w`'s effort score when it is trustworthy, else `None` — an invalid score is
    treated **exactly** as `NULL`, not as a low reading (Decision 7)."""
    return float(w.effort_score) if is_valid_effort_score(w.effort_score) else None


def _workout_is_hard(session: Session, w: Workouts, *, profile: Profile) -> bool:
    """Whether one workout makes its day hard — the per-workout half of `hard_day`."""
    duration = _duration_minutes(w)
    if duration >= LONG_DURATION_MIN:
        return True  # the long-session rule is unconditional, never corroboration-gated

    effort = _workout_effort(w)
    zones = _workout_z45_minutes(session, w, profile=profile)

    # Confirmation — either signal is enough, whatever the activity type (Decision 2).
    if (
        effort is not None
        and effort >= HARD_EFFORT_MIN
        and duration >= HARD_EFFORT_MIN_DURATION_MIN
    ):
        return True
    if zones is not None and zones[0] >= HARD_Z45_MIN:
        return True  # NOT coverage-gated: 15 credited hard minutes imply real data

    # Neither confirmed. The type heuristic applies ONLY when both signals are absent —
    # a present-but-unconfirming signal is evidence, and it wins over the label.
    zones_present = (
        zones is not None and duration > 0 and zones[1] >= HARD_HR_COVERAGE_MIN_FRAC * duration
    )
    if effort is None and not zones_present:
        return _canonical_activity_type(w.activity_type) in HARD_ACTIVITY_TYPES
    return False


def hard_day(session: Session, day: date, *, profile: Profile) -> int:
    """Deterministic 0/1 hard-session flag from the day's `workouts`, corroborated against
    the session's actual intensity (corroborated-hard-day DECISIONS.md; **revises**
    archived Decision 3 of `2026-06-04-e6-p1-per-day-recompute`, which trusted
    `activity_type` alone).

    `1` if ANY of the day's workouts is hard. Per workout, in order:

    1. `_duration_minutes(w) >= LONG_DURATION_MIN` (90) — unconditional, ungated.
    2. **Confirmed by either signal**, whatever the activity type: a *valid* effort score
       `>= HARD_EFFORT_MIN` on a session of `>= HARD_EFFORT_MIN_DURATION_MIN`, or in-window
       z4+z5 `>= HARD_Z45_MIN` minutes (`_workout_z45_minutes`).
    3. **Typed fallback** — `activity_type in HARD_ACTIVITY_TYPES` — but only when BOTH
       signals are *absent*, which reproduces the legacy predicate on a no-data workout.

    "Absent" is validity-gated, not merely null-gated: an effort score outside
    `HARD_EFFORT_VALID_RANGE` counts as absent (Decision 7), and the zones signal counts as
    present only with credited in-window HR `>= HARD_HR_COVERAGE_MIN_FRAC` of the duration
    (Decision 6). So a present-but-disproving signal demotes a mislabelled session, while
    bad or missing data leaves the label's protection intact.

    Always a real `0`/`1` — never `None` (a flag, not a measurement).
    """
    lo, hi = _window(day)
    stmt = select(Workouts).where(Workouts.start_date >= lo).where(Workouts.start_date < hi)
    workouts = _drop_superseded_seed(
        session.execute(stmt).scalars().all(), covered=_day_is_sync_covered(session, day)
    )
    for w in workouts:
        if to_sofia(parse_ts(w.start_date)).date() != day:
            continue
        if _workout_is_hard(session, w, profile=profile):
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
        forward = (
            session.execute(select(DailyMetrics.date).where(DailyMetrics.date.between(start, end)))
            .scalars()
            .all()
        )
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
    hrv = (
        session.execute(
            select(DailyMetrics.hrv_sdnn).where(
                DailyMetrics.date.between(start, end), DailyMetrics.hrv_sdnn.is_not(None)
            )
        )
        .scalars()
        .all()
    )
    rhr_vals = (
        session.execute(
            select(DailyMetrics.rhr).where(
                DailyMetrics.date.between(start, end), DailyMetrics.rhr.is_not(None)
            )
        )
        .scalars()
        .all()
    )
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
        "hard_day": hard_day(session, day, profile=profile),
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
