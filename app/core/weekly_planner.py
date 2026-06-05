"""The ``WEEKLY_PLANNER`` workflow — the deterministic weekly-brain skeleton (E10·P2).

ARCHITECTURE §5 fixes the weekly graph as a strictly **linear** 9-node chain (no
router — that is ``DAILY_ADJUSTER``'s ``SafetyGateRouter``):

    LoadAggregatesNode → RecomputeConstants → ComputeBudgetsNode → GeneratePlanNode
    → DeriveSessionsNode → ComputeTargetsNode → ComputeNutritionNode
    → ValidatePlanNode → PersistPlanNode

This module **assembles** that chain over one shared ``TaskContext``: each deterministic
``Node`` is a thin orchestration shell that reads prior outputs from
``TaskContext.nodes``, calls **one** already-built E6/E7/E8 kernel, and ``save_output``s
a typed result — it re-implements **no** rollup, card-field, budget, macro, validator, or
recompute formula (DECISIONS). ``GeneratePlanNode`` (the single ``AgentNode``) is
**imported** from E10·P1 (``app/core/weekly_agent.py``) and wired as the 4th node;
``WeeklyPlanner`` (the ``Workflow`` subclass) lands in TASK-004.

Two load-bearing rules (DECISIONS):

* **The DB ``Session`` rides in ``TaskContext.metadata["session"]``** — the endpoint
  (E10·P3) opens it, runs ``run_async(context=ctx)`` on a caller-built
  ``TaskContext(event=…, metadata={"session": session})``, and commits. Nodes read the
  shared session and **never** ``SessionLocal()``/``commit()`` (caller owns the txn).
* **``RecomputeConstants`` is monthly-gated and writes nothing** — it computes the
  proposed fresh constants in memory; the durable atomic ``profile.yaml`` write happens
  in ``PersistPlanNode`` **only after** the validated plan row is staged (TASK-002/003),
  so a failed brief never advances the file.

Pure ``app/core`` module otherwise: no FastAPI route, no endpoint, no get-or-generate /
``?refresh`` / wire-response assembly (all E10·P3).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date, timedelta
from typing import ClassVar

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.core.agent_node import BriefGenerationError
from app.core.cards import CARD_META, all_cards
from app.core.constraints import (
    Severity,
    ValidationContext,
    validate_weekly,
)
from app.core.enums import WorkoutCard
from app.core.nodes import Node
from app.core.profile import Profile, load_profile
from app.core.task_context import TaskContext
from app.core.time import now_sofia
from app.core.weekly_agent import GeneratePlanNode
from app.core.workflow import NodeConfig, Workflow, WorkflowSchema
from app.database.models import DailyMetrics, Plans, StrengthTests
from app.services.aggregates import Aggregates, load_aggregates
from app.services.budgets import compute_budgets
from app.services.derive.plan import PlannedSession, expand_plan
from app.services.macros import LastWeekNutrition, WeeklyNutrition, compute_weekly_nutrition
from app.services.recompute import (
    QualityFocus,
    StrengthPoint,
    next_quality_focus,
    ramp_cadence_for,
    rederive_zones,
    smooth_strength_trend,
)
from app.services.targets import WeeklyTargets, compute_targets

# §5.1/§9 deload cadence — the 4-week block ``compute_budgets`` reads via its 0-based
# ``iso_week_index`` (``(idx + 1) % 4 == 0`` → the 4th week deloads). Pinned here so the
# week-in-block derivation matches the budget kernel's ``DELOAD_EVERY_N_WEEKS``.
_DELOAD_BLOCK_WEEKS = 4

# §10 monthly constants recompute cadence (DECISIONS D1): ``RecomputeConstants`` fires
# when the ISO-week distance since the last recompute is ≥ this (4 ≈ monthly), or never.
RECOMPUTE_EVERY_N_WEEKS = 4

# `PersistPlanNode` STAGES the proposed `profile.yaml` rewrite under this `TaskContext`
# metadata key instead of writing it inside the node — the durable file write is a
# non-transactional side effect, so it must happen ONLY **after** the endpoint's DB
# `commit()` succeeds (E10·P3 applies it), or a commit-only failure would advance the file
# for a plan whose row rolled back (review — realizes DECISIONS D3's "one fate" correctly).
PENDING_PROFILE_WRITE_KEY = "pending_profile_write"


class WeeklyPlannerEvent(BaseModel):
    """The runner's input event — internal engine state (never serialised).

    ``anchor`` is the Europe/Sofia anchor date for the target ISO week (E10·P3 derives
    it from ``iso_week``/``now_sofia()``); ``iso_week`` is the period key (``YYYY-Www``);
    ``week_start`` is the Monday of the ISO week (Europe/Sofia). Snake_case (mirrors the
    E1·P3 ``TaskContext`` — ``TaskContext.event`` is never sent to the client).
    """

    anchor: date
    iso_week: str
    week_start: date


def _session_of(task_context: TaskContext) -> Session:
    """The open DB ``Session`` the endpoint injected (caller owns the txn).

    Read off ``task_context.metadata["session"]`` — the seam E10·P3 populates; a missing
    session is a wiring bug, surfaced loudly rather than silently opening a new one.
    """
    session = task_context.metadata.get("session")
    if not isinstance(session, Session):
        raise ValueError(
            "task_context.metadata['session'] must be an open SQLAlchemy Session"
        )
    return session


def _fresh_profile(task_context: TaskContext) -> Profile:
    """The fresh ``Profile`` downstream nodes read.

    ``RecomputeConstants`` stores the (possibly recomputed) ``Profile`` under its own
    output so budgets/derive/targets/nutrition use the just-proposed constants this run;
    a node running before/without it falls back to ``load_profile()``. Read structurally
    by node name so this read does not bind ``RecomputeConstants`` at import time.
    """
    output = task_context.nodes.get("RecomputeConstants")
    profile = getattr(output, "profile", None)
    if isinstance(profile, Profile):
        return profile
    return load_profile()


# ---------------------------------------------------------------------------
# LoadAggregatesNode — the 7/28-day rollups (E6·P3).
# ---------------------------------------------------------------------------
class LoadAggregatesNode(Node):
    """Read the 7/28-day training + nutrition-adherence rollups (E6·P3).

    Reads the shared ``Session`` and calls ``load_aggregates(session, event.anchor)``;
    ``save_output``s the ``Aggregates`` (wrapped so the engine's ``save_output`` —
    which keys a ``BaseModel`` — accepts the frozen dataclass). Opens no session,
    computes no rollup itself.
    """

    class OutputType(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)

        aggregates: Aggregates

    async def process(self, task_context: TaskContext) -> TaskContext:
        session = _session_of(task_context)
        aggregates = load_aggregates(session, task_context.event.anchor)
        self.save_output(self.OutputType(aggregates=aggregates))
        return task_context


def _aggregates_of(task_context: TaskContext) -> Aggregates:
    output = task_context.nodes.get(LoadAggregatesNode.__name__)
    if output is None:
        raise ValueError("LoadAggregatesNode output missing — node order is wrong")
    return output.aggregates


# ---------------------------------------------------------------------------
# RecomputeConstants — the §10 monthly recompute orchestrator (E8·P5 helpers).
# ---------------------------------------------------------------------------
def _iso_week_monday(iso_week: str) -> date:
    """The Monday (``date``) of an ISO week key (``YYYY-Www``) — year-boundary-safe."""
    year_str, week_str = iso_week.split("-W")
    return date.fromisocalendar(int(year_str), int(week_str), 1)


def is_recompute_due(last_week: str | None, current_week: str) -> bool:
    """Is the §10 monthly constants recompute due this ISO week? (DECISIONS D1).

    ``True`` when never recomputed (``last_week is None``) **or** the real ISO-week
    distance ``current_week − last_week`` is ``>= RECOMPUTE_EVERY_N_WEEKS`` (4 ≈ monthly).
    The distance is computed via ``date.fromisocalendar`` on each week's Monday then
    ``(d_now − d_last).days // 7`` — year-boundary-safe, **never** a lexical string
    compare. Pure + total: a malformed or future ``last_week`` (distance ≤ 0) is **not**
    due (idempotent on a same-week ``?refresh``/replay).
    """
    if last_week is None:
        return True
    distance_weeks = (_iso_week_monday(current_week) - _iso_week_monday(last_week)).days // 7
    return distance_weeks >= RECOMPUTE_EVERY_N_WEEKS


class RecomputeConstantsOutput(BaseModel):
    """``RecomputeConstants``'s output (DECISIONS D1/D3).

    ``constants_recomputed`` is the ``WeeklyPlan.data.constantsRecomputed`` flag; on a due
    run it also carries the proposed-fresh ``Profile`` (for ``PersistPlanNode``'s
    ``write_profile`` + downstream nodes) and the recomputed ``constants`` (for
    ``inputs_snapshot`` + the quality pick the validator re-reads). On a not-due run only
    the unchanged ``profile`` rides downstream (``constants_recomputed=False``).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    constants_recomputed: bool
    profile: Profile | None = None
    recomputed: dict | None = None


