"""E6·P1 `daily_metrics` recompute engine tests.

TASK-001 covers the engine *shape*: the idempotent `ON CONFLICT(date) DO UPDATE`
upsert, the non-clobber of the five later-phase columns, the empty-set no-IO guard,
and the multi-date entry point. Per-metric correctness is TASK-002/003.

`recompute_day` is exercised directly against the migrated temp-`app.db` `session`
fixture (tests/services/conftest.py). `DailyMetricsEngine.__call__` opens its **own**
`SessionLocal()`, so its tests point the lazy runtime engine at a temp `app.db` via
the `engine_db` fixture (APP_DB_PATH + cache clears, like tests/api/routes/test_sync).
"""

from __future__ import annotations

import sqlite3
import statistics
from collections.abc import Iterator
from datetime import date, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.profile import load_profile
from app.core.settings import get_settings
from app.database.engine import SessionLocal, get_engine
from app.database.models import DailyMetrics, Records, Workouts
from app.services import daily_metrics_engine as engine_mod
from app.services.daily_metrics_engine import (
    MIN_BASELINE_SAMPLES,
    PRESERVED_COLUMNS,
    DailyMetricsEngine,
    _workout_z45_minutes,
    active_energy,
    body_weight,
    current_body_weight,
    expand_affected_dates,
    hard_day,
    hrv_baseline,
    hrv_sdnn,
    nutrition_intake,
    recompute_day,
    rhr,
    rhr_baseline,
    sleep_h,
    steps,
    window_readings,
    zone_minutes,
)

PROFILE = load_profile()


def _row(session: Session, day: str) -> dict:
    """The `daily_metrics` row for `day` as a plain column→value dict."""
    mapping = (
        session.execute(text("SELECT * FROM daily_metrics WHERE date = :d"), {"d": day})
        .mappings()
        .one()
    )
    return dict(mapping)


def _count(session: Session, table: str = "daily_metrics") -> int:
    return session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


# ---------------------------------------------------------------------------
# recompute_day — idempotent upsert + non-clobber (uses the conftest `session`).
# ---------------------------------------------------------------------------
def test_recompute_day_writes_single_row_with_computed_at(session: Session) -> None:
    recompute_day(session, date(2026, 6, 1), profile=PROFILE)
    session.commit()
    assert _count(session) == 1
    row = _row(session, "2026-06-01")
    assert row["date"] == "2026-06-01"
    assert row["computed_at"] is not None


def test_recompute_day_computed_at_is_timezone_aware(session: Session) -> None:
    recompute_day(session, date(2026, 6, 1), profile=PROFILE)
    session.commit()
    computed_at = _row(session, "2026-06-01")["computed_at"]
    assert datetime.fromisoformat(computed_at).tzinfo is not None  # now_sofia(), not naive


def test_recompute_day_is_idempotent(session: Session) -> None:
    day = date(2026, 6, 1)
    recompute_day(session, day, profile=PROFILE)
    session.commit()
    first = _row(session, "2026-06-01")

    recompute_day(session, day, profile=PROFILE)
    session.commit()
    second = _row(session, "2026-06-01")

    assert _count(session) == 1  # still one row
    computed = [c for c in first if c != "computed_at"]
    assert {c: first[c] for c in computed} == {c: second[c] for c in computed}  # identical
    assert second["computed_at"] >= first["computed_at"]  # re-written / fresh


def test_recompute_day_fresh_insert_leaves_later_phase_columns_null(session: Session) -> None:
    recompute_day(session, date(2026, 6, 1), profile=PROFILE)
    session.commit()
    row = _row(session, "2026-06-01")
    for col in PRESERVED_COLUMNS:
        assert row[col] is None, f"{col} should be null on a fresh P1 insert"


def test_recompute_day_does_not_clobber_readiness_but_refreshes_baselines(session: Session) -> None:
    # Post-E6·P2 the three 30-day baselines UPDATE on recompute (folded into the set_);
    # only readiness_score/band (E8/E11) survive a recompute (round-1 #4/#5).
    day = date(2026, 6, 1)
    recompute_day(session, day, profile=PROFILE)
    session.commit()
    # E11 writes readiness_score AND band together; pre-set both + a stale baseline.
    session.execute(
        text(
            "UPDATE daily_metrics SET hrv_30d_mean = 42.0, readiness_score = 80, "
            "band = 'GREEN' WHERE date = :d"
        ),
        {"d": "2026-06-01"},
    )
    session.commit()

    recompute_day(session, day, profile=PROFILE)
    session.commit()

    row = _row(session, "2026-06-01")
    # readiness verdict survives (excluded from the set_)...
    assert row["readiness_score"] == 80
    assert row["band"] == "GREEN"
    # ...but the baseline now refreshes from the window (here: single empty day → null).
    assert row["hrv_30d_mean"] is None


# ---------------------------------------------------------------------------
# DailyMetricsEngine.__call__ — entry point over the lazy runtime engine.
# ---------------------------------------------------------------------------
@pytest.fixture
def engine_db(tmp_path, monkeypatch) -> Iterator[str]:
    """Point the lazy runtime engine (`SessionLocal`/`get_engine`) at a migrated temp app.db."""
    db_path = tmp_path / "app.db"
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.attributes["test_db_url"] = f"sqlite:///{db_path}"
    command.upgrade(cfg, "head")
    monkeypatch.setenv("API_TOKEN", "test-api-token-0123456789")
    monkeypatch.setenv("APP_DB_PATH", str(db_path))
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield str(db_path)
    get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()


def test_engine_writes_a_row_for_each_date(engine_db: str) -> None:
    DailyMetricsEngine()({date(2026, 6, 1), date(2026, 6, 2)})
    with sqlite3.connect(engine_db) as raw:
        dates = {r[0] for r in raw.execute("SELECT date FROM daily_metrics").fetchall()}
    assert dates == {"2026-06-01", "2026-06-02"}


def test_engine_empty_set_does_no_db_or_profile_io(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("empty affected set must not open a session or load the profile")

    monkeypatch.setattr(engine_mod, "SessionLocal", boom)
    monkeypatch.setattr(engine_mod, "load_profile", boom)
    assert DailyMetricsEngine()(set()) is None  # returns before any DB/profile access


def test_engine_raising_mid_recompute_does_not_commit(engine_db: str, monkeypatch) -> None:
    # An engine error must leave no half-written daily_metrics (the session is not
    # committed) — the route surfaces the 5xx, the day re-derives next sync.
    def boom_day(*args, **kwargs):
        raise RuntimeError("recompute_day boom")

    monkeypatch.setattr(engine_mod, "recompute_day", boom_day)
    with pytest.raises(RuntimeError):
        DailyMetricsEngine()({date(2026, 6, 1)})
    # A fresh session sees no committed row.
    sess = SessionLocal()
    try:
        assert _count(sess) == 0
    finally:
        sess.close()


def test_engine_module_has_no_http_import() -> None:
    # Pure service: the engine must not reach into FastAPI/HTTP. Scan the actual
    # import statements (the docstring legitimately names FastAPI).
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(engine_mod))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(mod.split(".")[0] in {"fastapi", "starlette"} for mod in imported)


# ---------------------------------------------------------------------------
# TASK-002: activity / recovery metrics (over the conftest `session` fixture).
# Zone bounds (profile.yaml): z1[96,125) z2[125,150) z3[150,167) z4[167,177) z5[177,192].
# ---------------------------------------------------------------------------
def _rec(
    type_: str,
    start: str,
    *,
    end: str | None = None,
    value: float | None = None,
    value_text: str | None = None,
    source: str = "Apple Watch",
    unit: str | None = None,
    origin: str = "sync",
) -> Records:
    return Records(
        type=type_,
        start_date=start,
        end_date=end if end is not None else start,
        value=value,
        value_text=value_text,
        source_name=source,
        unit=unit,
        origin=origin,
    )


def _seed(session: Session, *records: Records) -> None:
    for r in records:
        session.add(r)
    session.commit()


D1 = date(2026, 6, 1)
D2 = date(2026, 6, 2)


def test_sleep_h_sums_asleep_blocks_waking_on_day(session: Session) -> None:
    _seed(
        session,
        # two asleep blocks (core + REM) waking on D1 → 1h + 0.5h = 1.5h
        _rec(
            "sleep_analysis",
            "2026-06-01T01:00:00+03:00",
            end="2026-06-01T02:00:00+03:00",
            value_text="asleepCore",
        ),
        _rec(
            "sleep_analysis",
            "2026-06-01T02:00:00+03:00",
            end="2026-06-01T02:30:00+03:00",
            value_text="asleepREM",
        ),
        # inBed / awake must NOT count
        _rec(
            "sleep_analysis",
            "2026-06-01T00:30:00+03:00",
            end="2026-06-01T01:00:00+03:00",
            value_text="inBed",
        ),
    )
    assert sleep_h(session, D1) == pytest.approx(1.5)
    assert sleep_h(session, D2) is None  # nothing wakes on D2


def test_sleep_h_cross_midnight_anchors_wholly_to_wake_day(session: Session) -> None:
    # 23:30 (D1) → 07:00 (D2) Sofia = 7.5h asleep, all credited to the WAKE day (D2).
    _seed(
        session,
        _rec(
            "sleep_analysis",
            "2026-06-01T23:30:00+03:00",
            end="2026-06-02T07:00:00+03:00",
            value_text="asleepCore",
        ),
    )
    assert sleep_h(session, D2) == pytest.approx(7.5)  # full night on the morning row
    assert sleep_h(session, D1) is None  # nothing on the prior day (not split)


