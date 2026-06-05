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
from datetime import date

import pytest
import yaml

from app.api.schemas.weekly import NarrativeSection, PlannedPick, WeeklyPlanLLMOutput
from app.core.enums import NarrativeType, Weekday, WorkoutCard
from app.core.profile import load_profile
from app.core.task_context import TaskContext
from app.core.weekly_planner import (
    ComputeBudgetsNode,
    ComputeNutritionNode,
    ComputeTargetsNode,
    DeriveSessionsNode,
    LoadAggregatesNode,
    WeeklyPlannerEvent,
)
from app.database.models import DailyMetrics

from tests.core.test_profile import valid_profile_dict

ANCHOR = date(2026, 6, 7)  # a Sunday — end of 2026-W23
ISO_WEEK = "2026-W23"
WEEK_START = date(2026, 6, 1)


# --------------------------------------------------------------------------- #
# Fixtures: a temp profile.yaml + a seeded daily_metrics window.
# --------------------------------------------------------------------------- #
@pytest.fixture
def profile_path(tmp_path, monkeypatch):
    """Write the valid §5 profile to a temp file and point the loader at it."""
    d = valid_profile_dict()
    # `computed_at` is a date; dump as ISO so load round-trips through YAML.
    d["meta"]["computed_at"] = d["meta"]["computed_at"].isoformat()
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("PROFILE_PATH", str(path))
    return path


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


def _ctx(session, **nodes) -> TaskContext:
    ctx = TaskContext(
        event=WeeklyPlannerEvent(anchor=ANCHOR, iso_week=ISO_WEEK, week_start=WEEK_START),
        metadata={"session": session},
    )
    ctx.nodes.update(nodes)
    return ctx


def _clean_llm_output() -> WeeklyPlanLLMOutput:
    """A within-budget weekly plan (2 hard days, 2 strength, spaced)."""
    return WeeklyPlanLLMOutput(
        core=[
            PlannedPick(card=WorkoutCard.boxing, suggested_day=Weekday.tue, duration_min_low=60, duration_min_high=90),
            PlannedPick(card=WorkoutCard.vo2, suggested_day=Weekday.fri, duration_min_low=30, duration_min_high=40),
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
