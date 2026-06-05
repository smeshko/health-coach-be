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
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.cards import CARD_META
from app.core.nodes import Node
from app.core.profile import Profile, load_profile
from app.core.task_context import TaskContext
from app.database.models import DailyMetrics
from app.services.aggregates import Aggregates, load_aggregates
from app.services.budgets import compute_budgets
from app.services.derive.plan import PlannedSession, expand_plan
from app.services.macros import WeeklyNutrition, compute_weekly_nutrition
from app.services.targets import WeeklyTargets, compute_targets

# §5.1/§9 deload cadence — the 4-week block ``compute_budgets`` reads via its 0-based
# ``iso_week_index`` (``(idx + 1) % 4 == 0`` → the 4th week deloads). Pinned here so the
# week-in-block derivation matches the budget kernel's ``DELOAD_EVERY_N_WEEKS``.
_DELOAD_BLOCK_WEEKS = 4


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
        # Asserts the upstream Aggregates landed (node order) — the prior-long-run /
        # adherence feeds ride downstream; the budget inputs are the rolling baselines.
        _aggregates_of(task_context)
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
def _last_week_adherence(aggregates: Aggregates) -> dict | None:
    """The 7-day intake-adherence summary ``WeeklyNutrition.lastWeek`` carries.

    Flattens the E6·P3 ``NutritionAdherence`` (a frozen dataclass) to a JSON-able dict so
    it survives ``PersistPlanNode``'s ``payload`` serialisation. Its derivation is E6·P3's
    (passed through unchanged here — E8·P3 keeps ``last_week`` opaque).
    """
    adherence = aggregates.nutrition_7d
    if adherence is None:
        return None
    return dataclasses.asdict(adherence)


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