def _strength_series(session: Session, column: str) -> list[StrengthPoint]:
    """The weekly ``strength_tests`` series for one metric (``max_pushups``/``pullups``).

    Reads ``(iso_week, max_*)`` rows ordered by week; a missed test (``NULL`` value) is
    kept as a ``None``-valued ``StrengthPoint`` (``smooth_strength_trend`` drops it — a
    missed test is "no data", never read as 0 reps).
    """
    col = getattr(StrengthTests, column)
    rows = session.execute(
        select(StrengthTests.iso_week, col).order_by(StrengthTests.iso_week)
    ).all()
    return [StrengthPoint(iso_week=week, value=value) for week, value in rows]


class RecomputeConstants(Node):
    """The §10 monthly recompute orchestrator — runs the E8·P5 helpers in memory (E8·P5).

    Monthly-gated (``is_recompute_due``): on a **not-due** week it stores the unchanged
    ``Profile`` for downstream nodes and ``save_output``s ``constants_recomputed=False``
    (no helper call, no file write). On a **due** week it runs the four E8·P5 helpers
    (``ramp_cadence``/``next_quality_focus``/``smooth_strength_trend``/``rederive_zones``),
    **merges** their value-object outputs into a new **validated** ``Profile`` via
    ``Profile.model_validate({**dump, **updates})`` (a full re-validate — ``model_copy(
    update=…)`` does **not** re-run Pydantic v2 validators), stamps
    ``meta.constants_recomputed_week``, and ``save_output``s the proposed-fresh ``Profile``
    + the recomputed constants. It writes **no** file — ``PersistPlanNode`` does the atomic
    ``write_profile`` **after** the validated plan row is staged (DECISIONS D3), so a failed
    brief never advances ``profile.yaml``. The §10 arithmetic is **all** in E8·P5; this node
    only orchestrates + decides staleness.
    """

    async def process(self, task_context: TaskContext) -> TaskContext:
        event: WeeklyPlannerEvent = task_context.event
        profile = load_profile()

        if not is_recompute_due(profile.meta.constants_recomputed_week, event.iso_week):
            self.save_output(
                RecomputeConstantsOutput(constants_recomputed=False, profile=profile)
            )
            return task_context

        session = _session_of(task_context)
        last_week = profile.meta.constants_recomputed_week
        weeks_elapsed = (
            RECOMPUTE_EVERY_N_WEEKS
            if last_week is None
            else (_iso_week_monday(event.iso_week) - _iso_week_monday(last_week)).days // 7
        )

        # --- The four E8·P5 helpers (value objects; this node writes nothing) ---
        cadence = ramp_cadence_for(profile, weeks_since_last_bump=weeks_elapsed)
        quality = next_quality_focus(_last_quality_focus(task_context))
        pushups = smooth_strength_trend(_strength_series(session, "max_pushups"))
        pullups = smooth_strength_trend(_strength_series(session, "max_pullups"))
        zones = rederive_zones(
            current_max_hr=profile.thresholds.max_hr,
            current_rhr=profile.thresholds.rhr_baseline,
            new_max_hr=profile.thresholds.max_hr,
            new_rhr=profile.thresholds.rhr_baseline,
        )

        # --- Merge into a FULLY RE-VALIDATED Profile (re-runs E3·P1 validators) ---
        dump = profile.model_dump(mode="json")
        dump["thresholds"]["cadence_current_spm"] = cadence.new_spm
        if zones.changed and zones.zones is not None:
            dump["zones"] = {name: list(bounds) for name, bounds in zones.zones.items()}
        dump["meta"]["constants_recomputed_week"] = event.iso_week
        proposed = Profile.model_validate(dump)

        recomputed = {
            "cadence_spm": cadence.new_spm,
            "cadence_bumped": cadence.bumped,
            "quality_focus": quality.value,
            "strength_pushups": {"smoothed": pushups.smoothed, "direction": pushups.direction},
            "strength_pullups": {"smoothed": pullups.smoothed, "direction": pullups.direction},
            "zones_changed": zones.changed,
        }
        self.save_output(
            RecomputeConstantsOutput(
                constants_recomputed=True, profile=proposed, recomputed=recomputed
            )
        )
        return task_context