def test_hrv_and_rhr_this_morning(session: Session) -> None:
    _seed(
        session,
        _rec("heart_rate_variability_sdnn", "2026-06-01T06:30:00+03:00", value=48.0),
        _rec("resting_heart_rate", "2026-06-01T06:30:00+03:00", value=54.0),
    )
    assert hrv_sdnn(session, D1) == 48.0
    assert rhr(session, D1) == 54.0
    assert hrv_sdnn(session, D2) is None
    assert rhr(session, D2) is None


def test_steps_source_deduped_watch_over_iphone(session: Session) -> None:
    _seed(
        session,
        _rec("step_count", "2026-06-01T10:00:00+03:00", value=10000.0, source="Apple Watch"),
        _rec("step_count", "2026-06-01T11:00:00+03:00", value=7000.0, source="itsonev-ip15"),
    )
    assert steps(session, D1) == 10000  # Watch only, NOT 17000


def test_steps_falls_back_to_iphone_when_no_watch(session: Session) -> None:
    _seed(
        session,
        _rec("step_count", "2026-06-01T11:00:00+03:00", value=7000.0, source="itsonev-ip15"),
    )
    assert steps(session, D1) == 7000


def test_steps_none_when_no_record_and_zero_from_picked_source(session: Session) -> None:
    assert steps(session, D1) is None
    _seed(session, _rec("step_count", "2026-06-01T11:00:00+03:00", value=0.0, source="Apple Watch"))
    assert steps(session, D1) == 0  # a real zero from the picked source, not None


def test_active_energy_source_deduped_watch_over_workout_app(session: Session) -> None:
    _seed(
        session,
        _rec(
            "active_energy_burned", "2026-06-01T18:00:00+03:00", value=500.0, source="Apple Watch"
        ),
        _rec("active_energy_burned", "2026-06-01T18:00:00+03:00", value=300.0, source="Strava"),
    )
    assert active_energy(session, D1) == 500.0  # Watch only
    assert active_energy(session, D2) is None


def test_zone_minutes_bucketing_boundary_and_full_duration(session: Session) -> None:
    _seed(
        session,
        # full-duration in-day sample: 130 bpm (z2) for 10 min
        _rec(
            "heart_rate", "2026-06-01T10:00:00+03:00", end="2026-06-01T10:10:00+03:00", value=130.0
        ),
        # boundary sample: 127 bpm == z2.low lands in z2 (low <= bpm < high) for 5 min
        _rec(
            "heart_rate", "2026-06-01T10:10:00+03:00", end="2026-06-01T10:15:00+03:00", value=127.0
        ),
        # 100 bpm (z1) for 4 min
        _rec(
            "heart_rate", "2026-06-01T10:15:00+03:00", end="2026-06-01T10:19:00+03:00", value=100.0
        ),
    )
    z = zone_minutes(session, D1, profile=PROFILE)
    assert z["z1_min"] == pytest.approx(4.0)
    assert z["z2_min"] == pytest.approx(15.0)  # 10 + 5 (boundary 125 → z2)
    assert z["z3_min"] == pytest.approx(0.0)


def test_zone_minutes_split_across_sofia_midnight(session: Session) -> None:
    # 23:50 (D1) → 00:10 (D2) at 130 bpm (z2): 10 min each side of the boundary.
    _seed(
        session,
        _rec(
            "heart_rate", "2026-06-01T23:50:00+03:00", end="2026-06-02T00:10:00+03:00", value=130.0
        ),
    )
    assert zone_minutes(session, D1, profile=PROFILE)["z2_min"] == pytest.approx(10.0)
    assert zone_minutes(session, D2, profile=PROFILE)["z2_min"] == pytest.approx(10.0)


def test_zone_minutes_hr_source_deduped(session: Session) -> None:
    # Overlapping Watch (z2) + Garmin (z3) HR: minutes from the priority Watch only.
    _seed(
        session,
        _rec(
            "heart_rate",
            "2026-06-01T10:00:00+03:00",
            end="2026-06-01T10:10:00+03:00",
            value=130.0,
            source="Apple Watch",
        ),
        _rec(
            "heart_rate",
            "2026-06-01T10:00:00+03:00",
            end="2026-06-01T10:10:00+03:00",
            value=160.0,
            source="Garmin Connect",
        ),
    )
    z = zone_minutes(session, D1, profile=PROFILE)
    assert z["z2_min"] == pytest.approx(10.0)  # Watch
    assert z["z3_min"] == pytest.approx(0.0)  # Garmin's 160 bpm dropped — no doubled minutes


def test_zone_minutes_none_when_no_hr_records(session: Session) -> None:
    z = zone_minutes(session, D1, profile=PROFILE)
    assert all(z[c] is None for c in ("z1_min", "z2_min", "z3_min", "z4_min", "z5_min"))


def test_sleep_h_numeric_stage_codes_from_live_exporter(session: Session) -> None:
    """The 2026-07-23 live gap: the iOS exporter sends `HKCategoryValueSleepAnalysis.
    rawValue` as a bare digit, which matched no stage and NULLed sleep for 62 days."""
    _seed(
        session,
        # core (3) 1h + deep (4) 0.5h + rem (5) 0.25h = 1.75h asleep
        _rec(
            "sleep_analysis",
            "2026-06-01T01:00:00+03:00",
            end="2026-06-01T02:00:00+03:00",
            value_text="3",
        ),
        _rec(
            "sleep_analysis",
            "2026-06-01T02:00:00+03:00",
            end="2026-06-01T02:30:00+03:00",
            value_text="4",
        ),
        _rec(
            "sleep_analysis",
            "2026-06-01T02:30:00+03:00",
            end="2026-06-01T02:45:00+03:00",
            value_text="5",
        ),
        # awake (2) and inBed (0) must NOT count
        _rec(
            "sleep_analysis",
            "2026-06-01T02:45:00+03:00",
            end="2026-06-01T03:00:00+03:00",
            value_text="2",
        ),
        _rec(
            "sleep_analysis",
            "2026-06-01T00:30:00+03:00",
            end="2026-06-01T01:00:00+03:00",
            value_text="0",
        ),
    )
    assert sleep_h(session, D1) == pytest.approx(1.75)


def test_zone_minutes_instant_watch_samples_credit_gap_to_next(session: Session) -> None:
    """The 2026-07-23 live gap: every Watch HR sample is a point (`start == end`), so
    interval overlap credited 0s and zones were NULL for 62 days. Instant samples now
    credit the gap to the next sample, capped at 5 min."""
    _seed(
        session,
        # 10:00 at 130 (z2) → next at 10:04 → 4 min credited to z2
        _rec("heart_rate", "2026-06-01T10:00:00+03:00", value=130.0),
        # 10:04 at 155 (z3) → next at 10:24 (20 min away) → capped at 5 min to z3
        _rec("heart_rate", "2026-06-01T10:04:00+03:00", value=155.0),
        # 10:24 at 100 (z1) → last sample of the day → 0 credited
        _rec("heart_rate", "2026-06-01T10:24:00+03:00", value=100.0),
    )
    z = zone_minutes(session, D1, profile=PROFILE)
    assert z["z2_min"] == pytest.approx(4.0)
    assert z["z3_min"] == pytest.approx(5.0)  # capped, not 20
    assert z["z1_min"] == pytest.approx(0.0)  # data present, last-sample credit is 0 — not None


def test_zone_minutes_instant_credit_clipped_at_sofia_midnight(session: Session) -> None:
    # 23:58 (D1) at 130 bpm, next sample 00:30 (D2): credit is capped at 5 min AND
    # clipped to the day end → 2 min on D1; the sample contributes nothing to D2.
    _seed(
        session,
        _rec("heart_rate", "2026-06-01T23:58:00+03:00", value=130.0),
        _rec("heart_rate", "2026-06-02T00:30:00+03:00", value=130.0),
    )
    assert zone_minutes(session, D1, profile=PROFILE)["z2_min"] == pytest.approx(2.0)


def test_zone_minutes_mixed_interval_and_instant_samples(session: Session) -> None:
    # A seeded interval sample and live instant samples on the same day both credit.
    _seed(
        session,
        _rec(
            "heart_rate", "2026-06-01T09:00:00+03:00", end="2026-06-01T09:10:00+03:00", value=130.0
        ),  # interval: 10 min z2
        _rec("heart_rate", "2026-06-01T10:00:00+03:00", value=155.0),  # instant → 3 min z3
        _rec("heart_rate", "2026-06-01T10:03:00+03:00", value=155.0),  # last → 0
    )
    z = zone_minutes(session, D1, profile=PROFILE)
    assert z["z2_min"] == pytest.approx(10.0)
    assert z["z3_min"] == pytest.approx(3.0)


def test_instant_metric_attributed_to_sofia_date(session: Session) -> None:
    # 23:30 UTC on 06-02 → 02:30 Sofia (+03:00) on 06-03 → counts on the Sofia date.
    _seed(
        session, _rec("step_count", "2026-06-02T23:30:00+00:00", value=5000.0, source="Apple Watch")
    )
    assert steps(session, date(2026, 6, 3)) == 5000
    assert steps(session, D2) is None  # not the wire-offset date


def test_expand_affected_dates_pulls_cross_midnight_neighbour(session: Session) -> None:
    _seed(
        session,
        _rec(
            "heart_rate", "2026-06-01T23:50:00+03:00", end="2026-06-02T00:10:00+03:00", value=130.0
        ),
    )
    # Handed only the start day (E5·P3 fans out by start) → engine widens to both days.
    assert expand_affected_dates(session, {D1}) == {D1, D2}


def test_engine_recomputes_both_rows_for_cross_midnight_sample(engine_db: str) -> None:
    seed = SessionLocal()
    try:
        seed.add(
            _rec(
                "heart_rate",
                "2026-06-01T23:50:00+03:00",
                end="2026-06-02T00:10:00+03:00",
                value=130.0,
            )
        )
        seed.commit()
    finally:
        seed.close()
    DailyMetricsEngine()({D1})  # handed only the start day
    with sqlite3.connect(engine_db) as raw:
        dates = {r[0] for r in raw.execute("SELECT date FROM daily_metrics").fetchall()}
    assert dates == {"2026-06-01", "2026-06-02"}  # both neighbour rows refreshed


