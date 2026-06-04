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
from app.database.models import Records
from app.services import daily_metrics_engine as engine_mod
from app.services.daily_metrics_engine import (
    PRESERVED_COLUMNS,
    DailyMetricsEngine,
    active_energy,
    expand_affected_dates,
    hrv_sdnn,
    recompute_day,
    rhr,
    sleep_h,
    steps,
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
) -> Records:
    return Records(
        type=type_,
        start_date=start,
        end_date=end if end is not None else start,
        value=value,
        value_text=value_text,
        source_name=source,
        unit=unit,
        origin="sync",
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
