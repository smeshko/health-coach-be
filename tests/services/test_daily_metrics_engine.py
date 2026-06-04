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
from datetime import date, datetime

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
    active_energy,
    body_weight,
    expand_affected_dates,
    hard_day,
    hrv_baseline,
    hrv_sdnn,
    nutrition_intake,
    recompute_day,
    rhr,
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


def test_recompute_day_does_not_clobber_later_phase_columns(session: Session) -> None:
    day = date(2026, 6, 1)
    recompute_day(session, day, profile=PROFILE)
    session.commit()
    # E6·P2 / E11 fill these later — a P1 re-run must not wipe them.
    session.execute(
        text(
            "UPDATE daily_metrics SET hrv_30d_mean = 42.0, hrv_30d_sd = 5.5, "
            "rhr_30d_mean = 52.0, readiness_score = 80, band = 'GREEN' WHERE date = :d"
        ),
        {"d": "2026-06-01"},
    )
    session.commit()

    recompute_day(session, day, profile=PROFILE)
    session.commit()

    row = _row(session, "2026-06-01")
    assert row["hrv_30d_mean"] == 42.0
    assert row["hrv_30d_sd"] == 5.5
    assert row["rhr_30d_mean"] == 52.0
    assert row["readiness_score"] == 80
    assert row["band"] == "GREEN"


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
        _rec("sleep_analysis", "2026-06-01T01:00:00+03:00", end="2026-06-01T02:00:00+03:00",
             value_text="asleepCore"),
        _rec("sleep_analysis", "2026-06-01T02:00:00+03:00", end="2026-06-01T02:30:00+03:00",
             value_text="asleepREM"),
        # inBed / awake must NOT count
        _rec("sleep_analysis", "2026-06-01T00:30:00+03:00", end="2026-06-01T01:00:00+03:00",
             value_text="inBed"),
    )
    assert sleep_h(session, D1) == pytest.approx(1.5)
    assert sleep_h(session, D2) is None  # nothing wakes on D2