# ---------------------------------------------------------------------------
# TASK-003: nutrition intake + latest body weight + hard_day flag.
# ---------------------------------------------------------------------------
def _workout(
    activity_type: str,
    start: str,
    *,
    duration: float,
    unit: str = "s",
    origin: str = "sync",
    end: str | None = None,
    effort: float | None = None,
) -> Workouts:
    # `end` defaults to `start` (a zero-length window): the legacy fixtures carry no HR
    # window at all, so they exercise the "zones absent" typed fallback.
    return Workouts(
        activity_type=activity_type,
        start_date=start,
        end_date=start if end is None else end,
        duration=duration,
        duration_unit=unit,
        origin=origin,
        effort_score=effort,
    )


def test_nutrition_intake_dominant_app_not_cross_sum(session: Session) -> None:
    # MacroFactor (higher kcal_in) is dominant; MyFitnessPal's entries are NOT summed in.
    _seed(
        session,
        _rec(
            "dietary_energy_consumed",
            "2026-06-01T12:00:00+03:00",
            value=2000.0,
            source="MacroFactor",
        ),
        _rec("dietary_protein", "2026-06-01T12:00:00+03:00", value=150.0, source="MacroFactor"),
        _rec(
            "dietary_carbohydrates", "2026-06-01T12:00:00+03:00", value=220.0, source="MacroFactor"
        ),
        # a second app logged the same day (lower kcal) — must be ignored entirely
        _rec(
            "dietary_energy_consumed",
            "2026-06-01T13:00:00+03:00",
            value=900.0,
            source="MyFitnessPal",
        ),
        _rec("dietary_protein", "2026-06-01T13:00:00+03:00", value=60.0, source="MyFitnessPal"),
    )
    n = nutrition_intake(session, D1)
    assert n["kcal_in"] == 2000.0  # dominant only, NOT 2900
    assert n["protein_in_g"] == 150.0  # NOT 210
    assert n["carbs_in_g"] == 220.0
    assert n["fat_in_g"] is None  # no dietary_fat_total record in the dominant source
    assert n["fiber_in_g"] is None
    assert n["sodium_in_mg"] is None
    assert n["water_in_l"] is None


def test_nutrition_intake_single_app_unchanged(session: Session) -> None:
    _seed(
        session,
        _rec("dietary_energy_consumed", "2026-06-01T12:00:00+03:00", value=1800.0, source="YAZIO"),
        _rec("dietary_fiber", "2026-06-01T12:00:00+03:00", value=30.0, source="YAZIO"),
    )
    n = nutrition_intake(session, D1)
    assert n["kcal_in"] == 1800.0
    assert n["fiber_in_g"] == 30.0
    assert nutrition_intake(session, D2)["kcal_in"] is None  # no dietary records


def test_body_weight_latest_by_instant_not_lexical(session: Session) -> None:
    # Three weigh-ins whose LEXICAL order differs from CHRONOLOGICAL order (mixed offsets):
    #   09:00+03:00 = 06:00Z (77.0) | 08:30+02:00 = 06:30Z latest (80.0) | 07:00+03:00 = 04:00Z (76.0)
    # Lexical max of start_date is the "09:00+03:00" string (77.0) — the WRONG answer.
    _seed(
        session,
        _rec("body_mass", "2026-06-01T09:00:00+03:00", value=77.0),
        _rec("body_mass", "2026-06-01T08:30:00+02:00", value=80.0),
        _rec("body_mass", "2026-06-01T07:00:00+03:00", value=76.0),
    )
    assert body_weight(session, D1) == 80.0  # latest INSTANT, not first/avg/raw-text-last
    assert body_weight(session, D2) is None


# ---------------------------------------------------------------------------
# current_body_weight — the multi-day "latest materialised body_weight <= anchor" reader.
# ---------------------------------------------------------------------------
def _seed_weight(session: Session, day: date, weight: float | None) -> None:
    session.add(DailyMetrics(date=day.isoformat(), body_weight=weight))


def test_current_body_weight_latest_on_or_before_anchor(session: Session) -> None:
    anchor = date(2026, 6, 10)
    _seed_weight(session, anchor - timedelta(days=3), 80.0)
    _seed_weight(session, anchor - timedelta(days=1), 79.5)
    _seed_weight(session, anchor, 79.0)
    session.commit()
    assert current_body_weight(session, anchor) == 79.0  # the anchor-day reading


def test_current_body_weight_walks_back_when_anchor_missing(session: Session) -> None:
    anchor = date(2026, 6, 10)
    _seed_weight(session, anchor - timedelta(days=2), 81.5)
    _seed_weight(session, anchor - timedelta(days=1), None)  # row present, no reading
    _seed_weight(session, anchor, None)  # anchor day has no scale reading
    session.commit()
    assert current_body_weight(session, anchor) == 81.5  # walks back to the latest non-null


def test_current_body_weight_none_when_no_history(session: Session) -> None:
    anchor = date(2026, 6, 10)
    _seed_weight(session, anchor - timedelta(days=1), None)
    _seed_weight(session, anchor, None)
    session.commit()
    assert current_body_weight(session, anchor) is None


def test_current_body_weight_ignores_future_reading(session: Session) -> None:
    anchor = date(2026, 6, 10)
    _seed_weight(session, anchor - timedelta(days=1), 80.0)
    _seed_weight(session, anchor + timedelta(days=1), 78.0)  # after the anchor → ignored
    session.commit()
    assert current_body_weight(session, anchor) == 80.0


def test_current_body_weight_skips_non_positive_garbage(session: Session) -> None:
    """A materialised 0/negative body_weight is garbage (bad HealthKit body_mass), not a usable
    weight — it is skipped and the walk-back finds the latest valid positive reading, so a bad
    metric never reaches the macro engine's positive-weight guard (review)."""
    anchor = date(2026, 6, 10)
    _seed_weight(session, anchor - timedelta(days=2), 80.0)
    _seed_weight(session, anchor - timedelta(days=1), -5.0)  # garbage → skipped
    _seed_weight(session, anchor, 0.0)  # garbage → skipped
    session.commit()
    assert current_body_weight(session, anchor) == 80.0  # walks back to the latest positive

    # An anchor whose window has ONLY non-positive readings (before the 80.0 above) → None,
    # so the caller falls back to goal_weight_kg.
    bad_only_anchor = date(2026, 6, 5)  # precedes the 80.0 reading on 2026-06-08
    _seed_weight(session, date(2026, 6, 4), 0.0)
    _seed_weight(session, date(2026, 6, 5), -1.0)
    session.commit()
    assert current_body_weight(session, bad_only_anchor) is None


def test_current_body_weight_skips_implausible_weights(session: Session) -> None:
    """A +inf or finite-but-absurd materialised body_weight (the sync value is an unconstrained
    float) would 5xx the brief — `+inf` reaches `_round_half_up` → OverflowError, and a finite
    outlier like 1e308 overflows bmr→tdee to inf → OverflowError. The reader's plausible-range
    bound (`0 < w <= MAX_PLAUSIBLE_BODY_WEIGHT_KG`) skips both and walks back to the latest valid
    weight (review #1 rounds 2-3)."""
    anchor = date(2026, 6, 10)
    _seed_weight(session, anchor - timedelta(days=2), 79.0)
    _seed_weight(session, anchor - timedelta(days=1), float("inf"))  # non-finite → skipped
    _seed_weight(session, anchor, 1e308)  # finite but absurd (overflows the macro chain) → skipped
    session.commit()
    assert current_body_weight(session, anchor) == 79.0


def test_current_body_weight_skips_sub_physiological(session: Session) -> None:
    """A corrupted sub-physiological positive weight (e.g. 0.1 kg) is below any real adult
    athlete and would emit impossible weekly nutrition (protein/fat/carbs round to ~0). The
    reader's lower bound skips it and walks back to the latest plausible weight (review #1
    round-4)."""
    anchor = date(2026, 6, 10)
    _seed_weight(session, anchor - timedelta(days=1), 78.5)
    _seed_weight(session, anchor, 0.1)  # sub-physiological garbage → skipped
    session.commit()
    assert current_body_weight(session, anchor) == 78.5


@pytest.mark.parametrize(
    "activity", ["boxing", "high_intensity_interval_training", "kickboxing", "martial_arts"]
)
def test_hard_day_per_hard_activity_type(session: Session, activity: str) -> None:
    _seed(session, _workout(activity, "2026-06-01T18:00:00+03:00", duration=1800.0, unit="s"))
    assert hard_day(session, D1, profile=PROFILE) == 1


def test_hard_day_long_duration_threshold_inclusive(session: Session) -> None:
    # 89 min → 0, 90 min → 1 (inclusive), 91 min → 1; an easy short session → 0.
    _seed(session, _workout("running", "2026-06-01T18:00:00+03:00", duration=89.0, unit="min"))
    assert hard_day(session, D1, profile=PROFILE) == 0

    # A distinct day per case so the workouts don't accumulate ambiguously.
    _seed(session, _workout("running", "2026-06-02T18:00:00+03:00", duration=90.0, unit="min"))
    assert hard_day(session, D2, profile=PROFILE) == 1
    _seed(session, _workout("cycling", "2026-06-03T18:00:00+03:00", duration=91.0, unit="min"))
    assert hard_day(session, date(2026, 6, 3), profile=PROFILE) == 1