def _last_quality_focus(task_context: TaskContext) -> QualityFocus | None:
    """Last week's quality focus to flip off (``None`` cold start → THRESHOLD).

    There is no stored prior-quality history in this phase's scope; the flip opens on
    ``THRESHOLD`` (the base-phase quality day) and ``next_quality_focus`` is total over a
    ``None``. A future phase that persists the prior pick threads it through here.
    """
    return None


# ---------------------------------------------------------------------------
# ComputeBudgetsNode — the §5.1 weekly budgets (E8·P4).
# ---------------------------------------------------------------------------
def _iso_week_index(iso_week: str) -> int:
    """The 0-based week-in-block index ``compute_budgets`` reads (DECISIONS / §5.1).

    Derived from the ISO week **number** modulo the 4-week deload block, so the budget
    kernel's ``(index + 1) % 4 == 0`` fires on the 4th calendar week of each block. The
    ISO week number comes off the period key (``YYYY-Www``), never a wall-clock read.
    """
    week_number = int(iso_week.split("-W")[1])
    return (week_number - 1) % _DELOAD_BLOCK_WEEKS


def _window_avg(session: Session, anchor: date, days: int, column: str) -> float | None:
    """The NULL-skipping average of ``column`` over the inclusive ``[anchor-(days-1),
    anchor]`` Sofia-day window of ``daily_metrics``, or ``None`` when no day logged it.

    Reads the rolling 7-day averages (sleep/HRV/RHR) ``compute_budgets`` compares against
    the rolling 30-day baselines. ``AVG`` ignores NULLs, returning ``None`` for an empty
    window — passed straight to the kernel, which fails the 3-day upgrade closed and
    counts no under-recovery signal on a ``None`` (E8·P4).
    """
    start = (anchor - timedelta(days=days - 1)).isoformat()
    end = anchor.isoformat()
    col = getattr(DailyMetrics, column)
    stmt = select(func.avg(col)).where(DailyMetrics.date.between(start, end))
    return session.execute(stmt).scalar_one_or_none()


