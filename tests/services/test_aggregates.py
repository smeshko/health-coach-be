"""E6·P3 7/28-day rollup tests — pure read-side sums over the migrated temp `app.db`.

Uses the `session` fixture (tests/services/conftest.py: migrated temp-file `app.db` +
a bound Session). Rows are seeded as plain `DailyMetrics` ORM inserts — this phase
reads `daily_metrics` directly, it does not drive `/sync` or the E6·P1 engine.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.models import DailyMetrics
from app.services.aggregates import (
    Aggregates,
    NutritionTarget,
    load_aggregates,
    nutrition_adherence,
    nutrition_consumed,
    training_rollup,
    window_bounds,
)

D = date(2026, 6, 30)


def _dm(session: Session, day: date, **cols) -> None:
    session.add(DailyMetrics(date=day.isoformat(), **cols))


def _count(session: Session, table: str = "daily_metrics") -> int:
    return session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


# ---------------------------------------------------------------------------
# window_bounds
# ---------------------------------------------------------------------------
def test_window_bounds_inclusive_both_ends() -> None:
    assert window_bounds(D, 7) == ((D - timedelta(days=6)).isoformat(), D.isoformat())
    assert window_bounds(D, 28) == ((D - timedelta(days=27)).isoformat(), D.isoformat())


# ---------------------------------------------------------------------------
# training_rollup
# ---------------------------------------------------------------------------
def test_training_rollup_7d_hand_summed(session: Session) -> None:
    # 7-day window [D-6, D]: z1=10 each (×7=70), active_energy=100 each (×7=700),
    # hard_day=1 on 3 days. A D-7 row is outside the window and must be excluded.
    for i in range(7):  # D-6 .. D
        day = D - timedelta(days=6 - i)
        _dm(session, day, z1_min=10.0, z2_min=2.0, z3_min=3.0, z4_min=4.0, z5_min=5.0,
            active_energy=100.0, hard_day=(1 if i < 3 else 0))
    _dm(session, D - timedelta(days=7), z1_min=999.0, active_energy=9999.0, hard_day=1)  # OUT
    session.commit()

    r = training_rollup(session, D, 7)
    assert r.days == 7
    assert r.z1_min == pytest.approx(70.0)  # excludes the D-7 row's 999
    assert r.z2_min == pytest.approx(14.0)
    assert r.z5_min == pytest.approx(35.0)
    assert r.active_energy == pytest.approx(700.0)
    assert r.hard_days == 3
    assert r.n_days == 7


def test_training_rollup_28d_hand_summed(session: Session) -> None:
    for i in range(28):  # D-27 .. D
        _dm(session, D - timedelta(days=27 - i), z1_min=1.0, active_energy=50.0,
            hard_day=(1 if i % 2 == 0 else 0))
    _dm(session, D - timedelta(days=28), z1_min=999.0)  # OUT of the 28d window
    session.commit()

    r = training_rollup(session, D, 28)
    assert r.z1_min == pytest.approx(28.0)  # excludes D-28
    assert r.active_energy == pytest.approx(28 * 50.0)
    assert r.hard_days == 14  # even indices 0..26
    assert r.n_days == 28


def test_training_rollup_window_boundary(session: Session) -> None:
    _dm(session, D - timedelta(days=7), z1_min=100.0)  # D-7 → OUT of 7d
    _dm(session, D - timedelta(days=6), z1_min=10.0)   # D-6 (start) → IN
    _dm(session, D, z1_min=1.0)                          # D (anchor) → IN
    session.commit()
    r = training_rollup(session, D, 7)
    assert r.z1_min == pytest.approx(11.0)  # D-6 + D only; D-7 excluded
    assert r.n_days == 2


def test_training_rollup_null_safe_and_empty(session: Session) -> None:
    # A NULL cell sums to 0 (not None); other columns still sum.
    _dm(session, D, z1_min=None, z3_min=None, active_energy=None, hard_day=None)
    _dm(session, D - timedelta(days=1), z1_min=5.0, active_energy=20.0, hard_day=1)
    session.commit()
    r = training_rollup(session, D, 7)
    assert r.z1_min == pytest.approx(5.0)  # the NULL contributed 0
    assert r.z3_min == pytest.approx(0.0)
    assert r.active_energy == pytest.approx(20.0)
    assert r.hard_days == 1
    assert r.n_days == 2

    # Empty window (anchor far from any row) → all-zero, n_days 0, no None.
    empty = training_rollup(session, date(2030, 1, 1), 7)
    assert empty.z1_min == 0.0
    assert empty.active_energy == 0.0
    assert empty.hard_days == 0
    assert empty.n_days == 0


def test_training_rollup_performs_no_write(session: Session) -> None:
    _dm(session, D, z1_min=10.0)
    session.commit()
    before = _count(session)
    training_rollup(session, D, 7)
    training_rollup(session, D, 28)
    assert _count(session) == before  # read-only — no row written


# ---------------------------------------------------------------------------
# nutrition_consumed / nutrition_adherence (TASK-002)
# ---------------------------------------------------------------------------
def test_nutrition_consumed_hand_summed_with_logged_day_counts(session: Session) -> None:
    _dm(session, D - timedelta(days=6), kcal_in=2000.0, protein_in_g=150.0, carbs_in_g=200.0,
        fat_in_g=70.0, fiber_in_g=30.0, sodium_in_mg=2300.0, water_in_l=3.0)
    _dm(session, D - timedelta(days=5), kcal_in=2200.0, protein_in_g=140.0)
    _dm(session, D - timedelta(days=4), kcal_in=1800.0, protein_in_g=160.0)
    _dm(session, D, sleep_h=8.0)  # row present, no dietary logged
    session.commit()
    c = nutrition_consumed(session, D, 7)
    assert c.kcal_in == pytest.approx(6000.0)
    assert c.protein_in_g == pytest.approx(450.0)
    assert c.carbs_in_g == pytest.approx(200.0)  # only D-6 logged carbs
    assert c.n_days == 4  # rows present
    assert c.kcal_in_n == 3  # days kcal logged
    assert c.protein_in_g_n == 3
    assert c.carbs_in_g_n == 1
    assert c.sodium_in_mg_n == 1
    assert c.water_in_l_n == 1


def test_nutrition_consumed_window_boundary(session: Session) -> None:
    _dm(session, D - timedelta(days=7), kcal_in=999.0)  # OUT of 7d
    _dm(session, D - timedelta(days=6), kcal_in=100.0)  # IN (start)
    _dm(session, D, kcal_in=50.0)                        # IN (anchor)
    session.commit()
    c = nutrition_consumed(session, D, 7)
    assert c.kcal_in == pytest.approx(150.0)  # excludes the D-7 row
    assert c.kcal_in_n == 2


def test_nutrition_adherence_no_target_consumed_only(session: Session) -> None:
    _dm(session, D, kcal_in=2000.0, protein_in_g=150.0)
    session.commit()
    a = nutrition_adherence(session, D, 7, target=None)
    assert a.consumed.kcal_in == pytest.approx(2000.0)
    assert a.avg_kcal is None
    assert a.avg_protein_g is None
    assert a.kcal_pct is None
    assert a.protein_hit_days is None
    assert a.days_over_target is None
    assert a.days_under_target is None


def test_nutrition_adherence_per_day_comparison(session: Session) -> None:
    # 3 logged days: kcal [2000, 2200, 1800], protein [150, 140, 160].
    _dm(session, D - timedelta(days=6), kcal_in=2000.0, protein_in_g=150.0)
    _dm(session, D - timedelta(days=5), kcal_in=2200.0, protein_in_g=140.0)
    _dm(session, D - timedelta(days=4), kcal_in=1800.0, protein_in_g=160.0)
    session.commit()
    target = NutritionTarget(kcal=2100.0, protein_g=145.0, carbs_g=250.0,
                             fat_g_low=60.0, fat_g_high=80.0, water_l_low=3.0, water_l_high=3.5)
    a = nutrition_adherence(session, D, 7, target=target)
    assert a.avg_kcal == pytest.approx(2000.0)  # 6000/3
    assert a.avg_protein_g == pytest.approx(150.0)  # 450/3
    assert a.kcal_pct == pytest.approx(2000.0 / 2100.0)
    assert a.protein_hit_days == 2  # 150,160 >= 145; 140 < 145
    assert a.days_over_target == 1  # 2200 > 2100
    assert a.days_under_target == 2  # 2000,1800 < 2100


def test_nutrition_adherence_zero_kcal_target_guards(session: Session) -> None:
    _dm(session, D, kcal_in=2000.0, protein_in_g=150.0)
    session.commit()
    a = nutrition_adherence(session, D, 7, target=NutritionTarget(kcal=0.0, protein_g=140.0))
    assert a.kcal_pct is None  # divide-by-zero guard
    assert a.days_over_target is None  # no meaningful kcal target
    assert a.days_under_target is None
    assert a.avg_kcal == pytest.approx(2000.0)  # other fields still computed
    assert a.avg_protein_g == pytest.approx(150.0)
    assert a.protein_hit_days == 1  # 150 >= 140


def test_nutrition_adherence_null_only_window_unknown_not_zero(session: Session) -> None:
    # Rows present but ALL dietary NULL + a non-zero target → unknown, never 0%.
    _dm(session, D, sleep_h=8.0)
    _dm(session, D - timedelta(days=1), steps=10000)
    session.commit()
    a = nutrition_adherence(session, D, 7, target=NutritionTarget(kcal=2000.0, protein_g=150.0))
    assert a.consumed.kcal_in == pytest.approx(0.0)  # COALESCE sum
    assert a.consumed.kcal_in_n == 0  # nothing logged
    assert a.consumed.n_days == 2  # rows present (coverage distinct from logged)
    assert a.avg_kcal is None
    assert a.kcal_pct is None  # NOT 0%
    assert a.protein_hit_days is None
    assert a.days_over_target is None
    assert a.days_under_target is None


def test_nutrition_adherence_partial_logging_counts_only_logged(session: Session) -> None:
    for i in range(6):  # 6 rows present, no dietary
        _dm(session, D - timedelta(days=6 - i), sleep_h=8.0)
    _dm(session, D, kcal_in=2500.0, protein_in_g=120.0)  # the one logged day
    session.commit()
    a = nutrition_adherence(session, D, 7, target=NutritionTarget(kcal=2000.0, protein_g=150.0))
    assert a.consumed.n_days == 7
    assert a.consumed.kcal_in_n == 1  # coverage reflects sparse logging
    assert a.avg_kcal == pytest.approx(2500.0)  # only the logged day
    assert a.days_over_target == 1  # 2500 > 2000
    assert a.days_under_target == 0
    assert a.protein_hit_days == 0  # 120 < 150


# ---------------------------------------------------------------------------
# load_aggregates + Aggregates.to_dict (TASK-003)
# ---------------------------------------------------------------------------
def test_load_aggregates_full_shape_and_reads_cache_not_source(session: Session) -> None:
    _dm(session, D, z1_min=10.0, active_energy=100.0, hard_day=1, kcal_in=2000.0, protein_in_g=150.0)
    _dm(session, D - timedelta(days=10), z1_min=5.0, active_energy=50.0, kcal_in=1500.0)
    session.commit()
    # Pure read-side: no records/workouts seeded at all.
    assert _count(session, "records") == 0
    assert _count(session, "workouts") == 0

    aggs = load_aggregates(session, D)
    assert isinstance(aggs, Aggregates)
    assert aggs.anchor == D
    assert aggs.training_7d.z1_min == pytest.approx(10.0)  # only D in the 7d window
    assert aggs.training_28d.z1_min == pytest.approx(15.0)  # D + D-10 in the 28d window
    assert aggs.nutrition_7d.consumed.kcal_in == pytest.approx(2000.0)
    assert aggs.nutrition_28d.consumed.kcal_in == pytest.approx(3500.0)
    # No target → ratios None.
    assert aggs.nutrition_7d.kcal_pct is None
    assert aggs.nutrition_28d.kcal_pct is None


def test_load_aggregates_distinct_targets_no_swap(session: Session) -> None:
    _dm(session, D, kcal_in=2100.0, protein_in_g=150.0)               # in both windows
    _dm(session, D - timedelta(days=20), kcal_in=1000.0, protein_in_g=100.0)  # 28d only
    session.commit()
    a = NutritionTarget(kcal=2000.0, protein_g=145.0)  # 7d target
    b = NutritionTarget(kcal=3000.0, protein_g=145.0)  # 28d target (distinct)
    aggs = load_aggregates(session, D, nutrition_target_7d=a, nutrition_target_28d=b)

    # 7d uses A: avg 2100 / 2000
    assert aggs.nutrition_7d.kcal_pct == pytest.approx(2100.0 / 2000.0)
    assert aggs.nutrition_7d.days_over_target == 1   # 2100 > 2000
    assert aggs.nutrition_7d.days_under_target == 0
    # 28d uses B: avg (2100+1000)/2 = 1550 / 3000
    assert aggs.nutrition_28d.kcal_pct == pytest.approx(1550.0 / 3000.0)
    assert aggs.nutrition_28d.days_over_target == 0  # both < 3000
    assert aggs.nutrition_28d.days_under_target == 2


def test_load_aggregates_target_28d_alone(session: Session) -> None:
    _dm(session, D, kcal_in=2100.0)
    session.commit()
    aggs = load_aggregates(session, D, nutrition_target_28d=NutritionTarget(kcal=2000.0))
    assert aggs.nutrition_28d.kcal_pct == pytest.approx(2100.0 / 2000.0)  # 28d filled
    assert aggs.nutrition_7d.kcal_pct is None  # 7d had no target


def test_to_dict_json_serialisable_with_coverage(session: Session) -> None:
    # A sparse 7d window (1 logged of 5 rows) — the low ratio travels with its coverage.
    for i in range(4):
        _dm(session, D - timedelta(days=6 - i), sleep_h=8.0)  # rows present, no dietary
    _dm(session, D, kcal_in=1000.0)  # the one logged day
    session.commit()
    aggs = load_aggregates(session, D, nutrition_target_7d=NutritionTarget(kcal=2000.0))

    blob = json.dumps(aggs.to_dict())  # must not raise
    data = json.loads(blob)
    assert data["anchor"] == D.isoformat()
    assert "training_7d" in data and "training_28d" in data
    n7 = data["nutrition_7d"]
    # ratio is serialised ALONGSIDE its coverage (n_days + per-nutrient logged count).
    assert n7["kcal_pct"] == pytest.approx(1000.0 / 2000.0)  # 0.5 — a low ratio...
    assert n7["consumed"]["kcal_in_n"] == 1                  # ...next to its small coverage
    assert n7["consumed"]["n_days"] == 5


def test_load_aggregates_performs_no_write(session: Session) -> None:
    _dm(session, D, kcal_in=2000.0, z1_min=10.0)
    session.commit()
    before = _count(session)
    load_aggregates(session, D, nutrition_target_7d=NutritionTarget(kcal=2000.0))
    assert _count(session) == before  # read-only