def test_hard_day_seconds_unit_normalized(session: Session) -> None:
    # 5400 s == 90 min → hard (pins the duration_unit normalization).
    _seed(session, _workout("rowing", "2026-06-01T18:00:00+03:00", duration=5400.0, unit="s"))
    assert hard_day(session, D1, profile=PROFILE) == 1


def test_hard_day_easy_only_and_empty_day_are_zero(session: Session) -> None:
    assert hard_day(session, D1, profile=PROFILE) == 0  # empty day
    _seed(session, _workout("walking", "2026-06-01T18:00:00+03:00", duration=1200.0, unit="s"))
    assert hard_day(session, D1, profile=PROFILE) == 0  # 20 min easy walk


def test_full_p1_row_matches_source_with_baselines_null(session: Session) -> None:
    # The integrating assertion (PLAN Acceptance #1): every P1 column reflects the
    # source, with the 30-day baselines + readiness null.
    _seed(
        session,
        _rec(
            "sleep_analysis",
            "2026-05-31T23:30:00+03:00",
            end="2026-06-01T07:00:00+03:00",
            value_text="asleepCore",
        ),
        _rec("heart_rate_variability_sdnn", "2026-06-01T06:30:00+03:00", value=48.0),
        _rec("resting_heart_rate", "2026-06-01T06:30:00+03:00", value=54.0),
        _rec("step_count", "2026-06-01T10:00:00+03:00", value=9000.0, source="Apple Watch"),
        _rec(
            "active_energy_burned", "2026-06-01T10:00:00+03:00", value=500.0, source="Apple Watch"
        ),
        _rec(
            "heart_rate", "2026-06-01T10:00:00+03:00", end="2026-06-01T10:10:00+03:00", value=130.0
        ),
        _rec("body_mass", "2026-06-01T07:00:00+03:00", value=78.4),
        _rec(
            "dietary_energy_consumed",
            "2026-06-01T12:00:00+03:00",
            value=2200.0,
            source="MacroFactor",
        ),
    )
    _seed(session, _workout("boxing", "2026-06-01T18:00:00+03:00", duration=2700.0, unit="s"))
    recompute_day(session, D1, profile=PROFILE)
    session.commit()
    row = _row(session, "2026-06-01")

    assert row["sleep_h"] == pytest.approx(7.5)
    assert row["hrv_sdnn"] == 48.0
    assert row["rhr"] == 54.0
    assert row["steps"] == 9000
    assert row["active_energy"] == 500.0
    assert row["z2_min"] == pytest.approx(10.0)
    assert row["body_weight"] == 78.4
    assert row["kcal_in"] == 2200.0
    assert row["hard_day"] == 1
    # 30-day baselines + readiness stay null this phase.
    for col in PRESERVED_COLUMNS:
        assert row[col] is None


def test_nutrition_and_body_mass_attributed_to_sofia_date(session: Session) -> None:
    # 23:30 UTC on 06-02 → 02:30 Sofia (+03:00) on 06-03 → both land on the Sofia date.
    d3 = date(2026, 6, 3)
    _seed(
        session,
        _rec("body_mass", "2026-06-02T23:30:00+00:00", value=79.1, source="Apple Watch"),
        _rec(
            "dietary_energy_consumed",
            "2026-06-02T23:30:00+00:00",
            value=2100.0,
            source="MacroFactor",
        ),
    )
    assert body_weight(session, d3) == 79.1
    assert nutrition_intake(session, d3)["kcal_in"] == 2100.0
    assert body_weight(session, D2) is None  # not the wire-offset date
    assert nutrition_intake(session, D2)["kcal_in"] is None


# ---------------------------------------------------------------------------
# Integration: seed through E5·P2's real upsert_records write path (which stores
# r.type.value snake_case) and recompute — proves the engine matches records.type
# on the stored snake_case RecordType value, not the HK…Identifier (round-3 #2).
# ---------------------------------------------------------------------------
def test_recompute_matches_stored_type_form_via_upsert_records(session: Session) -> None:
    from app.api.schemas.sync import HealthRecord, RecordType
    from app.services.record_upsert import upsert_records

    records = [
        HealthRecord(
            uuid="s1",
            type=RecordType.STEP_COUNT,
            start=datetime.fromisoformat("2026-06-01T10:00:00+03:00"),
            end=datetime.fromisoformat("2026-06-01T10:00:00+03:00"),
            value=8000.0,
            unit="count",
            source="Apple Watch",
        ),
        HealthRecord(
            uuid="h1",
            type=RecordType.HEART_RATE_VARIABILITY_SDNN,
            start=datetime.fromisoformat("2026-06-01T06:30:00+03:00"),
            end=datetime.fromisoformat("2026-06-01T06:30:00+03:00"),
            value=46.0,
            unit="ms",
            source="Apple Watch",
        ),
        HealthRecord(
            uuid="k1",
            type=RecordType.DIETARY_ENERGY_CONSUMED,
            start=datetime.fromisoformat("2026-06-01T12:00:00+03:00"),
            end=datetime.fromisoformat("2026-06-01T12:00:00+03:00"),
            value=2100.0,
            unit="kcal",
            source="MacroFactor",
        ),
    ]
    upsert_records(session, records)
    session.commit()

    recompute_day(session, D1, profile=PROFILE)
    session.commit()
    row = _row(session, "2026-06-01")
    # Non-null only if the engine matched the stored snake_case types.
    assert row["steps"] == 8000
    assert row["hrv_sdnn"] == 46.0
    assert row["kcal_in"] == 2100.0


# ---------------------------------------------------------------------------
# Review round-1 #1/#2: the engine must read the SEEDED HK-identifier stored form
# (build_db/seed_app_db copy Apple-Health types verbatim), not only the snake_case
# form that /sync stores — else the whole 90-day seed history recomputes to null.
# ---------------------------------------------------------------------------
def test_recompute_reads_seeded_hk_identifier_records(session: Session) -> None:
    # A seed-only day (origin='seed', HK-identifier stored form) — no sync coverage, so
    # the seed rows are read (not superseded).
    _seed(
        session,
        _rec(
            "HKCategoryTypeIdentifierSleepAnalysis",
            "2026-05-31T23:30:00+03:00",
            end="2026-06-01T07:00:00+03:00",
            value_text="HKCategoryValueSleepAnalysisAsleepCore",
            origin="seed",
        ),
        _rec(
            "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
            "2026-06-01T06:30:00+03:00",
            value=48.0,
            origin="seed",
        ),
        _rec(
            "HKQuantityTypeIdentifierRestingHeartRate",
            "2026-06-01T06:30:00+03:00",
            value=54.0,
            origin="seed",
        ),
        _rec(
            "HKQuantityTypeIdentifierStepCount",
            "2026-06-01T10:00:00+03:00",
            value=9000.0,
            source="Apple Watch",
            origin="seed",
        ),
        _rec(
            "HKQuantityTypeIdentifierActiveEnergyBurned",
            "2026-06-01T10:00:00+03:00",
            value=500.0,
            source="Apple Watch",
            origin="seed",
        ),
        _rec(
            "HKQuantityTypeIdentifierHeartRate",
            "2026-06-01T10:00:00+03:00",
            end="2026-06-01T10:10:00+03:00",
            value=130.0,
            origin="seed",
        ),
        _rec(
            "HKQuantityTypeIdentifierBodyMass",
            "2026-06-01T07:00:00+03:00",
            value=78.4,
            origin="seed",
        ),
        _rec(
            "HKQuantityTypeIdentifierDietaryEnergyConsumed",
            "2026-06-01T12:00:00+03:00",
            value=2200.0,
            source="MacroFactor",
            origin="seed",
        ),
        _rec(
            "HKQuantityTypeIdentifierDietaryProtein",
            "2026-06-01T12:00:00+03:00",
            value=160.0,
            source="MacroFactor",
            origin="seed",
        ),
    )
    recompute_day(session, D1, profile=PROFILE)
    session.commit()
    row = _row(session, "2026-06-01")
    assert row["sleep_h"] == pytest.approx(7.5)  # seeded HKCategoryValue sleep stage read
    assert row["hrv_sdnn"] == 48.0
    assert row["rhr"] == 54.0
    assert row["steps"] == 9000
    assert row["active_energy"] == 500.0
    assert row["z2_min"] == pytest.approx(10.0)
    assert row["body_weight"] == 78.4
    assert row["kcal_in"] == 2200.0
    assert row["protein_in_g"] == 160.0


def test_nutrition_dominant_app_across_seeded_and_live_type_forms(session: Session) -> None:
    # The dominant-app pick + per-type sum must canonicalize HK vs snake forms together.
    _seed(
        session,
        _rec(
            "HKQuantityTypeIdentifierDietaryEnergyConsumed",
            "2026-06-01T12:00:00+03:00",
            value=1200.0,
            source="MacroFactor",
        ),
        _rec(
            "dietary_energy_consumed",
            "2026-06-01T19:00:00+03:00",
            value=900.0,
            source="MacroFactor",
        ),
    )
    # Both rows are the same canonical type + source → summed to one app's kcal.
    assert nutrition_intake(session, D1)["kcal_in"] == 2100.0


@pytest.mark.parametrize(
    "hk_activity",
    [
        "HKWorkoutActivityTypeBoxing",
        "HKWorkoutActivityTypeHighIntensityIntervalTraining",
        "HKWorkoutActivityTypeKickboxing",
        "HKWorkoutActivityTypeMartialArts",
    ],
)
def test_hard_day_matches_seeded_hk_workout_activity_types(
    session: Session, hk_activity: str
) -> None:
    # A sub-90-min seeded hard session (HK activity form) must read hard_day=1.
    _seed(session, _workout(hk_activity, "2026-06-01T18:00:00+03:00", duration=1800.0, unit="s"))
    assert hard_day(session, D1, profile=PROFILE) == 1