def _anchor_baseline(session: Session, anchor: date, column: str) -> float | None:
    """The rolling-30d baseline value stored on the **anchor** day's ``daily_metrics`` row.

    ``hrv_30d_mean``/``hrv_30d_sd``/``rhr_30d_mean`` are materialised per-day (E6·P2); the
    budget kernel reads the anchor day's. ``None`` when the anchor row is absent or the
    baseline is not yet computed (the kernel guards every baseline for ``None``).
    """
    col = getattr(DailyMetrics, column)
    stmt = select(col).where(DailyMetrics.date == anchor.isoformat())
    return session.execute(stmt).scalar_one_or_none()


class ComputeBudgetsNode(Node):
    """Compute the §5.1 weekly budgets — the hard limits the LLM plans within (E8·P4).

    Assembles ``compute_budgets``'s keyword inputs from the ``Aggregates`` rollups + the
    fresh ``Profile`` + the anchor day's rolling baselines (read via the shared session),
    calls the kernel, and ``save_output``s the ``WeeklyBudgets``. Computes no budget rule
    itself (the §5.1/§9/§8.4 arithmetic is all in E8·P4).
    """

    class OutputType(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)

        budgets: object  # app.core.constraints.WeeklyBudgets (a frozen dataclass)

    async def process(self, task_context: TaskContext) -> TaskContext:
        session = _session_of(task_context)
        event: WeeklyPlannerEvent = task_context.event
        # Capture the upstream Aggregates (node order) — the prior-long-run / adherence
        # feeds ride into the agent context below; the budget inputs are the rolling baselines.
        aggregates = _aggregates_of(task_context)
        anchor = event.anchor

        budgets = compute_budgets(
            iso_week_index=_iso_week_index(event.iso_week),
            sleep_avg_7d_h=_window_avg(session, anchor, 7, "sleep_h"),
            hrv_avg_7d=_window_avg(session, anchor, 7, "hrv_sdnn"),
            hrv_30d_mean=_anchor_baseline(session, anchor, "hrv_30d_mean"),
            hrv_30d_sd=_anchor_baseline(session, anchor, "hrv_30d_sd"),
            rhr_avg_7d=_window_avg(session, anchor, 7, "rhr"),
            rhr_30d_mean=_anchor_baseline(session, anchor, "rhr_30d_mean"),
            gi_symptoms_this_week=False,
            prior_week_long_run_km=None,
            extra_underrecovery_signals=0,
        )
        self.save_output(self.OutputType(budgets=budgets))

        # Bridge the deterministic feeds into the TaskContext metadata seams the NEXT node —
        # GeneratePlanNode (the single AgentNode) — reads: `metadata["profile"]` for the
        # rendered-constitution SYSTEM prompt (agent_node._profile) and `metadata["computed"]`
        # for the USER context + `WeeklyDeps` (weekly_agent._weekly_feeds). E10·P1 built the
        # agent node to read these "expecting E10·P2 to place them" (E10·P1 RESEARCH §25); that
        # placement was never wired into a P2 task — this is it. Every value is already computed
        # upstream (LoadAggregatesNode / RecomputeConstants / this node) — no new query/formula.
        task_context.metadata["profile"] = _fresh_profile(task_context)
        task_context.metadata["computed"] = {
            "budgets": budgets,
            "training_7d": aggregates.training_7d,
            "training_28d": aggregates.training_28d,
            "nutrition_adherence": aggregates.nutrition_7d,
            "constants": _recomputed_constants(task_context),
        }
        return task_context


