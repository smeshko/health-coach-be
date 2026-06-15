"""WEEKLY_PLANNER workflow tests — the deterministic graph, agent mocked (E10·P2).

The single ``AgentNode`` (``GeneratePlanNode``) is **never** invoked live: the per-node
tests seed a hand-built ``WeeklyPlanLLMOutput`` under ``ctx.nodes["GeneratePlanNode"]``,
and the end-to-end tests (TASK-004) substitute a stand-in ``Node`` — no PydanticAI,
network, or ``ANTHROPIC_API_KEY``. The DB ``Session`` rides in ``ctx.metadata["session"]``
(the endpoint seam), and a temp ``profile.yaml`` (via ``PROFILE_PATH``) controls the
constants. Mirrors the E1·P3 ``tests/core/`` workflow pattern.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest
import yaml
from sqlalchemy import select

from app.api.schemas.weekly import NarrativeSection, PlannedPick, WeeklyPlanLLMOutput
from app.core.enums import NarrativeType, Weekday, WorkoutCard
from app.core.profile import load_profile
from app.core.task_context import TaskContext
from app.core.agent_node import BriefGenerationError
from app.core.constraints import WeeklyBudgets
from app.core.weekly_agent import GeneratePlanNode
from app.core.weekly_planner import (
    ComputeBudgetsNode,
    ComputeNutritionNode,
    ComputeTargetsNode,
    DeriveSessionsNode,
    LoadAggregatesNode,
    PersistPlanNode,
    RecomputeConstants,
    RecomputeConstantsOutput,
    ValidatePlanNode,
    WeeklyPlanner,
    WeeklyPlannerEvent,
    is_recompute_due,
)
from app.database.models import DailyMetrics, Plans, StrengthTests, Workouts

from tests.core.test_profile import valid_profile_dict

ANCHOR = date(2026, 6, 7)  # a Sunday — end of 2026-W23
ISO_WEEK = "2026-W23"
WEEK_START = date(2026, 6, 1)


# --------------------------------------------------------------------------- #
# Fixtures: a temp profile.yaml + a seeded daily_metrics window.
# --------------------------------------------------------------------------- #
def _write_profile_yaml(tmp_path, monkeypatch, *, constants_recomputed_week=None):
    d = valid_profile_dict()
    # `computed_at` is a date; dump as ISO so load round-trips through YAML.
    d["meta"]["computed_at"] = d["meta"]["computed_at"].isoformat()
    if constants_recomputed_week is not None:
        d["meta"]["constants_recomputed_week"] = constants_recomputed_week
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("PROFILE_PATH", str(path))
    return path


@pytest.fixture
def profile_path(tmp_path, monkeypatch):
    """Write the valid §5 profile to a temp file and point the loader at it."""
    return _write_profile_yaml(tmp_path, monkeypatch)


def seed_strength_tests(session) -> None:
    """Seed a few weekly strength_tests rows (a rising push-up/pull-up trend)."""
    for i, week in enumerate(["2026-W19", "2026-W20", "2026-W21", "2026-W22"]):
        session.add(
            StrengthTests(
                date=f"2026-05-{10 + i:02d}",
                iso_week=week,
                max_pushups=40 + i,
                max_pullups=10 + i,
            )
        )
    session.flush()


def seed_window(session, anchor: date, *, days: int = 28) -> None:
    """Seed ``daily_metrics`` rows over the window ending on ``anchor`` (recovered)."""
    from datetime import timedelta

    for i in range(days):
        d = (anchor - timedelta(days=i)).isoformat()
        session.add(
            DailyMetrics(
                date=d,
                sleep_h=7.5,
                hrv_sdnn=45.0,
                rhr=55.0,
                hrv_30d_mean=44.0,
                hrv_30d_sd=4.0,
                rhr_30d_mean=56.0,
                z1_min=10.0,
                z2_min=20.0,
                active_energy=400.0,
                hard_day=0,
            )
        )
    session.flush()


def seed_prior_week_run(
    session, *, start: str, distance: float, unit: str = "km", origin: str = "sync"
) -> None:
    """Seed one prior-ISO-week running ``workouts`` row (for the §9 long-run ramp tests)."""
    session.add(
        Workouts(
            activity_type="running",
            total_distance=distance,
            total_distance_unit=unit,
            start_date=start,
            origin=origin,
        )
    )
    session.flush()


def _ctx(session, **nodes) -> TaskContext:
    ctx = TaskContext(
        event=WeeklyPlannerEvent(anchor=ANCHOR, iso_week=ISO_WEEK, week_start=WEEK_START),
        metadata={"session": session},
    )
    ctx.nodes.update(nodes)
    return ctx


def _clean_llm_output(quality_card: WorkoutCard = WorkoutCard.vo2) -> WeeklyPlanLLMOutput:
    """A within-budget weekly plan (2 hard days, 2 strength, spaced).

    ``quality_card`` is the single quality run (``vo2``/``threshold``) — on a due-recompute
    run the code-decided ``quality_run_pick`` (``next_quality_focus(None) → threshold``)
    must match, so the due-recompute tests pass ``threshold``.
    """
    dose = (30, 40) if quality_card is WorkoutCard.vo2 else (30, 50)
    return WeeklyPlanLLMOutput(
        core=[
            PlannedPick(card=WorkoutCard.boxing, suggested_day=Weekday.tue, duration_min_low=60, duration_min_high=90),
            PlannedPick(card=quality_card, suggested_day=Weekday.fri, duration_min_low=dose[0], duration_min_high=dose[1]),
            PlannedPick(card=WorkoutCard.strength_pull, suggested_day=Weekday.mon, duration_min_low=30, duration_min_high=45),
        ],
        extras=[
            PlannedPick(card=WorkoutCard.strength_push, suggested_day=Weekday.thu, duration_min_low=30, duration_min_high=45),
            PlannedPick(card=WorkoutCard.easy_run, suggested_day=Weekday.wed, duration_min_low=30, duration_min_high=40),
        ],
        narrative=[
            NarrativeSection(type=NarrativeType.plan, heading="h", body="b"),
        ],
    )


# --------------------------------------------------------------------------- #
# LoadAggregatesNode.
# --------------------------------------------------------------------------- #
def test_load_aggregates_node_reads_session_and_saves_aggregates(session, profile_path):
    seed_window(session, ANCHOR)
    ctx = _ctx(session)
    out_ctx = asyncio.run(LoadAggregatesNode(task_context=ctx).process(ctx))

    output = out_ctx.nodes["LoadAggregatesNode"]
    assert output.aggregates.anchor == ANCHOR
    assert output.aggregates.training_7d.n_days == 7
    assert output.aggregates.training_28d.n_days == 28


def test_load_aggregates_node_requires_session(profile_path):
    ctx = TaskContext(
        event=WeeklyPlannerEvent(anchor=ANCHOR, iso_week=ISO_WEEK, week_start=WEEK_START),
        metadata={},
    )
    with pytest.raises(ValueError, match="session"):
        asyncio.run(LoadAggregatesNode(task_context=ctx).process(ctx))


# --------------------------------------------------------------------------- #
# ComputeBudgetsNode.
# --------------------------------------------------------------------------- #
def test_compute_budgets_node_delegates_to_compute_budgets(session, profile_path):
    from app.services.aggregates import load_aggregates

    seed_window(session, ANCHOR)
    aggregates_out = LoadAggregatesNode.OutputType(aggregates=load_aggregates(session, ANCHOR))
    ctx = _ctx(session, LoadAggregatesNode=aggregates_out)
    out_ctx = asyncio.run(ComputeBudgetsNode(task_context=ctx).process(ctx))

    budgets = out_ctx.nodes["ComputeBudgetsNode"].budgets
    # Protected-at-2 strength, 2 hard days base (recovered → no deload on W23, idx 2).
    assert budgets.strength_sessions == 2
    assert budgets.deload is False
    assert budgets.hard_days in (2, 3)


# --------------------------------------------------------------------------- #
# TASK-002: prior-week long run feeds WeeklyBudgets.longRunKm (the §9 ramp cap).
# --------------------------------------------------------------------------- #
def test_long_run_km_populates_from_prior_week_run_normal_week(session, profile_path):
    # A 10 km running workout in the prior ISO week (W22, [2026-05-25, 2026-06-01)) → the
    # §9 ≤110% ramp, floor-rounded: floor(10.0 * 1.10 * 10) / 10 = 11.0. W23 (idx 2) is not
    # a deload, and a recovered window keeps it that way.
    seed_window(session, ANCHOR)
    seed_prior_week_run(session, start="2026-05-27T08:00:00+03:00", distance=10.0)
    ctx = _ctx(session)
    asyncio.run(LoadAggregatesNode(task_context=ctx).process(ctx))

    aggregates = ctx.nodes["LoadAggregatesNode"].aggregates
    assert aggregates.prior_week_long_run_km == pytest.approx(10.0)
    # The value rides into the serialized inputs_snapshot via aggregates.to_dict().
    assert aggregates.to_dict()["prior_week_long_run_km"] == pytest.approx(10.0)

    asyncio.run(ComputeBudgetsNode(task_context=ctx).process(ctx))
    budgets = ctx.nodes["ComputeBudgetsNode"].budgets
    assert budgets.deload is False
    assert budgets.long_run_km == pytest.approx(11.0)


def test_long_run_km_deload_down_ramp(session, profile_path):
    # W24 (0-based index 3) is a cadence-deload week, so the long run ramps DOWN ~40%:
    # floor(10.0 * 0.60 * 10) / 10 = 6.0, and hard days drop to 1. Prior week is W23
    # ([2026-06-01, 2026-06-08)).
    event = WeeklyPlannerEvent(
        anchor=date(2026, 6, 14), iso_week="2026-W24", week_start=date(2026, 6, 8)
    )
    ctx = TaskContext(event=event, metadata={"session": session})
    seed_prior_week_run(session, start="2026-06-03T08:00:00+03:00", distance=10.0)
    asyncio.run(LoadAggregatesNode(task_context=ctx).process(ctx))
    asyncio.run(ComputeBudgetsNode(task_context=ctx).process(ctx))

    budgets = ctx.nodes["ComputeBudgetsNode"].budgets
    assert budgets.deload is True
    assert budgets.long_run_km == pytest.approx(6.0)
    assert budgets.hard_days == 1


def test_long_run_km_none_without_prior_week_history(session, profile_path):
    # No prior-week running workout → longRunKm is None (week-one unconstrained).
    seed_window(session, ANCHOR)
    ctx = _ctx(session)
    asyncio.run(LoadAggregatesNode(task_context=ctx).process(ctx))
    asyncio.run(ComputeBudgetsNode(task_context=ctx).process(ctx))

    assert ctx.nodes["LoadAggregatesNode"].aggregates.prior_week_long_run_km is None
    assert ctx.nodes["ComputeBudgetsNode"].budgets.long_run_km is None


# --------------------------------------------------------------------------- #
# DeriveSessionsNode.
# --------------------------------------------------------------------------- #
def test_derive_sessions_node_expands_picks_with_card_fields(session, profile_path):
    ctx = _ctx(session, GeneratePlanNode=_clean_llm_output())
    out_ctx = asyncio.run(DeriveSessionsNode(task_context=ctx).process(ctx))

    output = out_ctx.nodes["DeriveSessionsNode"]
    assert [s.card for s in output.core] == [
        WorkoutCard.boxing,
        WorkoutCard.vo2,
        WorkoutCard.strength_pull,
    ]
    vo2 = output.core[1]
    # Card-derived fields come from CARD_META (vo2 is a hard, z5, quality card).
    assert vo2.is_hard_day is True
    assert vo2.zone_target.value == "z5"
    assert vo2.intensity.value == "quality"
    assert "quality_day" in vo2.flags
    # tier implied by array membership.
    assert all(s.tier.value == "core" for s in output.core)
    assert all(s.tier.value == "extra" for s in output.extras)
    # The dose is copied verbatim from the LLM pick.
    assert vo2.duration_min_low == 30 and vo2.duration_min_high == 40


# --------------------------------------------------------------------------- #
# ComputeTargetsNode.
# --------------------------------------------------------------------------- #
def test_compute_targets_node_delegates_to_compute_targets(session, profile_path):
    ctx = _ctx(session, GeneratePlanNode=_clean_llm_output())
    asyncio.run(DeriveSessionsNode(task_context=ctx).process(ctx))
    out_ctx = asyncio.run(ComputeTargetsNode(task_context=ctx).process(ctx))

    targets = out_ctx.nodes["ComputeTargetsNode"].targets
    assert targets.strength_sessions == 2
    assert targets.hard_days == 2  # boxing + vo2
    assert targets.cadence_spm == load_profile().thresholds.cadence_current_spm


# --------------------------------------------------------------------------- #
# ComputeNutritionNode.
# --------------------------------------------------------------------------- #
def test_compute_nutrition_node_maps_day_type_and_delegates(session, profile_path):
    seed_window(session, ANCHOR)
    from app.services.aggregates import load_aggregates

    aggregates_out = LoadAggregatesNode.OutputType(aggregates=load_aggregates(session, ANCHOR))
    ctx = _ctx(session, LoadAggregatesNode=aggregates_out, GeneratePlanNode=_clean_llm_output())
    asyncio.run(DeriveSessionsNode(task_context=ctx).process(ctx))
    out_ctx = asyncio.run(ComputeNutritionNode(task_context=ctx).process(ctx))

    nutrition = out_ctx.nodes["ComputeNutritionNode"].nutrition
    # One dayTypePattern entry per planned session (3 core + 2 extras = 5).
    assert len(nutrition.day_type_pattern) == 5
    # boxing → day_type hard (CARD_META), easy_run → moderate.
    by_day = {e.suggested_day: e.day_type.value for e in nutrition.day_type_pattern}
    assert by_day["tue"] == "hard"  # boxing
    assert by_day["wed"] == "moderate"  # easy_run
    assert nutrition.protein_g > 0


def test_compute_nutrition_node_last_week_null_and_object(session, profile_path):
    """E13·P1/P2: a no-intake window emits `lastWeek: null`; a logged-intake window emits the
    camelCase scorecard with averages rounded and — once E13·P2 injects the per-day target —
    the three vs-target counts populated."""
    from datetime import timedelta

    from app.core.profile import load_profile
    from app.services.aggregates import load_aggregates, nutrition_adherence
    from app.services.macros import per_day_nutrition_target

    # (a) No dietary intake in the 7d window → lastWeek is null (the empty state).
    seed_window(session, ANCHOR)  # training rows only, no kcal_in/protein_in_g logged
    ctx = _ctx(
        session,
        LoadAggregatesNode=LoadAggregatesNode.OutputType(aggregates=load_aggregates(session, ANCHOR)),
        GeneratePlanNode=_clean_llm_output(),
    )
    asyncio.run(DeriveSessionsNode(task_context=ctx).process(ctx))
    out_ctx = asyncio.run(ComputeNutritionNode(task_context=ctx).process(ctx))
    nutrition = out_ctx.nodes["ComputeNutritionNode"].nutrition
    assert nutrition.last_week is None
    assert nutrition.model_dump(mode="json")["lastWeek"] is None

    # (b) A non-overlapping window WITH logged intake + the per-day target injected (as the
    #     node now does) → camelCase object, averages rounded, vs-target counts populated.
    profile = load_profile()
    target = per_day_nutrition_target(
        weight_kg=profile.athlete.goal_weight_kg,
        nutrition=profile.nutrition,
        athlete=profile.athlete,
    )
    logged_anchor = ANCHOR - timedelta(days=40)
    for offset, (kcal, protein) in enumerate([(2600.0, 150.0), (2610.0, 138.5)]):
        session.add(
            DailyMetrics(
                date=(logged_anchor - timedelta(days=offset)).isoformat(),
                kcal_in=kcal,
                protein_in_g=protein,
            )
        )
    session.flush()
    ctx2 = _ctx(
        session,
        LoadAggregatesNode=LoadAggregatesNode.OutputType(
            aggregates=load_aggregates(session, logged_anchor, nutrition_target_7d=target)
        ),
        GeneratePlanNode=_clean_llm_output(),
    )
    asyncio.run(DeriveSessionsNode(task_context=ctx2).process(ctx2))
    out_ctx2 = asyncio.run(ComputeNutritionNode(task_context=ctx2).process(ctx2))
    last_week = out_ctx2.nodes["ComputeNutritionNode"].nutrition.model_dump(mode="json")["lastWeek"]
    assert set(last_week) == {
        "avgCaloriesKcal", "avgProteinG", "proteinHitDays", "daysOverTarget", "daysUnderTarget",
    }
    assert last_week["avgCaloriesKcal"] == 2605  # (2600 + 2610) / 2
    assert last_week["avgProteinG"] == 144  # (150 + 138.5) / 2 = 144.25 → floor(144.75)
    # The three counts now populate (E13·P2) and match the adherence with the same target.
    expected = nutrition_adherence(session, logged_anchor, 7, target=target)
    assert last_week["proteinHitDays"] == expected.protein_hit_days
    assert last_week["daysOverTarget"] == expected.days_over_target
    assert last_week["daysUnderTarget"] == expected.days_under_target
    assert last_week["proteinHitDays"] is not None  # non-null with target + logged protein
    assert 0 <= last_week["daysOverTarget"] <= 2  # bounded by the 2 logged days
    assert 0 <= last_week["daysUnderTarget"] <= 2


def test_load_aggregates_node_injects_target_counts_populate(session, profile_path):
    """E13·P2: the real LoadAggregatesNode builds a per-day target from the profile and injects
    it as nutrition_target_7d, so the lastWeek vs-target counts populate; the 28d window stays
    target-less."""
    from datetime import timedelta

    from app.core.profile import load_profile
    from app.services.aggregates import nutrition_adherence
    from app.services.macros import per_day_nutrition_target

    # 3 logged-intake days in the 7d window ending at ANCHOR.
    for offset in range(3):
        session.add(
            DailyMetrics(
                date=(ANCHOR - timedelta(days=offset)).isoformat(),
                kcal_in=2200.0,
                protein_in_g=160.0,
            )
        )
    session.flush()

    ctx = _ctx(session, GeneratePlanNode=_clean_llm_output())
    # The real node — it builds the per-day target from load_profile() and injects it.
    asyncio.run(LoadAggregatesNode(task_context=ctx).process(ctx))
    asyncio.run(DeriveSessionsNode(task_context=ctx).process(ctx))
    out_ctx = asyncio.run(ComputeNutritionNode(task_context=ctx).process(ctx))

    last_week = out_ctx.nodes["ComputeNutritionNode"].nutrition.last_week
    assert last_week is not None
    assert last_week.protein_hit_days is not None
    assert last_week.days_over_target is not None
    assert last_week.days_under_target is not None

    # The counts match the adherence computed with the same per-day target the node built.
    profile = load_profile()
    target = per_day_nutrition_target(
        weight_kg=profile.athlete.goal_weight_kg,
        nutrition=profile.nutrition,
        athlete=profile.athlete,
    )
    expected = nutrition_adherence(session, ANCHOR, 7, target=target)
    assert last_week.protein_hit_days == expected.protein_hit_days
    assert last_week.days_over_target == expected.days_over_target
    assert last_week.days_under_target == expected.days_under_target
    assert 0 <= last_week.protein_hit_days <= 3  # bounded by the 3 logged days

    # The 28d window stays target-less — its comparison fields remain None.
    aggregates = out_ctx.nodes["LoadAggregatesNode"].aggregates
    assert aggregates.nutrition_28d.protein_hit_days is None
    assert aggregates.nutrition_28d.days_over_target is None
    assert aggregates.nutrition_28d.days_under_target is None
    assert aggregates.nutrition_28d.kcal_pct is None


def test_load_aggregates_node_no_intake_still_null(session, profile_path):
    """E13·P2: injecting the target never fabricates a scorecard — a training-only window with
    no logged intake still yields lastWeek: null."""
    seed_window(session, ANCHOR)  # training rows only, no dietary logged
    ctx = _ctx(session, GeneratePlanNode=_clean_llm_output())
    asyncio.run(LoadAggregatesNode(task_context=ctx).process(ctx))
    asyncio.run(DeriveSessionsNode(task_context=ctx).process(ctx))
    out_ctx = asyncio.run(ComputeNutritionNode(task_context=ctx).process(ctx))
    assert out_ctx.nodes["ComputeNutritionNode"].nutrition.last_week is None


# --------------------------------------------------------------------------- #
# E13·P3: weekly nutrition + adherence target track the live body weight.
# --------------------------------------------------------------------------- #
def test_compute_nutrition_node_tracks_live_weight(session, profile_path):
    """E13·P3: with a materialised body_weight ≠ goal_weight_kg, the displayed macros track the
    live weight (not goal_weight_kg)."""
    from app.core.profile import load_profile
    from app.services.macros import compute_weekly_nutrition

    profile = load_profile()
    goal = profile.athlete.goal_weight_kg
    live = goal + 6.0  # distinct from goal → macros must differ
    session.add(DailyMetrics(date=ANCHOR.isoformat(), body_weight=live))
    session.flush()

    ctx = _ctx(session, GeneratePlanNode=_clean_llm_output())
    asyncio.run(LoadAggregatesNode(task_context=ctx).process(ctx))
    asyncio.run(DeriveSessionsNode(task_context=ctx).process(ctx))
    out_ctx = asyncio.run(ComputeNutritionNode(task_context=ctx).process(ctx))
    nutrition = out_ctx.nodes["ComputeNutritionNode"].nutrition

    # proteinG / avgCaloriesKcal (picks-independent) track the LIVE weight, not goal_weight_kg.
    def _scalars(weight: float) -> tuple[int, int]:
        wn = compute_weekly_nutrition(
            picks=[], weight_kg=weight, nutrition=profile.nutrition, athlete=profile.athlete
        )
        return wn.protein_g, wn.avg_calories_kcal

    live_protein, live_avg = _scalars(live)
    goal_protein, goal_avg = _scalars(goal)
    assert (nutrition.protein_g, nutrition.avg_calories_kcal) == (live_protein, live_avg)
    assert (live_protein, live_avg) != (goal_protein, goal_avg)  # the basis really changed


def test_adherence_target_uses_live_weight(session, profile_path):
    """E13·P3: the LoadAggregatesNode adherence target is built on the same live weight, so it
    equals the displayed live-weight target (lock-step)."""
    from app.core.profile import load_profile
    from app.services.macros import per_day_nutrition_target

    profile = load_profile()
    live = profile.athlete.goal_weight_kg + 6.0
    session.add(DailyMetrics(date=ANCHOR.isoformat(), body_weight=live))
    session.flush()

    ctx = _ctx(session, GeneratePlanNode=_clean_llm_output())
    asyncio.run(LoadAggregatesNode(task_context=ctx).process(ctx))
    target = ctx.nodes["LoadAggregatesNode"].aggregates.nutrition_7d.target
    expected = per_day_nutrition_target(
        weight_kg=live, nutrition=profile.nutrition, athlete=profile.athlete
    )
    assert target is not None
    assert target.kcal == expected.kcal
    assert target.protein_g == expected.protein_g


def test_nutrition_falls_back_to_goal_weight_when_no_history(session, profile_path, caplog):
    """E13·P3: with no scale history, the macros fall back to goal_weight_kg, a note is logged
    once, and the brief still succeeds (numbers identical to the goal-weight output)."""
    import logging

    from app.core.profile import load_profile
    from app.services.macros import protein_g

    profile = load_profile()
    seed_window(session, ANCHOR)  # rows present, but no body_weight seeded → fallback

    ctx = _ctx(session, GeneratePlanNode=_clean_llm_output())
    asyncio.run(LoadAggregatesNode(task_context=ctx).process(ctx))
    asyncio.run(DeriveSessionsNode(task_context=ctx).process(ctx))
    with caplog.at_level(logging.WARNING, logger="app.core.weekly_planner"):
        out_ctx = asyncio.run(ComputeNutritionNode(task_context=ctx).process(ctx))
    nutrition = out_ctx.nodes["ComputeNutritionNode"].nutrition

    assert nutrition.protein_g == protein_g(
        profile.athlete.goal_weight_kg, profile.nutrition.protein_g_per_kg
    )
    # The fallback note is logged (once) at the display node.
    fallback_notes = [r for r in caplog.records if "goal_weight_kg" in r.getMessage()]
    assert len(fallback_notes) == 1


# --------------------------------------------------------------------------- #
# TASK-002: is_recompute_due (the monthly gate) + RecomputeConstants branches.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("last_week", "current_week", "due"),
    [
        (None, "2026-W23", True),  # never recomputed → due
        ("2026-W22", "2026-W23", False),  # distance 1 → not due
        ("2026-W21", "2026-W23", False),  # distance 2 → not due
        ("2026-W20", "2026-W23", False),  # distance 3 → not due
        ("2026-W19", "2026-W23", True),  # distance 4 → due
        ("2025-W52", "2026-W04", True),  # year boundary: distance 4 → due
        ("2025-W52", "2026-W02", False),  # year boundary: distance 2 → not due
        ("2026-W23", "2026-W23", False),  # same week (?refresh replay) → not due
    ],
)
def test_is_recompute_due_is_monthly(last_week, current_week, due):
    assert is_recompute_due(last_week, current_week) is due


def test_recompute_constants_not_due_branch(session, tmp_path, monkeypatch):
    # Last recompute one week ago → not due: no helper called, no proposed write.
    _write_profile_yaml(tmp_path, monkeypatch, constants_recomputed_week="2026-W22")
    seed_strength_tests(session)

    import app.core.weekly_planner as wp

    called = []
    for name in ("ramp_cadence_for", "next_quality_focus", "smooth_strength_trend", "rederive_zones"):
        monkeypatch.setattr(wp, name, lambda *a, _n=name, **k: pytest.fail(f"{_n} called when not due"))
    monkeypatch.setattr(
        __import__("app.core.profile", fromlist=["write_profile"]),
        "write_profile",
        lambda *a, **k: called.append("write"),
    )

    ctx = _ctx(session)
    out_ctx = asyncio.run(RecomputeConstants(task_context=ctx).process(ctx))
    output = out_ctx.nodes["RecomputeConstants"]
    assert output.constants_recomputed is False
    assert output.profile is not None  # unchanged profile stored for downstream nodes
    assert output.recomputed is None
    assert called == []  # no file write proposed


def test_recompute_constants_due_branch_runs_helpers_in_memory(session, tmp_path, monkeypatch):
    # Distance 4 → due: each E8·P5 helper runs (spied), a proposed validated Profile is
    # stored with the new stamp, and NO file write happens in this node.
    _write_profile_yaml(tmp_path, monkeypatch, constants_recomputed_week="2026-W19")
    seed_strength_tests(session)

    import app.core.weekly_planner as wp

    spied = {"ramp_cadence_for": 0, "next_quality_focus": 0, "smooth_strength_trend": 0, "rederive_zones": 0}
    for name in spied:
        real = getattr(wp, name)

        def _spy(*a, _n=name, _real=real, **k):
            spied[_n] += 1
            return _real(*a, **k)

        monkeypatch.setattr(wp, name, _spy)

    # write_profile must NOT be imported/called by RecomputeConstants.
    monkeypatch.setattr(
        __import__("app.core.profile", fromlist=["write_profile"]),
        "write_profile",
        lambda *a, **k: pytest.fail("RecomputeConstants must not write profile.yaml"),
    )

    ctx = _ctx(session)
    out_ctx = asyncio.run(RecomputeConstants(task_context=ctx).process(ctx))
    output = out_ctx.nodes["RecomputeConstants"]

    assert output.constants_recomputed is True
    assert output.profile is not None
    assert output.profile.meta.constants_recomputed_week == ISO_WEEK
    assert output.recomputed is not None and "quality_focus" in output.recomputed
    assert spied["ramp_cadence_for"] == 1
    assert spied["next_quality_focus"] == 1
    assert spied["smooth_strength_trend"] == 2  # once per metric (pushups + pullups)
    assert spied["rederive_zones"] == 1


def test_recompute_constants_due_merge_re_validates_pydantic(session, tmp_path, monkeypatch):
    # An invalid helper output (cadence_current > cadence_target) must make the merge RAISE
    # — Profile.model_validate re-runs the E3·P1 validators (NOT model_copy(update=…)).
    _write_profile_yaml(tmp_path, monkeypatch, constants_recomputed_week="2026-W19")
    seed_strength_tests(session)

    import app.core.weekly_planner as wp
    from app.services.recompute import CadenceRamp

    # Force cadence above the target (172) — an invalid Thresholds combination.
    monkeypatch.setattr(wp, "ramp_cadence_for", lambda *a, **k: CadenceRamp(new_spm=200, bumped=True))

    ctx = _ctx(session)
    with pytest.raises(Exception):  # pydantic.ValidationError from the re-validate
        asyncio.run(RecomputeConstants(task_context=ctx).process(ctx))
    assert "RecomputeConstants" not in ctx.nodes  # nothing stored for PersistPlanNode


def test_recompute_no_model_copy_update_in_source():
    # The merge must use model_validate, never model_copy(update=…) (skips validation).
    import pathlib

    src = pathlib.Path("app/core/weekly_planner.py").read_text(encoding="utf-8")
    assert "model_copy(update" not in src


def test_recompute_constants_output_is_constructible():
    # A bare not-due output and a full due output both construct.
    assert RecomputeConstantsOutput(constants_recomputed=False).constants_recomputed is False


# --------------------------------------------------------------------------- #
# TASK-003: ValidatePlanNode (belt-and-suspenders) + PersistPlanNode.
# --------------------------------------------------------------------------- #
def _budgets_output(*, hard_days=2, strength=2, deload=False):
    return ComputeBudgetsNode.OutputType(
        budgets=WeeklyBudgets(
            hard_days=hard_days, strength_sessions=strength, long_run_km=11.0, deload=deload
        )
    )


def _breaking_llm_output() -> WeeklyPlanLLMOutput:
    """A budget-breaking plan: 4 hard cards on adjacent days, wrong strength count."""
    return WeeklyPlanLLMOutput(
        core=[
            PlannedPick(card=WorkoutCard.vo2, suggested_day=Weekday.mon, duration_min_low=30, duration_min_high=40),
            PlannedPick(card=WorkoutCard.threshold, suggested_day=Weekday.tue, duration_min_low=30, duration_min_high=50),
            PlannedPick(card=WorkoutCard.boxing, suggested_day=Weekday.wed, duration_min_low=60, duration_min_high=90),
        ],
        extras=[
            PlannedPick(card=WorkoutCard.hiit, suggested_day=Weekday.thu, duration_min_low=15, duration_min_high=25),
        ],
        narrative=[NarrativeSection(type=NarrativeType.plan, heading="h", body="b")],
    )


def test_validate_plan_node_raises_on_hard_violation(session, profile_path):
    ctx = _ctx(
        session,
        ComputeBudgetsNode=_budgets_output(),
        GeneratePlanNode=_breaking_llm_output(),
    )
    with pytest.raises(BriefGenerationError) as exc:
        asyncio.run(ValidatePlanNode(task_context=ctx).process(ctx))
    assert exc.value.code == "brief_generation_failed"


def test_validate_plan_node_passes_clean_plan(session, profile_path):
    ctx = _ctx(
        session,
        ComputeBudgetsNode=_budgets_output(),
        GeneratePlanNode=_clean_llm_output(),
    )
    # No raise — returns the context.
    out_ctx = asyncio.run(ValidatePlanNode(task_context=ctx).process(ctx))
    assert out_ctx is ctx


def _seed_full_ctx_for_persist(session, *, recompute_output=None):
    """Build a ctx with every upstream output populated, ready for PersistPlanNode."""
    from app.services.aggregates import load_aggregates

    seed_window(session, ANCHOR)
    nodes = {
        "LoadAggregatesNode": LoadAggregatesNode.OutputType(aggregates=load_aggregates(session, ANCHOR)),
        "ComputeBudgetsNode": _budgets_output(),
        "GeneratePlanNode": _clean_llm_output(),
    }
    if recompute_output is not None:
        nodes["RecomputeConstants"] = recompute_output
    ctx = _ctx(session, **nodes)
    asyncio.run(DeriveSessionsNode(task_context=ctx).process(ctx))
    asyncio.run(ComputeTargetsNode(task_context=ctx).process(ctx))
    asyncio.run(ComputeNutritionNode(task_context=ctx).process(ctx))
    return ctx


def test_persist_plan_node_writes_one_row_with_all_columns(session, profile_path):
    ctx = _seed_full_ctx_for_persist(session)
    asyncio.run(PersistPlanNode(task_context=ctx).process(ctx))

    rows = session.execute(select(Plans)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.iso_week == ISO_WEEK
    assert row.payload and row.rationale and row.inputs_snapshot
    assert row.model and row.constitution_version == "v1" and row.created_at

    payload = json.loads(row.payload)
    assert payload["isoWeek"] == ISO_WEEK
    assert payload["weekStart"] == WEEK_START.isoformat()
    assert "budgets" in payload and "targets" in payload and "nutrition" in payload
    assert len(payload["core"]) == 3 and len(payload["extras"]) == 2
    assert payload["constantsRecomputed"] is False


def test_persist_inputs_snapshot_carries_aggregates_and_constants(session, profile_path):
    ctx = _seed_full_ctx_for_persist(session)
    asyncio.run(PersistPlanNode(task_context=ctx).process(ctx))
    row = session.execute(select(Plans)).scalars().one()
    snapshot = json.loads(row.inputs_snapshot)
    assert set(snapshot) == {"aggregates", "constants"}
    assert snapshot["aggregates"]["anchor"] == ANCHOR.isoformat()


def test_persist_does_not_commit_or_lookup(session, profile_path, monkeypatch):
    # The node must not commit (the endpoint owns the txn). Patch commit to fail-if-called.
    monkeypatch.setattr(session, "commit", lambda *a, **k: pytest.fail("PersistPlanNode committed"))
    ctx = _seed_full_ctx_for_persist(session)
    asyncio.run(PersistPlanNode(task_context=ctx).process(ctx))
    # The row exists in this session (uncommitted), and save_output carried the data.
    assert session.execute(select(Plans)).scalars().all()
    data = ctx.nodes["PersistPlanNode"].data
    assert data["isoWeek"] == ISO_WEEK and "targets" in data


def test_persist_writes_row_then_stages_profile_on_due_recompute(session, tmp_path, monkeypatch):
    # A due-recompute ctx: PersistPlanNode stages the row THEN STAGES the proposed
    # profile.yaml write (it does NOT write the file — the endpoint applies it post-commit
    # so a commit-only failure never advances the file for a rolled-back plan; review).
    from app.core.weekly_planner import PENDING_PROFILE_WRITE_KEY

    path = _write_profile_yaml(tmp_path, monkeypatch, constants_recomputed_week="2026-W19")
    seed_strength_tests(session)
    ctx = _ctx(session)
    asyncio.run(RecomputeConstants(task_context=ctx).process(ctx))
    recompute_out = ctx.nodes["RecomputeConstants"]
    assert recompute_out.constants_recomputed is True

    before = path.read_text(encoding="utf-8")
    full_ctx = _seed_full_ctx_for_persist(session, recompute_output=recompute_out)
    asyncio.run(PersistPlanNode(task_context=full_ctx).process(full_ctx))

    # Row staged; the proposed profile write is STAGED (not applied) and the file is untouched.
    assert session.execute(select(Plans)).scalars().all()
    staged = full_ctx.metadata.get(PENDING_PROFILE_WRITE_KEY)
    assert staged is not None and staged.meta.constants_recomputed_week == ISO_WEEK
    assert path.read_text(encoding="utf-8") == before  # node does NOT write the file


def test_persist_does_not_stage_profile_when_not_due(session, profile_path, monkeypatch):
    # A not-due ctx (no RecomputeConstants proposing constants): nothing staged for write.
    from app.core.weekly_planner import PENDING_PROFILE_WRITE_KEY

    ctx = _seed_full_ctx_for_persist(
        session,
        recompute_output=RecomputeConstantsOutput(constants_recomputed=False),
    )
    asyncio.run(PersistPlanNode(task_context=ctx).process(ctx))
    assert session.execute(select(Plans)).scalars().all()
    assert PENDING_PROFILE_WRITE_KEY not in ctx.metadata


# --------------------------------------------------------------------------- #
# TASK-004: the assembled WeeklyPlanner workflow (node order + end-to-end).
# --------------------------------------------------------------------------- #
_EXPECTED_ORDER = [
    "LoadAggregatesNode",
    "RecomputeConstants",
    "ComputeBudgetsNode",
    "GeneratePlanNode",
    "DeriveSessionsNode",
    "ComputeTargetsNode",
    "ComputeNutritionNode",
    "ValidatePlanNode",
    "PersistPlanNode",
]


def test_node_order_is_exactly_architecture_section_5():
    schema = WeeklyPlanner.workflow_schema
    assert schema.start.__name__ == "LoadAggregatesNode"
    names = [nc.node.__name__ for nc in schema.nodes]
    assert names == _EXPECTED_ORDER
    # Each edge points to its successor; the last is terminal.
    for nc, expected_next in zip(schema.nodes, _EXPECTED_ORDER[1:] + [None]):
        targets = [c.__name__ for c in nc.connections]
        assert targets == ([expected_next] if expected_next else [])


def test_weekly_planner_constructs_without_error():
    # The E1·P3 WorkflowValidator accepts the linear chain (unique/declared/cycle-free).
    assert WeeklyPlanner() is not None


def test_no_router_on_the_weekly_path():
    schema = WeeklyPlanner.workflow_schema
    assert not any(nc.is_router for nc in schema.nodes)


def _mock_generate_plan(monkeypatch, llm_output: WeeklyPlanLLMOutput) -> None:
    """Substitute the AgentNode's process with a stand-in (no LLM/network/key)."""

    async def _stand_in(self, task_context):
        self.save_output(llm_output)
        return task_context

    monkeypatch.setattr(GeneratePlanNode, "process", _stand_in, raising=True)