def test_sleep_h_cross_midnight_anchors_wholly_to_wake_day(session: Session) -> None:
    # 23:30 (D1) → 07:00 (D2) Sofia = 7.5h asleep, all credited to the WAKE day (D2).
    _seed(
        session,
        _rec("sleep_analysis", "2026-06-01T23:30:00+03:00", end="2026-06-02T07:00:00+03:00",
             value_text="asleepCore"),
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
    _seed(session, _rec("step_count", "2026-06-01T11:00:00+03:00", value=7000.0, source="itsonev-ip15"))
    assert steps(session, D1) == 7000


def test_steps_none_when_no_record_and_zero_from_picked_source(session: Session) -> None:
    assert steps(session, D1) is None
    _seed(session, _rec("step_count", "2026-06-01T11:00:00+03:00", value=0.0, source="Apple Watch"))
    assert steps(session, D1) == 0  # a real zero from the picked source, not None


def test_active_energy_source_deduped_watch_over_workout_app(session: Session) -> None:
    _seed(
        session,
        _rec("active_energy_burned", "2026-06-01T18:00:00+03:00", value=500.0, source="Apple Watch"),
        _rec("active_energy_burned", "2026-06-01T18:00:00+03:00", value=300.0, source="Strava"),
    )
    assert active_energy(session, D1) == 500.0  # Watch only
    assert active_energy(session, D2) is None


def test_zone_minutes_bucketing_boundary_and_full_duration(session: Session) -> None:
    _seed(
        session,
        # full-duration in-day sample: 130 bpm (z2) for 10 min
        _rec("heart_rate", "2026-06-01T10:00:00+03:00", end="2026-06-01T10:10:00+03:00", value=130.0),
        # boundary sample: 125 bpm lands in z2 (low <= bpm < high) for 5 min
        _rec("heart_rate", "2026-06-01T10:10:00+03:00", end="2026-06-01T10:15:00+03:00", value=125.0),
        # 100 bpm (z1) for 4 min
        _rec("heart_rate", "2026-06-01T10:15:00+03:00", end="2026-06-01T10:19:00+03:00", value=100.0),
    )
    z = zone_minutes(session, D1, profile=PROFILE)
    assert z["z1_min"] == pytest.approx(4.0)
    assert z["z2_min"] == pytest.approx(15.0)  # 10 + 5 (boundary 125 → z2)
    assert z["z3_min"] == pytest.approx(0.0)


def test_zone_minutes_split_across_sofia_midnight(session: Session) -> None:
    # 23:50 (D1) → 00:10 (D2) at 130 bpm (z2): 10 min each side of the boundary.
    _seed(
        session,
        _rec("heart_rate", "2026-06-01T23:50:00+03:00", end="2026-06-02T00:10:00+03:00", value=130.0),
    )
    assert zone_minutes(session, D1, profile=PROFILE)["z2_min"] == pytest.approx(10.0)
    assert zone_minutes(session, D2, profile=PROFILE)["z2_min"] == pytest.approx(10.0)


def test_zone_minutes_hr_source_deduped(session: Session) -> None:
    # Overlapping Watch (z2) + Garmin (z3) HR: minutes from the priority Watch only.
    _seed(
        session,
        _rec("heart_rate", "2026-06-01T10:00:00+03:00", end="2026-06-01T10:10:00+03:00",
             value=130.0, source="Apple Watch"),
        _rec("heart_rate", "2026-06-01T10:00:00+03:00", end="2026-06-01T10:10:00+03:00",
             value=160.0, source="Garmin Connect"),
    )
    z = zone_minutes(session, D1, profile=PROFILE)
    assert z["z2_min"] == pytest.approx(10.0)  # Watch
    assert z["z3_min"] == pytest.approx(0.0)  # Garmin's 160 bpm dropped — no doubled minutes


def test_zone_minutes_none_when_no_hr_records(session: Session) -> None:
    z = zone_minutes(session, D1, profile=PROFILE)
    assert all(z[c] is None for c in ("z1_min", "z2_min", "z3_min", "z4_min", "z5_min"))


def test_instant_metric_attributed_to_sofia_date(session: Session) -> None:
    # 23:30 UTC on 06-02 → 02:30 Sofia (+03:00) on 06-03 → counts on the Sofia date.
    _seed(session, _rec("step_count", "2026-06-02T23:30:00+00:00", value=5000.0, source="Apple Watch"))
    assert steps(session, date(2026, 6, 3)) == 5000
    assert steps(session, D2) is None  # not the wire-offset date


def test_expand_affected_dates_pulls_cross_midnight_neighbour(session: Session) -> None:
    _seed(
        session,
        _rec("heart_rate", "2026-06-01T23:50:00+03:00", end="2026-06-02T00:10:00+03:00", value=130.0),
    )
    # Handed only the start day (E5·P3 fans out by start) → engine widens to both days.
    assert expand_affected_dates(session, {D1}) == {D1, D2}


def test_engine_recomputes_both_rows_for_cross_midnight_sample(engine_db: str) -> None:
    seed = SessionLocal()
    try:
        seed.add(_rec("heart_rate", "2026-06-01T23:50:00+03:00", end="2026-06-02T00:10:00+03:00",
                      value=130.0))
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
    activity_type: str, start: str, *, duration: float, unit: str = "s", origin: str = "sync"
) -> Workouts:
    return Workouts(
        activity_type=activity_type,
        start_date=start,
        end_date=start,
        duration=duration,
        duration_unit=unit,
        origin=origin,
    )