def _budgets_of(task_context: TaskContext):
    output = task_context.nodes.get(ComputeBudgetsNode.__name__)
    if output is None:
        raise ValueError("ComputeBudgetsNode output missing — node order is wrong")
    return output.budgets


# ---------------------------------------------------------------------------
# DeriveSessionsNode — expand the LLM picks into full sessions (E7·P2).
# ---------------------------------------------------------------------------
def _llm_output(task_context: TaskContext):
    """The ``WeeklyPlanLLMOutput`` the AgentNode (``GeneratePlanNode``) saved.

    Read by class name (``"GeneratePlanNode"``) so this phase needs no compile-time
    import of the E10·P1 node here; tests seed it directly.
    """
    output = task_context.nodes.get("GeneratePlanNode")
    if output is None:
        raise ValueError("GeneratePlanNode output missing — node order is wrong")
    return output


class DeriveSessionsNode(Node):
    """Expand the slim LLM picks into full ``PlannedSession``s (E7·P2 ``expand_plan``).

    Reads the ``WeeklyPlanLLMOutput`` (``core``/``extras`` ``PlannedPick[]``) + the fresh
    ``Profile``, calls ``expand_plan(core, extras, profile)`` — which copies the LLM dose
    verbatim and fills ``tier``/``intensity``/``zoneTarget``/``isHardDay``/``flags`` from
    ``CARD_META`` — and ``save_output``s the two expanded lists. Expands nothing by hand.
    """

    class OutputType(BaseModel):
        core: list[PlannedSession]
        extras: list[PlannedSession]

    async def process(self, task_context: TaskContext) -> TaskContext:
        out = _llm_output(task_context)
        profile = _fresh_profile(task_context)
        core, extras = expand_plan(out.core, out.extras, profile)
        self.save_output(self.OutputType(core=core, extras=extras))
        return task_context


def _expanded_sessions(task_context: TaskContext) -> list[PlannedSession]:
    output = task_context.nodes.get(DeriveSessionsNode.__name__)
    if output is None:
        raise ValueError("DeriveSessionsNode output missing — node order is wrong")
    return list(output.core) + list(output.extras)


# ---------------------------------------------------------------------------
# ComputeTargetsNode — the weekly numeric targets (this phase's new kernel).
# ---------------------------------------------------------------------------
class ComputeTargetsNode(Node):
    """Derive the weekly ``WeeklyTargets`` from the expanded sessions (``compute_targets``).

    Reads the expanded ``PlannedSession[]`` + the fresh ``Profile`` and calls the new pure
    ``compute_targets(sessions, profile)`` (DECISIONS D2 — the one kernel this phase adds);
    ``save_output``s the ``WeeklyTargets`` (sums/ratios/counts + the cadence cue).
    """

    class OutputType(BaseModel):
        targets: WeeklyTargets

    async def process(self, task_context: TaskContext) -> TaskContext:
        sessions = _expanded_sessions(task_context)
        profile = _fresh_profile(task_context)
        targets = compute_targets(sessions, profile)
        self.save_output(self.OutputType(targets=targets))
        return task_context