def test_end_to_end_happy_path_via_run_async_context(session, tmp_path, monkeypatch):
    # A not-due week (recompute False) — the full deterministic graph runs end-to-end.
    _write_profile_yaml(tmp_path, monkeypatch, constants_recomputed_week="2026-W22")
    seed_window(session, ANCHOR)
    _mock_generate_plan(monkeypatch, _clean_llm_output())

    ctx = TaskContext(
        event=WeeklyPlannerEvent(anchor=ANCHOR, iso_week=ISO_WEEK, week_start=WEEK_START),
        metadata={"session": session},
    )
    out_ctx = asyncio.run(WeeklyPlanner().run_async(context=ctx))

    # Every node's output is present.
    for name in _EXPECTED_ORDER:
        assert name in out_ctx.nodes, f"{name} output missing"
    # core/extras are code-expanded PlannedSession[] (card-derived fields filled).
    derived = out_ctx.nodes["DeriveSessionsNode"]
    assert derived.core[1].card == WorkoutCard.vo2
    assert derived.core[1].zone_target.value == "z5"  # from CARD_META
    assert out_ctx.nodes["ComputeBudgetsNode"].budgets.strength_sessions == 2
    assert out_ctx.nodes["ComputeTargetsNode"].targets.hard_days == 2
    assert len(out_ctx.nodes["ComputeNutritionNode"].nutrition.day_type_pattern) == 5
    # Exactly one Plans row with the key columns set.
    rows = session.execute(select(Plans)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.payload and row.inputs_snapshot and row.model and row.constitution_version


def test_monthly_recompute_branch_due_stages_profile_write(session, tmp_path, monkeypatch):
    from app.core.weekly_planner import PENDING_PROFILE_WRITE_KEY

    path = _write_profile_yaml(tmp_path, monkeypatch, constants_recomputed_week="2026-W19")
    seed_window(session, ANCHOR)
    seed_strength_tests(session)
    # On a due recompute next_quality_focus(None) → THRESHOLD; the plan must match it.
    _mock_generate_plan(monkeypatch, _clean_llm_output(quality_card=WorkoutCard.threshold))
    before = path.read_text(encoding="utf-8")

    ctx = TaskContext(
        event=WeeklyPlannerEvent(anchor=ANCHOR, iso_week=ISO_WEEK, week_start=WEEK_START),
        metadata={"session": session},
    )
    out_ctx = asyncio.run(WeeklyPlanner().run_async(context=ctx))

    assert out_ctx.nodes["RecomputeConstants"].constants_recomputed is True
    row = session.execute(select(Plans)).scalars().one()
    assert json.loads(row.payload)["constantsRecomputed"] is True
    # The profile write is STAGED with the merged stamp; the file is NOT advanced by the
    # workflow — the endpoint (E10·P3) applies it only after a successful commit (review).
    staged = out_ctx.metadata.get(PENDING_PROFILE_WRITE_KEY)
    assert staged is not None and staged.meta.constants_recomputed_week == ISO_WEEK
    assert path.read_text(encoding="utf-8") == before


def test_monthly_recompute_branch_adjacent_week_no_write(session, tmp_path, monkeypatch):
    path = _write_profile_yaml(tmp_path, monkeypatch, constants_recomputed_week="2026-W22")
    seed_window(session, ANCHOR)
    _mock_generate_plan(monkeypatch, _clean_llm_output())
    before = path.read_text(encoding="utf-8")

    ctx = TaskContext(
        event=WeeklyPlannerEvent(anchor=ANCHOR, iso_week=ISO_WEEK, week_start=WEEK_START),
        metadata={"session": session},
    )
    out_ctx = asyncio.run(WeeklyPlanner().run_async(context=ctx))

    assert out_ctx.nodes["RecomputeConstants"].constants_recomputed is False
    assert json.loads(session.execute(select(Plans)).scalars().one().payload)["constantsRecomputed"] is False
    assert path.read_text(encoding="utf-8") == before  # no file write on an adjacent week


def test_failed_brief_never_advances_profile_or_writes_row(session, tmp_path, monkeypatch):
    # A due-recompute event whose agent RAISES: profile.yaml unchanged, no Plans row.
    path = _write_profile_yaml(tmp_path, monkeypatch, constants_recomputed_week="2026-W19")
    seed_window(session, ANCHOR)
    seed_strength_tests(session)
    before = path.read_text(encoding="utf-8")

    async def _boom(self, task_context):
        raise BriefGenerationError(code="upstream_timeout")

    monkeypatch.setattr(GeneratePlanNode, "process", _boom, raising=True)

    ctx = TaskContext(
        event=WeeklyPlannerEvent(anchor=ANCHOR, iso_week=ISO_WEEK, week_start=WEEK_START),
        metadata={"session": session},
    )
    with pytest.raises(BriefGenerationError):
        asyncio.run(WeeklyPlanner().run_async(context=ctx))

    assert path.read_text(encoding="utf-8") == before  # never advanced
    assert not session.execute(select(Plans)).scalars().all()  # no row
    # The next run still sees the week as due (the stamp never advanced).
    assert load_profile(path).meta.constants_recomputed_week == "2026-W19"


def test_constraint_breaking_plan_never_reaches_the_cache(session, profile_path, monkeypatch):
    seed_window(session, ANCHOR)
    _mock_generate_plan(monkeypatch, _breaking_llm_output())

    ctx = TaskContext(
        event=WeeklyPlannerEvent(anchor=ANCHOR, iso_week=ISO_WEEK, week_start=WEEK_START),
        metadata={"session": session},
    )
    with pytest.raises(BriefGenerationError) as exc:
        asyncio.run(WeeklyPlanner().run_async(context=ctx))
    assert exc.value.code == "brief_generation_failed"
    assert not session.execute(select(Plans)).scalars().all()  # no row written