def test_nutrition_intake_dominant_app_not_cross_sum(session: Session) -> None:
    # MacroFactor (higher kcal_in) is dominant; MyFitnessPal's entries are NOT summed in.
    _seed(
        session,
        _rec("dietary_energy_consumed", "2026-06-01T12:00:00+03:00", value=2000.0, source="MacroFactor"),
        _rec("dietary_protein", "2026-06-01T12:00:00+03:00", value=150.0, source="MacroFactor"),
        _rec("dietary_carbohydrates", "2026-06-01T12:00:00+03:00", value=220.0, source="MacroFactor"),
        # a second app logged the same day (lower kcal) — must be ignored entirely
        _rec("dietary_energy_consumed", "2026-06-01T13:00:00+03:00", value=900.0, source="MyFitnessPal"),
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


@pytest.mark.parametrize("activity", ["boxing", "high_intensity_interval_training", "kickboxing", "martial_arts"])
def test_hard_day_per_hard_activity_type(session: Session, activity: str) -> None:
    _seed(session, _workout(activity, "2026-06-01T18:00:00+03:00", duration=1800.0, unit="s"))
    assert hard_day(session, D1) == 1


def test_hard_day_long_duration_threshold_inclusive(session: Session) -> None:
    # 89 min → 0, 90 min → 1 (inclusive), 91 min → 1; an easy short session → 0.
    _seed(session, _workout("running", "2026-06-01T18:00:00+03:00", duration=89.0, unit="min"))
    assert hard_day(session, D1) == 0

    # A distinct day per case so the workouts don't accumulate ambiguously.
    _seed(session, _workout("running", "2026-06-02T18:00:00+03:00", duration=90.0, unit="min"))
    assert hard_day(session, D2) == 1
    _seed(session, _workout("cycling", "2026-06-03T18:00:00+03:00", duration=91.0, unit="min"))
    assert hard_day(session, date(2026, 6, 3)) == 1


def test_hard_day_seconds_unit_normalized(session: Session) -> None:
    # 5400 s == 90 min → hard (pins the duration_unit normalization).
    _seed(session, _workout("rowing", "2026-06-01T18:00:00+03:00", duration=5400.0, unit="s"))
    assert hard_day(session, D1) == 1


def test_hard_day_easy_only_and_empty_day_are_zero(session: Session) -> None:
    assert hard_day(session, D1) == 0  # empty day
    _seed(session, _workout("walking", "2026-06-01T18:00:00+03:00", duration=1200.0, unit="s"))
    assert hard_day(session, D1) == 0  # 20 min easy walk


def test_full_p1_row_matches_source_with_baselines_null(session: Session) -> None:
    # The integrating assertion (PLAN Acceptance #1): every P1 column reflects the
    # source, with the 30-day baselines + readiness null.
    _seed(
        session,
        _rec("sleep_analysis", "2026-05-31T23:30:00+03:00", end="2026-06-01T07:00:00+03:00",
             value_text="asleepCore"),
        _rec("heart_rate_variability_sdnn", "2026-06-01T06:30:00+03:00", value=48.0),
        _rec("resting_heart_rate", "2026-06-01T06:30:00+03:00", value=54.0),
        _rec("step_count", "2026-06-01T10:00:00+03:00", value=9000.0, source="Apple Watch"),
        _rec("active_energy_burned", "2026-06-01T10:00:00+03:00", value=500.0, source="Apple Watch"),
        _rec("heart_rate", "2026-06-01T10:00:00+03:00", end="2026-06-01T10:10:00+03:00", value=130.0),
        _rec("body_mass", "2026-06-01T07:00:00+03:00", value=78.4),
        _rec("dietary_energy_consumed", "2026-06-01T12:00:00+03:00", value=2200.0, source="MacroFactor"),
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
        _rec("dietary_energy_consumed", "2026-06-02T23:30:00+00:00", value=2100.0, source="MacroFactor"),
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
        _rec("HKCategoryTypeIdentifierSleepAnalysis", "2026-05-31T23:30:00+03:00",
             end="2026-06-01T07:00:00+03:00", value_text="HKCategoryValueSleepAnalysisAsleepCore",
             origin="seed"),
        _rec("HKQuantityTypeIdentifierHeartRateVariabilitySDNN", "2026-06-01T06:30:00+03:00",
             value=48.0, origin="seed"),
        _rec("HKQuantityTypeIdentifierRestingHeartRate", "2026-06-01T06:30:00+03:00",
             value=54.0, origin="seed"),
        _rec("HKQuantityTypeIdentifierStepCount", "2026-06-01T10:00:00+03:00", value=9000.0,
             source="Apple Watch", origin="seed"),
        _rec("HKQuantityTypeIdentifierActiveEnergyBurned", "2026-06-01T10:00:00+03:00", value=500.0,
             source="Apple Watch", origin="seed"),
        _rec("HKQuantityTypeIdentifierHeartRate", "2026-06-01T10:00:00+03:00",
             end="2026-06-01T10:10:00+03:00", value=130.0, origin="seed"),
        _rec("HKQuantityTypeIdentifierBodyMass", "2026-06-01T07:00:00+03:00", value=78.4,
             origin="seed"),
        _rec("HKQuantityTypeIdentifierDietaryEnergyConsumed", "2026-06-01T12:00:00+03:00",
             value=2200.0, source="MacroFactor", origin="seed"),
        _rec("HKQuantityTypeIdentifierDietaryProtein", "2026-06-01T12:00:00+03:00",
             value=160.0, source="MacroFactor", origin="seed"),
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
        _rec("HKQuantityTypeIdentifierDietaryEnergyConsumed", "2026-06-01T12:00:00+03:00",
             value=1200.0, source="MacroFactor"),
        _rec("dietary_energy_consumed", "2026-06-01T19:00:00+03:00", value=900.0, source="MacroFactor"),
    )
    # Both rows are the same canonical type + source → summed to one app's kcal.
    assert nutrition_intake(session, D1)["kcal_in"] == 2100.0


@pytest.mark.parametrize(
    "hk_activity",
    ["HKWorkoutActivityTypeBoxing", "HKWorkoutActivityTypeHighIntensityIntervalTraining",
     "HKWorkoutActivityTypeKickboxing", "HKWorkoutActivityTypeMartialArts"],
)
def test_hard_day_matches_seeded_hk_workout_activity_types(session: Session, hk_activity: str) -> None:
    # A sub-90-min seeded hard session (HK activity form) must read hard_day=1.
    _seed(session, _workout(hk_activity, "2026-06-01T18:00:00+03:00", duration=1800.0, unit="s"))
    assert hard_day(session, D1) == 1


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
        _rec("HKQuantityTypeIdentifierStepCount", "2026-06-01T09:00:00+03:00", value=9000.0,
             source="Apple Watch", origin="seed"),
        _rec("HKQuantityTypeIdentifierActiveEnergyBurned", "2026-06-01T09:00:00+03:00", value=400.0,
             source="Apple Watch", origin="seed"),
        # live /sync for the same day — authoritative for the WHOLE day
        _rec("step_count", "2026-06-01T18:00:00+03:00", value=10000.0, source="Apple Watch",
             origin="sync"),
        _rec("active_energy_burned", "2026-06-01T18:00:00+03:00", value=550.0, source="Apple Watch",
             origin="sync"),
    )
    assert steps(session, D1) == 10000  # sync only — NOT 19000
    assert active_energy(session, D1) == 550.0  # sync only — NOT 950