# ---------------------------------------------------------------------------
# ComputeNutritionNode — the weekly nutrition half (E8·P3).
# ---------------------------------------------------------------------------
def _last_week_adherence(aggregates: Aggregates) -> LastWeekNutrition | None:
    """The 7-day intake scorecard ``WeeklyNutrition.lastWeek`` carries (E13·P1).

    Delegates to ``LastWeekNutrition.from_adherence`` (the typed mapper + null predicate
    live next to the model in ``macros.py`` — DECISIONS Decision 4), which returns ``None``
    (→ ``lastWeek: null``) when the 7-day window logged no dietary coverage and otherwise
    the camelCase scorecard. No more snake_case ``dataclasses.asdict`` dump.
    """
    return LastWeekNutrition.from_adherence(aggregates.nutrition_7d)


class ComputeNutritionNode(Node):
    """Compute the weekly ``WeeklyNutrition`` from the picks + profile (E8·P3).

    Maps each expanded session → ``(suggested_day, CARD_META[card].day_type)`` (E7·P1 —
    the **caller's** map; E8·P3 takes the resolved ``dayType``), reads the fresh
    ``Profile``'s ``nutrition``/``athlete`` + last-week intake adherence
    (``Aggregates.nutrition_7d``), and calls ``compute_weekly_nutrition(...)`` →
    ``WeeklyNutrition``. Computes no macro itself.
    """

    class OutputType(BaseModel):
        nutrition: WeeklyNutrition

    async def process(self, task_context: TaskContext) -> TaskContext:
        sessions = _expanded_sessions(task_context)
        profile = _fresh_profile(task_context)
        aggregates = _aggregates_of(task_context)

        picks = [
            (
                s.suggested_day.value if s.suggested_day is not None else "",
                CARD_META[s.card].day_type,
            )
            for s in sessions
        ]
        nutrition = compute_weekly_nutrition(
            picks=picks,
            weight_kg=profile.athlete.goal_weight_kg,
            nutrition=profile.nutrition,
            athlete=profile.athlete,
            last_week=_last_week_adherence(aggregates),
        )
        self.save_output(self.OutputType(nutrition=nutrition))
        return task_context


# ---------------------------------------------------------------------------
# Shared readers for the validate/persist tail.
# ---------------------------------------------------------------------------
def _recompute_output(task_context: TaskContext) -> RecomputeConstantsOutput | None:
    output = task_context.nodes.get(RecomputeConstants.__name__)
    return output if isinstance(output, RecomputeConstantsOutput) else None


def _recomputed_constants(task_context: TaskContext) -> dict | None:
    """The recomputed-constant bundle (or ``None`` on a not-due week)."""
    output = _recompute_output(task_context)
    return output.recomputed if output is not None else None


def _quality_run_pick(task_context: TaskContext) -> WorkoutCard | None:
    """The code-decided threshold↔VO₂ pick the validator re-reads (round-2 M2).

    Reads the ``quality_focus`` cue off ``RecomputeConstants``'s recomputed constants —
    the **same** source E10·P1's ``WeeklyDeps.quality_run_pick`` uses — so both validation
    layers see one ``quality_run_pick``. ``None`` (no quality run expected → the validator
    skips the threshold↔VO₂ rule) when absent/unrecognised or not a recompute week.
    """
    constants = _recomputed_constants(task_context)
    if not constants:
        return None
    focus = constants.get("quality_focus")
    focus = getattr(focus, "value", focus)
    if focus in (WorkoutCard.threshold.value, WorkoutCard.vo2.value):
        return WorkoutCard(focus)
    return None