# ---------------------------------------------------------------------------
# Review round-2 #1: seed/live overlap must NOT double-count. A Sofia day with ≥1
# origin='sync' row is "fully covered" — the engine drops that day's origin='seed'
# rows at read time (mirrors reconcile_seed.py), so the recompute equals the
# post-reconcile state even before the offline reconcile runs.
# ---------------------------------------------------------------------------
def test_sync_covered_day_supersedes_seed_rows_no_double_count(session: Session) -> None:
    _seed(
        session,
        # seeded estimate for D1 (HK form) — same source as the live row below
        _rec(
            "HKQuantityTypeIdentifierStepCount",
            "2026-06-01T09:00:00+03:00",
            value=9000.0,
            source="Apple Watch",
            origin="seed",
        ),
        _rec(
            "HKQuantityTypeIdentifierActiveEnergyBurned",
            "2026-06-01T09:00:00+03:00",
            value=400.0,
            source="Apple Watch",
            origin="seed",
        ),
        # live /sync for the same day — authoritative for the WHOLE day
        _rec(
            "step_count",
            "2026-06-01T18:00:00+03:00",
            value=10000.0,
            source="Apple Watch",
            origin="sync",
        ),
        _rec(
            "active_energy_burned",
            "2026-06-01T18:00:00+03:00",
            value=550.0,
            source="Apple Watch",
            origin="sync",
        ),
    )
    assert steps(session, D1) == 10000  # sync only — NOT 19000
    assert active_energy(session, D1) == 550.0  # sync only — NOT 950


def test_sync_covered_day_drops_seed_metric_even_when_sync_lacks_it(session: Session) -> None:
    # reconcile_seed drops ALL seed rows on a covered day, so a seed-only metric on a
    # day the live sync covers is gone — the engine matches that post-reconcile state.
    _seed(
        session,
        _rec(
            "step_count",
            "2026-06-01T18:00:00+03:00",
            value=10000.0,
            source="Apple Watch",
            origin="sync",
        ),  # makes D1 "covered"
        _rec(
            "HKQuantityTypeIdentifierBodyMass",
            "2026-06-01T07:00:00+03:00",
            value=78.4,
            origin="seed",
        ),  # seed-only metric on a covered day → superseded
    )
    assert body_weight(session, D1) is None  # seed body_mass dropped on the covered day


def test_uncovered_seed_day_keeps_seed_rows(session: Session) -> None:
    # D1 has only seed rows (no sync) → not covered → seed rows are read.
    _seed(
        session,
        _rec(
            "HKQuantityTypeIdentifierStepCount",
            "2026-06-01T09:00:00+03:00",
            value=9000.0,
            source="Apple Watch",
            origin="seed",
        ),
    )
    assert steps(session, D1) == 9000  # kept — a partial/uncovered day keeps its seed


def test_hard_day_seed_workout_superseded_on_sync_covered_day(session: Session) -> None:
    # A live sync row covers D1, so a seed boxing workout on D1 is superseded.
    _seed(session, _rec("step_count", "2026-06-01T18:00:00+03:00", value=8000.0, origin="sync"))
    session.add(
        _workout(
            "HKWorkoutActivityTypeBoxing",
            "2026-06-01T19:00:00+03:00",
            duration=1800.0,
            unit="s",
            origin="seed",
        )
    )
    session.commit()
    assert hard_day(session, D1, profile=PROFILE) == 0  # seed boxing dropped on the covered day


# ---------------------------------------------------------------------------
# Review round-3 #1: a cross-midnight live sync interval must supersede seed rows on
# the NEIGHBOUR day it reaches too — coverage is contribution-day aware (HR overlap,
# sleep wake), not just the sync row's own start day.
# ---------------------------------------------------------------------------
def test_cross_midnight_sync_hr_supersedes_seed_on_neighbour_day(session: Session) -> None:
    _seed(
        session,
        # live HR spanning D1->D2 (start-day D1, but contributes minutes to D2 too)
        _rec(
            "heart_rate",
            "2026-06-01T23:50:00+03:00",
            end="2026-06-02T00:10:00+03:00",
            value=130.0,
            source="Apple Watch",
            origin="sync",
        ),
        # seeded HR fully within D2, same source — would double-count D2 without the fix
        _rec(
            "HKQuantityTypeIdentifierHeartRate",
            "2026-06-02T02:00:00+03:00",
            end="2026-06-02T02:10:00+03:00",
            value=130.0,
            source="Apple Watch",
            origin="seed",
        ),
    )
    # D2 is covered by the cross-midnight sync row → the D2 seed HR is superseded.
    assert zone_minutes(session, D2, profile=PROFILE)["z2_min"] == pytest.approx(10.0)  # not 20.0


def test_cross_midnight_sync_sleep_supersedes_seed_on_wake_day(session: Session) -> None:
    _seed(
        session,
        # live sleep waking on D2 (sync, 7.5h)
        _rec(
            "sleep_analysis",
            "2026-06-01T23:30:00+03:00",
            end="2026-06-02T07:00:00+03:00",
            value_text="asleepCore",
            origin="sync",
        ),
        # seeded sleep also waking on D2 (HK form) — would double sleep_h without the fix
        _rec(
            "HKCategoryTypeIdentifierSleepAnalysis",
            "2026-06-01T23:00:00+03:00",
            end="2026-06-02T06:00:00+03:00",
            value_text="HKCategoryValueSleepAnalysisAsleepCore",
            origin="seed",
        ),
    )
    # D2 (wake day) is covered by the sync sleep → the seed sleep is superseded.
    assert sleep_h(session, D2) == pytest.approx(7.5)  # live only, not 14.5


# ---------------------------------------------------------------------------
# Review round-4 #1: the supersede is TARGET-DAY specific — a sync interval that only
# reaches a neighbour day must not erase legitimate seed data on a day it doesn't cover;
# and HR overlap is half-open so a sample ending exactly at midnight doesn't cover the
# next day.
# ---------------------------------------------------------------------------
def test_uncovered_neighbour_day_keeps_cross_midnight_seed_hr(session: Session) -> None:
    _seed(
        session,
        # seed HR spanning D1->D2 (contributes 10 min to each), origin=seed
        _rec(
            "heart_rate",
            "2026-06-01T23:50:00+03:00",
            end="2026-06-02T00:10:00+03:00",
            value=130.0,
            source="Apple Watch",
            origin="seed",
        ),
        # live sync covers ONLY D1 (an instant step), NOT D2
        _rec("step_count", "2026-06-01T12:00:00+03:00", value=8000.0, origin="sync"),
    )
    # D2 is NOT covered → the seed HR's D2 minutes are legitimate and kept (not erased).
    assert zone_minutes(session, D2, profile=PROFILE)["z2_min"] == pytest.approx(10.0)
    # D1 IS covered (the sync step) → its seed HR is superseded; no sync HR → None.
    assert zone_minutes(session, D1, profile=PROFILE)["z2_min"] is None


def test_sync_hr_ending_exactly_at_midnight_does_not_cover_next_day(session: Session) -> None:
    _seed(
        session,
        # sync HR ending exactly at D2 00:00 — half-open, so it contributes to D1 only
        _rec(
            "heart_rate",
            "2026-06-01T23:50:00+03:00",
            end="2026-06-02T00:00:00+03:00",
            value=130.0,
            source="Apple Watch",
            origin="sync",
        ),
        # seed HR on D2 — must NOT be superseded (D2 is uncovered)
        _rec(
            "heart_rate",
            "2026-06-02T08:00:00+03:00",
            end="2026-06-02T08:10:00+03:00",
            value=130.0,
            source="Apple Watch",
            origin="seed",
        ),
    )
    assert zone_minutes(session, D2, profile=PROFILE)["z2_min"] == pytest.approx(10.0)  # seed kept


# ===========================================================================
# E6·P2 — rolling 30-day HRV/RHR baselines.
# ===========================================================================
def _dm(
    session: Session, day: str, *, hrv: float | None = None, rhr_v: float | None = None
) -> None:
    """Seed a minimal `daily_metrics` row (date PK + hrv_sdnn/rhr; rest null)."""
    session.add(DailyMetrics(date=day, hrv_sdnn=hrv, rhr=rhr_v))


def test_window_readings_boundary_inclusive_of_d(session: Session) -> None:
    # D = 2026-06-30; window is [2026-06-01, 2026-06-30] (30 calendar days incl. D).
    _dm(session, "2026-05-31", hrv=40.0, rhr_v=50.0)  # D-30 → OUT
    _dm(session, "2026-06-01", hrv=41.0, rhr_v=51.0)  # D-29 → IN
    _dm(session, "2026-06-15", hrv=45.0, rhr_v=55.0)  # mid → IN
    _dm(session, "2026-06-30", hrv=49.0, rhr_v=59.0)  # D → IN
    _dm(session, "2026-07-01", hrv=99.0, rhr_v=99.0)  # D+1 → OUT
    session.commit()
    hrv_vals, rhr_vals = window_readings(session, date(2026, 6, 30))
    assert sorted(hrv_vals) == [41.0, 45.0, 49.0]  # D-29, mid, D — not D-30 or D+1
    assert sorted(rhr_vals) == [51.0, 55.0, 59.0]


def test_window_readings_filters_nulls_independently(session: Session) -> None:
    _dm(session, "2026-06-28", hrv=42.0, rhr_v=None)  # HRV only
    _dm(session, "2026-06-29", hrv=None, rhr_v=52.0)  # RHR only
    _dm(session, "2026-06-30", hrv=44.0, rhr_v=54.0)  # both
    session.commit()
    hrv_vals, rhr_vals = window_readings(session, date(2026, 6, 30))
    assert sorted(hrv_vals) == [42.0, 44.0]  # the null-hrv day excluded from HRV
    assert sorted(rhr_vals) == [52.0, 54.0]  # the null-rhr day excluded from RHR


