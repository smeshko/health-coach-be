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
    RecomputeConstants,
    RecomputeConstantsOutput,
    WeeklyPlannerEvent,
    is_recompute_due,
)
from app.database.models import DailyMetrics, StrengthTests

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