def test_sync_covered_day_drops_seed_metric_even_when_sync_lacks_it(session: Session) -> None:
    # reconcile_seed drops ALL seed rows on a covered day, so a seed-only metric on a
    # day the live sync covers is gone — the engine matches that post-reconcile state.
    _seed(
        session,
        _rec("step_count", "2026-06-01T18:00:00+03:00", value=10000.0, source="Apple Watch",
             origin="sync"),  # makes D1 "covered"
        _rec("HKQuantityTypeIdentifierBodyMass", "2026-06-01T07:00:00+03:00", value=78.4,
             origin="seed"),  # seed-only metric on a covered day → superseded
    )
    assert body_weight(session, D1) is None  # seed body_mass dropped on the covered day


def test_uncovered_seed_day_keeps_seed_rows(session: Session) -> None:
    # D1 has only seed rows (no sync) → not covered → seed rows are read.
    _seed(
        session,
        _rec("HKQuantityTypeIdentifierStepCount", "2026-06-01T09:00:00+03:00", value=9000.0,
             source="Apple Watch", origin="seed"),
    )
    assert steps(session, D1) == 9000  # kept — a partial/uncovered day keeps its seed


def test_hard_day_seed_workout_superseded_on_sync_covered_day(session: Session) -> None:
    # A live sync row covers D1, so a seed boxing workout on D1 is superseded.
    _seed(session, _rec("step_count", "2026-06-01T18:00:00+03:00", value=8000.0, origin="sync"))
    session.add(_workout("HKWorkoutActivityTypeBoxing", "2026-06-01T19:00:00+03:00",
                         duration=1800.0, unit="s", origin="seed"))
    session.commit()
    assert hard_day(session, D1) == 0  # seed boxing dropped on the covered day