def test_hrv_baseline_population_sd_above_threshold() -> None:
    values = [40.0, 42.0, 44.0, 46.0, 48.0, 50.0, 52.0, 54.0, 56.0, 58.0]  # exactly 10
    assert len(values) == MIN_BASELINE_SAMPLES
    mean, sd = hrv_baseline(values)
    assert mean == pytest.approx(statistics.fmean(values))
    assert sd == pytest.approx(statistics.pstdev(values))  # population (÷N)
    assert sd != pytest.approx(statistics.stdev(values))  # NOT sample (÷N-1)


def test_hrv_baseline_below_threshold_is_none_none() -> None:
    values = [40.0] * (MIN_BASELINE_SAMPLES - 1)  # one short
    assert hrv_baseline(values) == (None, None)  # mean and SD both null, gated together


# ---------------------------------------------------------------------------
# E6·P2 TASK-002 — RHR mean + baselines folded into recompute_day + cascade.
# ---------------------------------------------------------------------------
def test_rhr_baseline_mean_and_no_sd() -> None:
    vals = [50.0 + i for i in range(MIN_BASELINE_SAMPLES)]
    assert rhr_baseline(vals) == pytest.approx(statistics.fmean(vals))
    assert rhr_baseline([50.0] * (MIN_BASELINE_SAMPLES - 1)) is None  # below threshold → None


def _seed_prior_dm(session: Session, d: date, n: int, *, hrv=None, rhr_v=None) -> None:
    """Seed `n` materialized daily_metrics rows ending at d-1 (the days before d)."""
    for i in range(n):
        day = (d - timedelta(days=n - i)).isoformat()
        h = hrv[i] if isinstance(hrv, list) else hrv
        r = rhr_v[i] if isinstance(rhr_v, list) else rhr_v
        _dm(session, day, hrv=h, rhr_v=r)
    session.commit()


def test_recompute_writes_three_baselines_over_full_window(session: Session) -> None:
    d = date(2026, 6, 30)
    hrv_seed = [40.0 + i for i in range(29)]
    rhr_seed = [50.0 + (i % 5) for i in range(29)]
    _seed_prior_dm(session, d, 29, hrv=hrv_seed, rhr_v=rhr_seed)  # [D-29 .. D-1]
    _seed(  # D's own source HRV/RHR
        session,
        _rec("heart_rate_variability_sdnn", "2026-06-30T06:30:00+03:00", value=70.0),
        _rec("resting_heart_rate", "2026-06-30T06:30:00+03:00", value=56.0),
    )
    recompute_day(session, d, profile=PROFILE)
    session.commit()
    row = _row(session, "2026-06-30")
    all_hrv = hrv_seed + [70.0]  # D's reading included
    all_rhr = rhr_seed + [56.0]
    assert row["hrv_30d_mean"] == pytest.approx(statistics.fmean(all_hrv))
    assert row["hrv_30d_sd"] == pytest.approx(statistics.pstdev(all_hrv))
    assert row["rhr_30d_mean"] == pytest.approx(statistics.fmean(all_rhr))


def test_window_includes_ds_own_reading_counted_once(session: Session) -> None:
    d = date(2026, 6, 30)
    _seed_prior_dm(session, d, MIN_BASELINE_SAMPLES - 1, hrv=50.0, rhr_v=55.0)  # 9 prior
    _seed(
        session,
        _rec("heart_rate_variability_sdnn", "2026-06-30T06:30:00+03:00", value=50.0),
        _rec("resting_heart_rate", "2026-06-30T06:30:00+03:00", value=55.0),
    )
    recompute_day(session, d, profile=PROFILE)  # 9 prior + D = 10 = threshold → SET
    session.commit()
    assert _row(session, "2026-06-30")["hrv_30d_mean"] == pytest.approx(50.0)
    # Re-run: D counted once (its row updated, not duplicated) → still set, one row for D.
    recompute_day(session, d, profile=PROFILE)
    session.commit()
    assert _row(session, "2026-06-30")["hrv_30d_mean"] == pytest.approx(50.0)
    assert _count(session) == MIN_BASELINE_SAMPLES  # 9 prior + D, no extra


def test_sparse_window_nulls_baseline_per_metric_independently(session: Session) -> None:
    d = date(2026, 6, 30)
    # 10 RHR readings (dense) but only 8 HRV (sparse) in the window; D adds neither.
    for i in range(10):
        day = (d - timedelta(days=10 - i)).isoformat()
        _dm(session, day, hrv=(50.0 if i < 8 else None), rhr_v=55.0)
    session.commit()
    recompute_day(session, d, profile=PROFILE)  # D has no source records → adds nothing
    session.commit()
    row = _row(session, "2026-06-30")
    assert row["hrv_30d_mean"] is None  # 8 < 10
    assert row["hrv_30d_sd"] is None
    assert row["rhr_30d_mean"] == pytest.approx(55.0)  # 10 >= 10 → set (independent)


def test_null_readings_skipped_not_zeroed(session: Session) -> None:
    d = date(2026, 6, 30)
    vals = [60.0] * 10 + [None] * 2  # 10 non-null + 2 null in the window
    for i, v in enumerate(vals):
        _dm(session, (d - timedelta(days=len(vals) - i)).isoformat(), hrv=v)
    session.commit()
    recompute_day(session, d, profile=PROFILE)
    session.commit()
    row = _row(session, "2026-06-30")
    assert row["hrv_30d_mean"] == pytest.approx(60.0)  # mean over 10 non-null, NOT zero-padded
    assert row["hrv_30d_sd"] == pytest.approx(0.0)  # all 60 → 0 spread, not inflated by zeros


def test_baseline_recompute_is_idempotent(session: Session) -> None:
    d = date(2026, 6, 30)
    _seed_prior_dm(session, d, 15, hrv=[50.0 + i * 0.5 for i in range(15)], rhr_v=55.0)
    recompute_day(session, d, profile=PROFILE)
    session.commit()
    first = _row(session, "2026-06-30")
    recompute_day(session, d, profile=PROFILE)
    session.commit()
    second = _row(session, "2026-06-30")
    assert first["hrv_30d_mean"] == second["hrv_30d_mean"]
    assert first["hrv_30d_sd"] == second["hrv_30d_sd"]
    assert first["rhr_30d_mean"] == second["rhr_30d_mean"]
    assert second["computed_at"] >= first["computed_at"]
    assert _count(session) == 16  # 15 prior + D, no duplicate


def test_forward_window_cascade_via_source_records(engine_db: str) -> None:
    # Build a dense materialized series over SEEDED SOURCE records, correct D's HRV at the
    # SOURCE record, and assert D + the forward rows [D+1, D+29] refresh while D+30 (whose
    # window can't contain D) is unchanged — the cascade fires for every recomputed day.
    d = date(2026, 6, 30)
    all_days = {d + timedelta(days=off) for off in range(-29, 31)}  # D-29 .. D+30
    seed = SessionLocal()
    try:
        for day in all_days:
            seed.add(
                _rec(
                    "heart_rate_variability_sdnn",
                    f"{day.isoformat()}T06:30:00+03:00",
                    value=50.0,
                    origin="sync",
                )
            )
        seed.commit()
    finally:
        seed.close()
    DailyMetricsEngine()(all_days)  # materialize the whole series (mean 50.0 where dense)

    def mean_of(day: date) -> float:
        s = SessionLocal()
        try:
            return s.execute(
                text("SELECT hrv_30d_mean FROM daily_metrics WHERE date = :d"),
                {"d": day.isoformat()},
            ).scalar_one()
        finally:
            s.close()

    assert mean_of(d) == pytest.approx(50.0)  # baseline before the correction
    assert mean_of(d + timedelta(days=30)) == pytest.approx(50.0)

    # Correct D's HRV at the SOURCE record (NOT the derived daily_metrics column).
    fix = SessionLocal()
    try:
        fix.execute(
            text(
                "UPDATE records SET value = 80.0 WHERE type = 'heart_rate_variability_sdnn' "
                "AND start_date LIKE '2026-06-30%'"
            )
        )
        fix.commit()
    finally:
        fix.close()

    DailyMetricsEngine()({d})  # cascade: recompute D + existing rows in [D+1, D+29]

    # D's window: 29 others (50) + D (80) → 51.0; forward rows containing D → 51.0.
    assert mean_of(d) == pytest.approx(51.0)
    assert mean_of(d + timedelta(days=1)) == pytest.approx(51.0)
    assert mean_of(d + timedelta(days=29)) == pytest.approx(51.0)
    # D+30's window is [D+1, D+30] — excludes D — and it is NOT in the cascade → unchanged.
    assert mean_of(d + timedelta(days=30)) == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# corroborated-hard-day TASK-001: per-workout in-window z4+z5 minutes helper.
# The corroboration signal for `hard_day` — credited strictly inside the workout's
# own [start_date, end_date] window, from the single highest-priority HR source.
# Zone bounds (profile.yaml): z1[98,127) z2[127,152) z3[152,170) z4[170,179) z5[179,195].
# ---------------------------------------------------------------------------
W_START = "2026-06-01T18:00:00+03:00"
W_END = "2026-06-01T18:50:00+03:00"  # a 50-minute window


def _win_workout(**over) -> Workouts:
    """A 50-min untyped workout on D1 with a real start/end window."""
    base = {"activity_type": "running", "start": W_START, "duration": 50.0, "unit": "min"}
    base.update(over)
    return _workout(
        base["activity_type"],
        base["start"],
        duration=base["duration"],
        unit=base["unit"],
        end=base.get("end", W_END),
    )


def _z45(session: Session, w: Workouts) -> tuple[float, float] | None:
    return _workout_z45_minutes(session, w, profile=PROFILE)