# ---------------------------------------------------------------------------
# ValidatePlanNode — the belt-and-suspenders re-check before persist (E7·P3 + E9).
# ---------------------------------------------------------------------------
class ValidatePlanNode(Node):
    """The deterministic belt-and-suspenders re-check before persist (LLM.md §4).

    Builds a ``ValidationContext`` from the code-computed ``WeeklyBudgets``
    (``ComputeBudgetsNode``) + the ``quality_run_pick`` (the ``RecomputeConstants``
    ``next_quality_focus`` cue — the same source the agent-side validator used) + the
    full card pool, re-runs the **pure** ``validate_weekly`` over the **LLM picks**
    (``GeneratePlanNode``'s ``WeeklyPlanLLMOutput``), and on **any hard** ``Violation``
    raises ``BriefGenerationError(code="brief_generation_failed")`` — so a
    constraint-breaking plan never reaches ``PersistPlanNode``/the cache.

    It does **not** ``ModelRetry`` and does **not** re-run the agent: the ``ModelRetry ≤2``
    budget was already spent **inside** ``GeneratePlanNode``'s ``@agent.output_validator``
    (E9·P2). This is the second, deterministic layer of LLM.md §4's "two layers, one
    source of truth". A clean plan (``[]`` or only ``soft``) falls through and
    ``save_output``s a ``passed`` marker (the soft-violation list rides along for E10·P3).
    """

    class OutputType(BaseModel):
        passed: bool
        soft_violations: list[str] = []

    async def process(self, task_context: TaskContext) -> TaskContext:
        out = _llm_output(task_context)
        ctx = ValidationContext(
            budgets=_budgets_of(task_context),
            quality_run_pick=_quality_run_pick(task_context),
            week_plan_cards=frozenset(meta.card for meta in all_cards()),
        )
        violations = validate_weekly(out, ctx)
        if any(v.severity is Severity.hard for v in violations):
            raise BriefGenerationError(code="brief_generation_failed")
        self.save_output(
            self.OutputType(passed=True, soft_violations=[v.rule for v in violations])
        )
        return task_context


# ---------------------------------------------------------------------------
# PersistPlanNode — stage one `plans` row, then atomically write profile.yaml.
# ---------------------------------------------------------------------------
def _targets_of(task_context: TaskContext) -> WeeklyTargets:
    output = task_context.nodes.get(ComputeTargetsNode.__name__)
    if output is None:
        raise ValueError("ComputeTargetsNode output missing — node order is wrong")
    return output.targets


def _nutrition_of(task_context: TaskContext) -> WeeklyNutrition:
    output = task_context.nodes.get(ComputeNutritionNode.__name__)
    if output is None:
        raise ValueError("ComputeNutritionNode output missing — node order is wrong")
    return output.nutrition


class PersistPlanNode(Node):
    """Stage one ``plans`` row, then atomically (re)write ``profile.yaml`` (DB.md §4; §10).

    Assembles the persistable payload and ``session.execute(insert(Plans))`` **without
    committing** (the endpoint owns the txn — E10·P3): ``iso_week``; ``payload`` (the
    structured data — budgets + expanded ``core``/``extras`` + targets + nutrition +
    ``constantsRecomputed``/``weekStart``/``isoWeek``); ``rationale`` (the LLM narrative);
    ``inputs_snapshot`` (``{aggregates, constants}`` — the aggregates **and** constants the
    LLM saw, for reproducibility); ``model`` (the agent ``model_id``);
    ``constitution_version``; ``created_at`` (``now_sofia()``).

    **After** staging the row, if ``RecomputeConstants`` proposed fresh constants it
    **stages** the proposed ``Profile`` under ``PENDING_PROFILE_WRITE_KEY`` (it does **not**
    write the file here). The durable ``profile.yaml`` rewrite is a non-transactional side
    effect, so the endpoint (E10·P3) applies it via ``write_profile`` **only after** its DB
    ``commit()`` succeeds — keeping the file write and the plan row on **one fate**: a
    downstream node failure short-circuits before this node, and a commit-only failure
    leaves the staged write un-applied, so the file is never advanced for a brief that did
    not persist (DECISIONS D3; review). It does **no** commit, no lookup-by-``iso_week``, no
    ``?refresh`` delete, no file write, and builds no wire response (all E10·P3).
    ``save_output``s the assembled structured ``data`` so E10·P3 wraps it into the
    ``WeeklyPlan`` response.
    """

    class OutputType(BaseModel):
        data: dict

    async def process(self, task_context: TaskContext) -> TaskContext:
        session = _session_of(task_context)
        event: WeeklyPlannerEvent = task_context.event
        profile = _fresh_profile(task_context)

        derived = task_context.nodes[DeriveSessionsNode.__name__]
        budgets = _budgets_of(task_context)
        targets = _targets_of(task_context)
        nutrition = _nutrition_of(task_context)
        aggregates = _aggregates_of(task_context)
        recompute = _recompute_output(task_context)
        constants = recompute.recomputed if recompute is not None else None
        out = _llm_output(task_context)

        data = {
            "isoWeek": event.iso_week,
            "weekStart": event.week_start.isoformat(),
            "budgets": dataclasses.asdict(budgets),
            "core": [s.model_dump(mode="json") for s in derived.core],
            "extras": [s.model_dump(mode="json") for s in derived.extras],
            "targets": targets.model_dump(mode="json"),
            "nutrition": nutrition.model_dump(mode="json"),
            "constantsRecomputed": bool(recompute.constants_recomputed) if recompute else False,
        }
        inputs_snapshot = {
            "aggregates": aggregates.to_dict(),
            "constants": constants,
        }
        narrative = [n.model_dump(mode="json") for n in out.narrative]

        session.execute(
            insert(Plans).values(
                iso_week=event.iso_week,
                payload=json.dumps(data),
                rationale=json.dumps(narrative),
                inputs_snapshot=json.dumps(inputs_snapshot),
                model=_agent_model_id(),
                constitution_version=profile.constitution_version,
                created_at=now_sofia().isoformat(),
            )
        )

        # On a due-recompute week, STAGE the proposed profile.yaml rewrite for the endpoint
        # to apply atomically ONLY AFTER a successful DB commit (E10·P3 reads
        # PENDING_PROFILE_WRITE_KEY post-commit and calls write_profile). The durable file
        # write is a non-transactional side effect, so writing it here — before the
        # endpoint's commit — would advance the file for a plan whose row could still roll
        # back at commit; staging keeps the file write and the plan row on one fate (D3).
        if recompute is not None and recompute.constants_recomputed and recompute.profile is not None:
            task_context.metadata[PENDING_PROFILE_WRITE_KEY] = recompute.profile

        self.save_output(self.OutputType(data=data))
        return task_context