# ---------------------------------------------------------------------------
# Review round-3 #1: a cross-midnight live sync interval must supersede seed rows on
# the NEIGHBOUR day it reaches too — coverage is contribution-day aware (HR overlap,
# sleep wake), not just the sync row's own start day.
# ---------------------------------------------------------------------------
def test_cross_midnight_sync_hr_supersedes_seed_on_neighbour_day(session: Session) -> None:
    _seed(
        session,
        # live HR spanning D1->D2 (start-day D1, but contributes minutes to D2 too)
        _rec("heart_rate", "2026-06-01T23:50:00+03:00", end="2026-06-02T00:10:00+03:00",
             value=130.0, source="Apple Watch", origin="sync"),
        # seeded HR fully within D2, same source — would double-count D2 without the fix
        _rec("HKQuantityTypeIdentifierHeartRate", "2026-06-02T02:00:00+03:00",
             end="2026-06-02T02:10:00+03:00", value=130.0, source="Apple Watch", origin="seed"),
    )
    # D2 is covered by the cross-midnight sync row → the D2 seed HR is superseded.
    assert zone_minutes(session, D2, profile=PROFILE)["z2_min"] == pytest.approx(10.0)  # not 20.0


def test_cross_midnight_sync_sleep_supersedes_seed_on_wake_day(session: Session) -> None:
    _seed(
        session,
        # live sleep waking on D2 (sync, 7.5h)
        _rec("sleep_analysis", "2026-06-01T23:30:00+03:00", end="2026-06-02T07:00:00+03:00",
             value_text="asleepCore", origin="sync"),
        # seeded sleep also waking on D2 (HK form) — would double sleep_h without the fix
        _rec("HKCategoryTypeIdentifierSleepAnalysis", "2026-06-01T23:00:00+03:00",
             end="2026-06-02T06:00:00+03:00", value_text="HKCategoryValueSleepAnalysisAsleepCore",
             origin="seed"),
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
        _rec("heart_rate", "2026-06-01T23:50:00+03:00", end="2026-06-02T00:10:00+03:00",
             value=130.0, source="Apple Watch", origin="seed"),
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
        _rec("heart_rate", "2026-06-01T23:50:00+03:00", end="2026-06-02T00:00:00+03:00",
             value=130.0, source="Apple Watch", origin="sync"),
        # seed HR on D2 — must NOT be superseded (D2 is uncovered)
        _rec("heart_rate", "2026-06-02T08:00:00+03:00", end="2026-06-02T08:10:00+03:00",
             value=130.0, source="Apple Watch", origin="seed"),
    )
    assert zone_minutes(session, D2, profile=PROFILE)["z2_min"] == pytest.approx(10.0)  # seed kept


# ===========================================================================
# E6·P2 — rolling 30-day HRV/RHR baselines.
# ===========================================================================
def _dm(session: Session, day: str, *, hrv: float | None = None, rhr_v: float | None = None) -> None:
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