def test_workout_z45_none_when_no_hr_overlaps_the_window(session: Session) -> None:
    # HR exists on the day, but entirely OUTSIDE the workout window → zones absent.
    _seed(
        session,
        _rec(
            "heart_rate", "2026-06-01T10:00:00+03:00", end="2026-06-01T10:30:00+03:00", value=172.0
        ),
    )
    w = _win_workout()
    _seed(session, w)
    assert _z45(session, w) is None


def test_workout_z45_none_when_window_is_undefined(session: Session) -> None:
    # `end_date is None` and a zero-length window both leave the window undefined.
    _seed(
        session,
        _rec("heart_rate", W_START, end=W_END, value=172.0),
    )
    no_end = _win_workout()
    no_end.end_date = None
    _seed(session, no_end)
    assert _z45(session, no_end) is None

    zero_len = _win_workout(end=W_START)
    _seed(session, zero_len)
    assert _z45(session, zero_len) is None


def test_workout_z45_interval_credits_only_the_window_overlap(session: Session) -> None:
    # A z4 interval 17:50→18:10 half-overlaps the 18:00→18:50 window → 10 min, not 20.
    _seed(
        session,
        _rec(
            "heart_rate", "2026-06-01T17:50:00+03:00", end="2026-06-01T18:10:00+03:00", value=172.0
        ),
    )
    w = _win_workout()
    _seed(session, w)
    z45, credited = _z45(session, w)
    assert z45 == pytest.approx(10.0)
    assert credited == pytest.approx(10.0)


def test_workout_z45_sums_z4_and_z5_only(session: Session) -> None:
    # z4 + z5 are the signal; z1–z3 feed `credited_minutes` but never the z45 sum.
    _seed(
        session,
        _rec(
            "heart_rate", "2026-06-01T18:00:00+03:00", end="2026-06-01T18:06:00+03:00", value=172.0
        ),
        _rec(
            "heart_rate", "2026-06-01T18:06:00+03:00", end="2026-06-01T18:10:00+03:00", value=185.0
        ),
        _rec(
            "heart_rate", "2026-06-01T18:10:00+03:00", end="2026-06-01T18:20:00+03:00", value=130.0
        ),
    )
    w = _win_workout()
    _seed(session, w)
    z45, credited = _z45(session, w)
    assert z45 == pytest.approx(10.0)  # 6 min z4 + 4 min z5
    assert credited == pytest.approx(20.0)  # + 10 min z2


def test_workout_z45_instant_chain_credits_capped_gaps(session: Session) -> None:
    # Live Watch point samples inside the window credit the gap to the next sample,
    # capped at 5 min (`_INSTANT_HR_MAX_CREDIT_S`) — same rule as `zone_minutes`.
    _seed(
        session,
        _rec("heart_rate", "2026-06-01T18:00:00+03:00", value=172.0),  # → 18:04 = 4 min z4
        _rec("heart_rate", "2026-06-01T18:04:00+03:00", value=185.0),  # → 18:24, capped 5 min z5
        _rec("heart_rate", "2026-06-01T18:24:00+03:00", value=110.0),  # last of all → 0
    )
    w = _win_workout()
    _seed(session, w)
    z45, credited = _z45(session, w)
    assert z45 == pytest.approx(9.0)
    assert credited == pytest.approx(9.0)  # the trailing z1 sample credits 0


def test_workout_z45_instant_successor_context_comes_from_outside_the_window(
    session: Session,
) -> None:
    """round-1 #5: the last in-window instant must credit its real gap, clipped to the
    window end — a filter-to-window-first implementation gives it 0 and lands at 10.0,
    just under the 15.0 promotion threshold."""
    _seed(
        session,
        _rec("heart_rate", "2026-06-01T18:00:00+03:00", value=172.0),  # → 18:05 = 5 min z4
        _rec("heart_rate", "2026-06-01T18:05:00+03:00", value=172.0),  # → 18:10 = 5 min z4
        _rec("heart_rate", "2026-06-01T18:10:00+03:00", value=172.0),  # successor at 18:52
        # Successor OUTSIDE the window: gap 42 min → capped 5 min, clipped to 18:50 (40) → 5.
        _rec("heart_rate", "2026-06-01T18:52:00+03:00", value=110.0),
    )
    w = _win_workout()
    _seed(session, w)
    z45, credited = _z45(session, w)
    assert z45 == pytest.approx(15.0)  # NOT 10.0
    assert credited == pytest.approx(15.0)


def test_workout_z45_restricted_to_the_single_highest_priority_source(session: Session) -> None:
    # Watch (rank 0) outranks the phone (rank 2); the phone's z5 minutes must not add.
    _seed(
        session,
        _rec(
            "heart_rate",
            "2026-06-01T18:00:00+03:00",
            end="2026-06-01T18:12:00+03:00",
            value=172.0,
            source="Apple Watch",
        ),
        _rec(
            "heart_rate",
            "2026-06-01T18:00:00+03:00",
            end="2026-06-01T18:30:00+03:00",
            value=185.0,
            source="itsonev-ip15",
        ),
    )
    w = _win_workout()
    _seed(session, w)
    z45, credited = _z45(session, w)
    assert z45 == pytest.approx(12.0)  # Watch only — NOT 42.0
    assert credited == pytest.approx(12.0)


def test_workout_z45_reports_sparse_credited_coverage(session: Session) -> None:
    # round-1 #2: 3 credited minutes of a 50-min window — TASK-002's coverage gate needs
    # `credited_minutes` to tell this from a fully-recorded easy session.
    _seed(
        session,
        _rec(
            "heart_rate", "2026-06-01T18:00:00+03:00", end="2026-06-01T18:03:00+03:00", value=110.0
        ),
    )
    w = _win_workout()
    _seed(session, w)
    z45, credited = _z45(session, w)
    assert z45 == pytest.approx(0.0)
    assert credited == pytest.approx(3.0)


def test_workout_z45_is_zero_not_none_when_the_window_is_covered_but_easy(
    session: Session,
) -> None:
    # Data present, no hard minutes → (0.0, covered) — the "present and zero" case the
    # coverage gate is allowed to trust (mirrors `zone_minutes`' no-data convention).
    _seed(
        session,
        _rec("heart_rate", W_START, end=W_END, value=110.0),
    )
    w = _win_workout()
    _seed(session, w)
    assert _z45(session, w) == (pytest.approx(0.0), pytest.approx(50.0))