def _agent_model_id() -> str:
    """The agent's ``model_id`` for the ``plans.model`` column.

    Read from ``GeneratePlanNode``'s ``AgentConfig`` (the default Opus id from
    ``Settings``) so a Sonnet downshift is a config change, not a node edit. Imported
    lazily so this module's import doesn't pull the PydanticAI harness (E9) at load time.
    """
    from app.core.settings import Settings

    return Settings.model_fields["model_id"].default


# ---------------------------------------------------------------------------
# The assembled WEEKLY_PLANNER workflow (ARCHITECTURE §5 — strictly linear).
# ---------------------------------------------------------------------------
class WeeklyPlanner(Workflow):
    """The ``WEEKLY_PLANNER`` workflow — the nine ARCHITECTURE §5 nodes, linear (E10·P2).

    A **strictly linear** chain (no router — that is ``DAILY_ADJUSTER``'s
    ``SafetyGateRouter``):

        LoadAggregatesNode → RecomputeConstants → ComputeBudgetsNode → GeneratePlanNode
        → DeriveSessionsNode → ComputeTargetsNode → ComputeNutritionNode
        → ValidatePlanNode → PersistPlanNode

    ``GeneratePlanNode`` (E10·P1) is the only ``AgentNode`` — wired as the 4th node; it
    reads this phase's ``ComputeBudgetsNode``/``LoadAggregatesNode``/``RecomputeConstants``
    outputs from the shared ``TaskContext``. ``PersistPlanNode`` is terminal
    (``connections=[]``). Construction runs ``WorkflowValidator`` (E1·P3) — a mis-wired /
    missing / duplicate node fails **here**, not mid-run. The endpoint (E10·P3) runs
    ``WeeklyPlanner().run_async(context=TaskContext(event=…, metadata={"session": session}))``
    and commits; tests mock ``GeneratePlanNode`` (a stand-in ``Node``) so the deterministic
    graph runs with no LLM/network/key.
    """

    workflow_schema: ClassVar[WorkflowSchema] = WorkflowSchema(
        event_schema=WeeklyPlannerEvent,
        start=LoadAggregatesNode,
        nodes=[
            NodeConfig(node=LoadAggregatesNode, connections=[RecomputeConstants]),
            NodeConfig(node=RecomputeConstants, connections=[ComputeBudgetsNode]),
            NodeConfig(node=ComputeBudgetsNode, connections=[GeneratePlanNode]),
            NodeConfig(node=GeneratePlanNode, connections=[DeriveSessionsNode]),
            NodeConfig(node=DeriveSessionsNode, connections=[ComputeTargetsNode]),
            NodeConfig(node=ComputeTargetsNode, connections=[ComputeNutritionNode]),
            NodeConfig(node=ComputeNutritionNode, connections=[ValidatePlanNode]),
            NodeConfig(node=ValidatePlanNode, connections=[PersistPlanNode]),
            NodeConfig(node=PersistPlanNode, connections=[]),
        ],
        description="WEEKLY_PLANNER — the weekly tiered-plan brain (ARCHITECTURE §5).",
    )