def test_zone_minutes_unchanged_by_the_window_credit_extraction(session: Session) -> None:
    # The shared window-crediting core must leave `zone_minutes` byte-identical.
    _seed(
        session,
        _rec(
            "heart_rate", "2026-06-01T09:00:00+03:00", end="2026-06-01T09:10:00+03:00", value=130.0
        ),
        _rec("heart_rate", "2026-06-01T10:00:00+03:00", value=155.0),
        _rec("heart_rate", "2026-06-01T10:03:00+03:00", value=155.0),
    )
    z = zone_minutes(session, D1, profile=PROFILE)
    assert z["z2_min"] == pytest.approx(10.0)
    assert z["z3_min"] == pytest.approx(3.0)
    assert z["z4_min"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# corroborated-hard-day TASK-002: symmetric corroborated hard_day() with typed fallback.
# Either signal confirms ANY workout as hard; the activity-type heuristic survives only
# when BOTH signals are absent, where "absent" is validity-gated (DECISIONS 6 & 7).
# ---------------------------------------------------------------------------
def _hard(session: Session, day: date = D1) -> int:
    return hard_day(session, day, profile=PROFILE)


def _hr_span(start: str, end: str, bpm: float, *, source: str = "Apple Watch") -> Records:
    return _rec("heart_rate", start, end=end, value=bpm, source=source)


def test_hard_day_july_27_regression_typed_but_easy(session: Session) -> None:
    """The reported incident: a HIIT-labelled 50-min session logged at RPE 3 whose
    in-window HR never left z1/z2. The label alone must no longer flag it hard."""
    _seed(
        session,
        _hr_span(W_START, "2026-06-01T18:30:00+03:00", 110.0),  # 30 min z1 → 60 % coverage
        _hr_span("2026-06-01T18:30:00+03:00", W_END, 130.0),  # 20 min z2
    )
    _seed(
        session,
        _workout(
            "high_intensity_interval_training",
            W_START,
            duration=50.0,
            unit="min",
            end=W_END,
            effort=3.0,
        ),
    )
    assert _hard(session) == 0


def test_hard_day_july_27_regression_recomputes_to_zero(session: Session) -> None:
    # The same fixture through the real engine path — the stored column, not the predicate.
    _seed(
        session,
        _hr_span(W_START, "2026-06-01T18:30:00+03:00", 110.0),
        _hr_span("2026-06-01T18:30:00+03:00", W_END, 130.0),
    )
    _seed(
        session,
        _workout(
            "high_intensity_interval_training",
            W_START,
            duration=50.0,
            unit="min",
            end=W_END,
            effort=3.0,
        ),
    )
    recompute_day(session, D1, profile=PROFILE)
    session.commit()
    assert _row(session, "2026-06-01")["hard_day"] == 0


def test_hard_day_promoted_by_effort_on_an_untyped_workout(session: Session) -> None:
    # A threshold run arrives typed `running` — effort 9 over 25 min promotes it.
    _seed(session, _workout("running", W_START, duration=25.0, unit="min", effort=9.0))
    assert _hard(session) == 1


def test_hard_day_promoted_by_in_window_z45_with_null_effort(session: Session) -> None:
    # 16 credited z4 minutes inside the window, no RPE logged at all.
    _seed(session, _hr_span(W_START, "2026-06-01T18:16:00+03:00", 172.0))
    _seed(session, _workout("running", W_START, duration=50.0, unit="min", end=W_END))
    assert _hard(session) == 1


def test_hard_day_promotion_is_not_coverage_gated(session: Session) -> None:
    """round-2 #4: those same 16 z4 minutes cover only 32 % of the 50-min window — below
    `HARD_HR_COVERAGE_MIN_FRAC`. Promotion must still fire; an implementation that applies
    the coverage gate to promotion fails here."""
    _seed(session, _hr_span(W_START, "2026-06-01T18:16:00+03:00", 172.0))
    w = _workout("running", W_START, duration=50.0, unit="min", end=W_END)
    _seed(session, w)
    z45, credited = _workout_z45_minutes(session, w, profile=PROFILE)
    assert z45 == pytest.approx(16.0)
    assert credited == pytest.approx(16.0)  # 32 % of 50 min — under the 50 % gate
    assert _hard(session) == 1


def test_hard_day_not_promoted_by_moderate_effort_and_z3_only(session: Session) -> None:
    # effort 6 (present, under the bar) + a fully-covered z3 window → still not hard.
    _seed(session, _hr_span(W_START, W_END, 155.0))
    _seed(session, _workout("running", W_START, duration=50.0, unit="min", end=W_END, effort=6.0))
    assert _hard(session) == 0


def test_hard_day_typed_fallback_holds_when_both_signals_absent(session: Session) -> None:
    # The unchanged legacy behaviour: no RPE, no HR in the window at all.
    _seed(session, _workout("boxing", W_START, duration=50.0, unit="min", end=W_END))
    assert _hard(session) == 1


def test_hard_day_typed_fallback_holds_when_hr_misses_the_window(session: Session) -> None:
    # The day HAS heart-rate records — just none overlapping the workout → zones absent.
    _seed(session, _hr_span("2026-06-01T10:00:00+03:00", "2026-06-01T10:30:00+03:00", 130.0))
    _seed(session, _workout("boxing", W_START, duration=50.0, unit="min", end=W_END))
    assert _hard(session) == 1


def test_hard_day_sparse_hr_coverage_falls_back_instead_of_demoting(session: Session) -> None:
    """round-1 #2: a watch that recorded 3 easy minutes of a 50-min boxing session and
    stopped must NOT demote it — 6 % coverage means the zones signal is absent."""
    _seed(session, _hr_span(W_START, "2026-06-01T18:03:00+03:00", 110.0))
    _seed(session, _workout("boxing", W_START, duration=50.0, unit="min", end=W_END))
    assert _hard(session) == 1


def test_hard_day_adequate_hr_coverage_demotes_a_typed_workout(session: Session) -> None:
    # Same fixture, 60 % coverage, all z1 → the zones signal is present and disproving.
    _seed(session, _hr_span(W_START, "2026-06-01T18:30:00+03:00", 110.0))
    _seed(session, _workout("boxing", W_START, duration=50.0, unit="min", end=W_END))
    assert _hard(session) == 0


def test_hard_day_coverage_gate_is_boundary_inclusive(session: Session) -> None:
    # Exactly 50 % of the duration credited, all z1 → present (>=), so no fallback → 0.
    _seed(session, _hr_span(W_START, "2026-06-01T18:25:00+03:00", 110.0))
    _seed(session, _workout("boxing", W_START, duration=50.0, unit="min", end=W_END))
    assert _hard(session) == 0


def test_hard_day_out_of_range_high_effort_is_absent_not_a_promotion(session: Session) -> None:
    # round-1 #3: `effort_score = 99` on an easy untyped 30-min workout must not promote.
    _seed(session, _workout("running", W_START, duration=30.0, unit="min", effort=99.0))
    assert _hard(session) == 0


def test_hard_day_out_of_range_low_effort_leaves_the_typed_fallback_intact(
    session: Session,
) -> None:
    # round-1 #3: `effort_score = -3` is nonsense, not evidence — boxing stays hard.
    _seed(session, _workout("boxing", W_START, duration=50.0, unit="min", end=W_END, effort=-3.0))
    assert _hard(session) == 1


def test_hard_day_effort_validity_bounds_are_inclusive(session: Session) -> None:
    # 10.0 is a valid max effort → promotes a 25-min untyped workout.
    _seed(session, _workout("running", W_START, duration=25.0, unit="min", effort=10.0))
    assert _hard(session) == 1
    # 1.0 is a valid easy effort → PRESENT, so it disables the typed fallback on D2.
    _seed(
        session,
        _workout("boxing", "2026-06-02T18:00:00+03:00", duration=50.0, unit="min", effort=1.0),
    )
    assert _hard(session, D2) == 0


def test_hard_day_effort_branch_boundaries_are_inclusive(session: Session) -> None:
    # effort 7.0 AND duration 20.0 — both exactly at the bar → hard.
    _seed(session, _workout("running", W_START, duration=20.0, unit="min", effort=7.0))
    assert _hard(session) == 1


@pytest.mark.parametrize("activity", ["running", "boxing"])
def test_hard_day_effort_7_under_20_min_does_not_flag_even_when_typed(
    session: Session, activity: str
) -> None:
    """round-1 #6, pinned: a 19.9-min 7-RPE burst confirms nothing, but the effort signal
    is PRESENT — so the typed label does not rescue it either. 0 for both variants."""
    _seed(session, _workout(activity, W_START, duration=19.9, unit="min", effort=7.0))
    assert _hard(session) == 0


def test_hard_day_in_window_z45_threshold_is_inclusive(session: Session) -> None:
    # Exactly 15.0 credited z4 minutes (the last in-window instant credits its clipped
    # gap to a successor at 18:52) → hard. A naive 10.0 would not flag.
    _seed(
        session,
        _rec("heart_rate", "2026-06-01T18:00:00+03:00", value=172.0),
        _rec("heart_rate", "2026-06-01T18:05:00+03:00", value=172.0),
        _rec("heart_rate", "2026-06-01T18:10:00+03:00", value=172.0),
        _rec("heart_rate", "2026-06-01T18:52:00+03:00", value=110.0),
    )
    w = _workout("running", W_START, duration=50.0, unit="min", end=W_END)
    _seed(session, w)
    assert _workout_z45_minutes(session, w, profile=PROFILE)[0] == pytest.approx(15.0)
    assert _hard(session) == 1


def test_hard_day_z45_earned_outside_the_window_does_not_flag(session: Session) -> None:
    """round-1 #4: 20 z4 minutes elsewhere in the day, while the workout's own window is
    fully covered and entirely easy. A day-total implementation flags this; the
    per-workout one must not."""
    _seed(
        session,
        _hr_span("2026-06-01T10:00:00+03:00", "2026-06-01T10:20:00+03:00", 172.0),  # 20 z4 min
        _hr_span(W_START, W_END, 110.0),  # the workout itself: 50 min of z1
    )
    _seed(session, _workout("running", W_START, duration=50.0, unit="min", end=W_END))
    assert zone_minutes(session, D1, profile=PROFILE)["z4_min"] == pytest.approx(20.0)
    assert _hard(session) == 0


def test_hard_day_two_workouts_in_window_minutes_are_never_summed(session: Session) -> None:
    # round-1 #4: 8 + 8 in-window z4 minutes across two sessions is 16 day-total but
    # under the bar for each workout — no cross-workout aggregation.
    _seed(
        session,
        _hr_span("2026-06-01T18:00:00+03:00", "2026-06-01T18:08:00+03:00", 172.0),
        _hr_span("2026-06-01T19:00:00+03:00", "2026-06-01T19:08:00+03:00", 172.0),
    )
    _seed(
        session,
        _workout(
            "running",
            "2026-06-01T18:00:00+03:00",
            duration=20.0,
            unit="min",
            end="2026-06-01T18:20:00+03:00",
        ),
        _workout(
            "running",
            "2026-06-01T19:00:00+03:00",
            duration=20.0,
            unit="min",
            end="2026-06-01T19:20:00+03:00",
        ),
    )
    assert zone_minutes(session, D1, profile=PROFILE)["z4_min"] == pytest.approx(16.0)
    assert _hard(session) == 0


def test_hard_day_long_session_flags_regardless_of_signals(session: Session) -> None:
    # The 90-min rule is untouched and NOT corroboration-gated: effort 2, fully-covered
    # easy HR, untyped — still hard.
    _seed(session, _hr_span(W_START, "2026-06-01T19:35:00+03:00", 110.0))
    _seed(
        session,
        _workout(
            "walking",
            W_START,
            duration=95.0,
            unit="min",
            end="2026-06-01T19:35:00+03:00",
            effort=2.0,
        ),
    )
    assert _hard(session) == 1


def test_hard_day_missing_duration_cannot_confirm_by_effort_but_zones_still_promote(
    session: Session,
) -> None:
    # `duration_unit` unknown → `_duration_minutes` is 0: the effort branch can never
    # confirm and zones can never be *present*, but promotion by z4+z5 still fires.
    _seed(session, _hr_span(W_START, "2026-06-01T18:16:00+03:00", 172.0))
    _seed(
        session,
        _workout("running", W_START, duration=3000.0, unit="furlongs", end=W_END, effort=9.0),
    )
    assert _hard(session) == 1
    # Without the z4 window the same workout falls through to 0 (untyped, both absent).
    _seed(
        session,
        _workout(
            "running", "2026-06-02T18:00:00+03:00", duration=3000.0, unit="furlongs", effort=9.0
        ),
    )
    assert _hard(session, D2) == 0


def test_hard_day_constants_are_pinned() -> None:
    assert engine_mod.HARD_EFFORT_MIN == 7.0
    assert engine_mod.HARD_EFFORT_MIN_DURATION_MIN == 20.0
    assert engine_mod.HARD_Z45_MIN == 15.0
    assert engine_mod.HARD_EFFORT_VALID_RANGE == (1.0, 10.0)
    assert engine_mod.HARD_HR_COVERAGE_MIN_FRAC == 0.5
