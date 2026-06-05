"""The ``DAILY_ADJUSTER`` workflow — the deterministic daily-brain skeleton (E11·P2).

ARCHITECTURE §5 fixes the daily graph as the six-node chain with the system's **one**
router (the safety gate):

    ComputeReadinessNode → SafetyGateRouter → [SafetyRestNode | TuneSessionNode]
    → DeriveSessionNode → ValidateSessionNode → PersistSuggestionNode

This module **assembles** that graph over one shared ``TaskContext``: each deterministic
``Node`` is a thin orchestration shell that reads prior outputs from ``TaskContext.nodes``,
calls **one** already-built E6/E7/E8 kernel (``compute_readiness`` / ``evaluate_safety_gate``
/ ``expand_session`` / ``compute_macro_focus`` / ``validate_daily``), and ``save_output``s a
typed result — it re-implements **no** readiness/gate/card-field/macro/validator formula.
``TuneSessionNode`` (the single ``AgentNode``) is **imported** from E11·P1
(``app/core/daily_agent.py``) and wired as the router's clean-path fallback; the
``DailyAdjuster`` ``Workflow`` subclass lands in TASK-004.

Two load-bearing rules (DECISIONS):

* **The DB ``Session`` rides in ``TaskContext.metadata["session"]``** — the endpoint
  (E11·P3) opens it, builds ``ctx = TaskContext(event=…, metadata={"session": session})``,
  runs ``run_async(context=ctx)``, and commits. Nodes read the shared session and **never**
  ``SessionLocal()``/``commit()`` (caller owns the txn).
* **The safety gate is "two kinds of rest"** — when ``SafetyGateRouter`` trips it routes to
  ``SafetyRestNode``, which code-writes **and persists** the REST/active-recovery brief (no
  LLM, no arithmetic) and calls ``stop_workflow()`` — the engine breaks the loop before any
  successor, so the gated terminal persists itself (``connections=[]``).

Pure ``app/core`` module otherwise: no FastAPI route, no get-or-generate / ``?refresh`` /
wire-response assembly (all E11·P3).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from app.api.schemas.daily import IntakeSummary, IntakeVsTarget
from app.api.schemas.narrative import NarrativeSection
from app.core.cards import CARD_META, all_cards, floors_day_type_hard
from app.core.daily_agent import TuneSessionNode
from app.core.enums import DayType, NarrativeType, WorkoutCard
from app.core.nodes import BaseRouter, Node, RouterNode
from app.core.profile import Profile, load_profile
from app.core.task_context import TaskContext
from app.core.time import now_sofia
from app.database.models import Checkins, DailyMetrics, Plans, Suggestions
from app.services.derive.session import SessionBlock
from app.services.derive.session import SessionPick as DerivePick
from app.services.derive.session import expand_session
from app.services.macros import MacroFocus, compute_macro_focus
from app.services.readiness import Readiness, compute_readiness
from app.services.safety_gate import SafetyGate, evaluate_safety_gate


class DailyAdjusterEvent(BaseModel):
    """The runner's input event — internal engine state (never serialised).

    ``date`` is the Europe/Sofia target day (E11·P3 derives it from the request
    ``date``/``now_sofia()``). Snake_case (mirrors the E1·P3 ``TaskContext`` and
    E10·P2's ``WeeklyPlannerEvent`` — ``TaskContext.event`` is never sent to the client).
    """

    date: date


# --------------------------------------------------------------------------- #
# Shared readers + small pure helpers (no business arithmetic).
# --------------------------------------------------------------------------- #
def _session_of(task_context: TaskContext) -> Session:
    """The open DB ``Session`` the endpoint injected (caller owns the txn).

    Read off ``task_context.metadata["session"]`` — the seam E11·P3 populates; a
    missing session is a wiring bug, surfaced loudly rather than silently opening one.
    """
    session = task_context.metadata.get("session")
    if not isinstance(session, Session):
        raise ValueError(
            "task_context.metadata['session'] must be an open SQLAlchemy Session"
        )
    return session


def _metrics_row(session: Session, day: date) -> DailyMetrics | None:
    """The ``daily_metrics`` row for ``day`` (or ``None``)."""
    return session.execute(
        select(DailyMetrics).where(DailyMetrics.date == day.isoformat())
    ).scalar_one_or_none()


def _checkin_row(session: Session, day: date) -> Checkins | None:
    """The ``checkins`` row for ``day`` (or ``None``)."""
    return session.execute(
        select(Checkins).where(Checkins.date == day.isoformat())
    ).scalar_one_or_none()


def _iso_week_key(day: date) -> str:
    """The ``YYYY-Www`` ISO-week key of ``day`` (the ``plans`` lookup key)."""
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _week_plan_cards(session: Session, day: date) -> frozenset[WorkoutCard]:
    """The cards in ``day``'s active week plan — the ``card ∈ week plan`` allowed set.

    Reads the ``plans`` row for ``day``'s ISO week (E10) and unions its expanded
    ``core``/``extras`` cards. Falls back to **all** cards when no plan exists yet (a
    fresh system / pre-first-weekly day) so a missing plan never spuriously fails every
    session's card-in-plan check; ``validate_daily`` adds the §3 low-impact subs.
    """
    payload = session.execute(
        select(Plans.payload).where(Plans.iso_week == _iso_week_key(day))
    ).scalar_one_or_none()
    if payload:
        try:
            data = json.loads(payload)
        except (TypeError, ValueError):
            data = {}
        cards: set[WorkoutCard] = set()
        for key in ("core", "extras"):
            for entry in data.get(key, []) or []:
                value = entry.get("card") if isinstance(entry, dict) else None
                try:
                    cards.add(WorkoutCard(value))
                except (ValueError, KeyError):
                    continue
        if cards:
            return frozenset(cards)
    return frozenset(meta.card for meta in all_cards())


def _checkin_flags(session: Session, day: date) -> dict:
    """The day's check-in flags the daily context + validator read (``knee_pain``/``gi``)."""
    checkin = _checkin_row(session, day)
    return {
        "knee_pain": int(getattr(checkin, "knee_pain", 0) or 0),
        "gi_symptoms": int(getattr(checkin, "gi_symptoms", 0) or 0),
        "illness": int(getattr(checkin, "illness", 0) or 0),
    }


def _live_weight(today: DailyMetrics | None, profile: Profile) -> float:
    """The day's live weight for the macro compute — today's logged ``body_weight``,
    else the profile's goal weight (the kernel needs a positive number)."""
    weight = getattr(today, "body_weight", None)
    if weight:
        return float(weight)
    return float(profile.athlete.goal_weight_kg)


def _daily_constants(profile: Profile) -> dict:
    """The small constants snapshot the daily context + ``inputs_snapshot`` carry."""
    return {"cadence_spm": profile.thresholds.cadence_current_spm}


def _readiness_of(task_context: TaskContext) -> Readiness:
    output = task_context.nodes.get(ComputeReadinessNode.__name__)
    if output is None:
        raise ValueError("ComputeReadinessNode output missing — node order is wrong")
    return output.readiness


def _gate_of(task_context: TaskContext) -> SafetyGate:
    output = task_context.nodes.get(GateTrippedRoute.__name__)
    if not isinstance(output, SafetyGate):
        raise ValueError("SafetyGate missing — the gate router did not run")
    return output


# --------------------------------------------------------------------------- #
# ComputeReadinessNode — the objective readiness score (E8·P1) + the agent bridge.
# --------------------------------------------------------------------------- #
class ComputeReadinessNode(Node):
    """Compute the day's objective ``Readiness`` (E8·P1) and bridge the agent context.

    Reads the day's + yesterday's ``daily_metrics`` rows (sleep/HRV/RHR + the rolling
    30-day baselines + yesterday's ``hard_day``), calls ``compute_readiness(...)`` →
    ``Readiness`` (``{score, band, penalties}``), and ``save_output``s it. It also
    **bridges** the deterministic feeds into ``TaskContext.metadata`` so the downstream
    ``TuneSessionNode`` (E11·P1) reads ``metadata["profile"]`` (the constitution SYSTEM
    prompt) + ``metadata["computed"]`` (the USER context + ``DailyDeps``) — the same seam
    E10·P2's ``ComputeBudgetsNode`` fills for the weekly agent. Writes **no**
    ``daily_metrics`` back here (that snapshot is ``PersistSuggestionNode``'s, so a failed
    brief never half-writes the day's row). Computes no score itself (the §6.1 arithmetic
    is all in E8·P1).
    """

    class OutputType(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)

        readiness: Readiness

    async def process(self, task_context: TaskContext) -> TaskContext:
        session = _session_of(task_context)
        event: DailyAdjusterEvent = task_context.event
        today = _metrics_row(session, event.date)
        yesterday = _metrics_row(session, event.date - timedelta(days=1))

        readiness = compute_readiness(
            sleep_h=getattr(today, "sleep_h", None),
            hrv_sdnn=getattr(today, "hrv_sdnn", None),
            hrv_30d_mean=getattr(today, "hrv_30d_mean", None),
            hrv_30d_sd=getattr(today, "hrv_30d_sd", None),
            rhr=getattr(today, "rhr", None),
            rhr_30d_mean=getattr(today, "rhr_30d_mean", None),
            yesterday_hard_day=bool(getattr(yesterday, "hard_day", 0) or 0),
        )
        self.save_output(self.OutputType(readiness=readiness))

        # Bridge the deterministic feeds into the metadata seams TuneSessionNode reads:
        # `metadata["profile"]` (agent_node._profile → the constitution) and
        # `metadata["computed"]` (daily_agent._daily_feeds → the USER context + DailyDeps).
        # `safety_gate` is injected by GateTrippedRoute (computed during routing, below).
        profile = load_profile()
        task_context.metadata["profile"] = profile
        task_context.metadata["computed"] = {
            "readiness": readiness,
            "band": readiness.band,
            "week_plan_cards": _week_plan_cards(session, event.date),
            "flags": _checkin_flags(session, event.date),
            "live_weight_kg": _live_weight(today, profile),
            "constants": _daily_constants(profile),
        }
        return task_context


# --------------------------------------------------------------------------- #
# SafetyGateRouter — the system's one router (the safety gate; E8·P2).
# --------------------------------------------------------------------------- #
class GateTrippedRoute(RouterNode):
    """The one routing **predicate** — evaluate the §6.2 safety gate (E8·P2).

    ``determine_next_node(ctx)``: read the day's check-in flags + this-morning metrics,
    call ``evaluate_safety_gate(...)`` → ``SafetyGate``, ``save_output`` it (so
    ``SafetyRestNode``/``PersistSuggestionNode`` read it), inject it into the agent
    ``metadata["computed"]`` (so the clean-path LLM sees the un-triggered gate), and
    return a ``SafetyRestNode`` instance iff ``gate.triggered`` else ``None`` (so the
    ``BaseRouter`` falls through to ``fallback = TuneSessionNode``). The gate is **code**
    computed **before** the LLM (ARCHITECTURE §2/§6.2); it decides no gate rule itself.
    """

    def determine_next_node(self, task_context: TaskContext) -> Node | None:
        session = _session_of(task_context)
        event: DailyAdjusterEvent = task_context.event
        today = _metrics_row(session, event.date)
        checkin = _checkin_row(session, event.date)

        gate = evaluate_safety_gate(
            gi_symptoms=getattr(checkin, "gi_symptoms", None),
            illness=getattr(checkin, "illness", None),
            knee_pain=getattr(checkin, "knee_pain", None),
            sleep_h=getattr(today, "sleep_h", None),
            rhr=getattr(today, "rhr", None),
            rhr_30d_mean=getattr(today, "rhr_30d_mean", None),
            hrv_sdnn=getattr(today, "hrv_sdnn", None),
            hrv_30d_mean=getattr(today, "hrv_30d_mean", None),
        )
        self.save_output(gate)

        computed = task_context.metadata.get("computed")
        if isinstance(computed, dict):
            computed["safety_gate"] = gate

        if gate.triggered:
            return SafetyRestNode(task_context=task_context)
        return None


class SafetyGateRouter(BaseRouter):
    """The in-DAG router (E1·P3 ``BaseRouter``) — the system's **one** router.

    Composes the single ``GateTrippedRoute`` predicate (``routes``) and a
    ``fallback = TuneSessionNode`` (the clean LLM path). The runner calls ``.route(ctx)``:
    a tripped gate → ``SafetyRestNode`` (class), a clean gate → the ``TuneSessionNode``
    fallback. It never calls ``stop_workflow()`` (the ``BaseRouter`` contract — only
    ``SafetyRestNode`` does).
    """

    routes = [GateTrippedRoute]
    fallback = TuneSessionNode


# --------------------------------------------------------------------------- #
# SafetyRestNode — the code-written safety-gate terminal (ARCHITECTURE §5).
# --------------------------------------------------------------------------- #
def _rest_narrative(gate: SafetyGate) -> list[NarrativeSection]:
    """The fixed-template, **code-written** gated REST prose (no LLM).

    A ``caution`` section naming the firing reasons + a ``session`` section describing
    the forced recovery card. Only the daily ``summary|session|nutrition|caution`` kinds.
    """
    reasons = ", ".join(gate.reasons) if gate.reasons else "an active safety flag"
    card = gate.overrideTo.value if gate.overrideTo is not None else "rest"
    return [
        NarrativeSection(
            type=NarrativeType.caution,
            heading="Recovery day",
            body=(
                f"A safety flag is active ({reasons}), so today is a code-written "
                "rest / active-recovery day — no hard training while you recover."
            ),
        ),
        NarrativeSection(
            type=NarrativeType.session,
            heading="Today's session",
            body=(
                f"A gentle {card} session. Keep the effort easy and let your body reset; "
                "the plan resumes once the flag clears."
            ),
        ),
    ]


class SafetyRestNode(Node):
    """The **code-written** safety-gate terminal (ARCHITECTURE §5 "Two kinds of rest").

    On a tripped gate the router routes **here**, skipping the ``AgentNode`` entirely.
    It code-writes the REST/active-recovery brief — the forced ``overrideTo`` card
    expanded via ``expand_session`` (E7·P2), an empty ``alternatives``, a fixed-template
    ``narrative`` (no LLM), and a recovery ``MacroFocus`` from the card's ``dayType``
    (``compute_macro_focus`` — still **code numbers**) — **persists it** via the shared
    ``_persist_brief`` (``safety_gate_tripped=1``, ``gate_reason`` set, ``model=None``),
    ``save_output``s the structured ``data``, and **then** calls ``stop_workflow()``. It
    constructs **no** ``Agent`` and calls **no** ``agent.run``. A tripped gate is a
    **success**, not an error. Wired ``connections=[]`` (TASK-004): the engine breaks the
    loop before any successor, so this terminal persists itself.
    """

    class OutputType(BaseModel):
        brief: dict

    async def process(self, task_context: TaskContext) -> TaskContext:
        session = _session_of(task_context)
        event: DailyAdjusterEvent = task_context.event
        gate = _gate_of(task_context)
        readiness = _readiness_of(task_context)
        profile = load_profile()

        override = gate.overrideTo or WorkoutCard.rest
        meta = CARD_META[override]
        dose_high = meta.dose_min_high if meta.dose_min_high is not None else meta.dose_min_low
        session_block = expand_session(
            DerivePick(
                card=override,
                duration_min_low=meta.dose_min_low,
                duration_min_high=dose_high,
            ),
            profile,
        )
        day_type = meta.day_type
        macro_focus = compute_macro_focus(
            day_type=day_type,
            weight_kg=_live_weight(_metrics_row(session, event.date), profile),
            nutrition=profile.nutrition,
            athlete=profile.athlete,
        )
        brief = _persist_brief(
            task_context,
            session_block=session_block,
            alternatives=[],
            skip_ok=True,
            day_type=day_type,
            macro_focus=macro_focus,
            intake_yesterday=None,
            readiness=readiness,
            gate=gate,
            narrative=_rest_narrative(gate),
            model=None,
        )
        self.save_output(self.OutputType(brief=brief))
        task_context.stop_workflow()
        return task_context


# --------------------------------------------------------------------------- #
# The shared persist body — one insert+write-back, two callers (clean + gated).
# --------------------------------------------------------------------------- #
def _readiness_dict(readiness: Readiness) -> dict:
    return {
        "score": readiness.score,
        "band": readiness.band.value,
        "penalties": [dataclasses.asdict(p) for p in readiness.penalties],
    }


def _gate_dict(gate: SafetyGate) -> dict:
    return {
        "triggered": gate.triggered,
        "reasons": list(gate.reasons),
        "overrideTo": gate.overrideTo.value if gate.overrideTo is not None else None,
    }


def _persist_brief(
    task_context: TaskContext,
    *,
    session_block: SessionBlock,
    alternatives: list[SessionBlock],
    skip_ok: bool,
    day_type: DayType,
    macro_focus: MacroFocus,
    intake_yesterday: IntakeSummary | None,
    readiness: Readiness,
    gate: SafetyGate,
    narrative: list[NarrativeSection],
    model: str | None,
) -> dict:
    """The **single** persist body — write one ``suggestions`` row + the
    ``daily_metrics`` readiness/band snapshot (no commit), and return the full
    ``{ data, narrative }`` brief.

    Called by ``PersistSuggestionNode`` on the clean LLM path (``model`` = the agent id)
    and by ``SafetyRestNode`` on the gated path (``model=None`` — no model ran). One body,
    two callers, so the two persist sites cannot drift (DB.md §4/§6). The ``suggestions``
    table has no ``rationale`` column, so the LLM/code ``narrative`` rides **inside**
    ``payload`` (``{ data, narrative }``) — the exact wire brief E11·P3 returns on a cache
    hit. The endpoint (E11·P3) owns the transaction (``commit``) and the get-or-generate;
    this writes into the open session only.
    """
    session = _session_of(task_context)
    event: DailyAdjusterEvent = task_context.event
    profile = load_profile()
    date_str = event.date.isoformat()

    readiness_d = _readiness_dict(readiness)
    gate_d = _gate_dict(gate)
    constants = task_context.metadata.get("computed", {}).get("constants")
    data = {
        "date": date_str,
        "readiness": readiness_d,
        "safetyGate": gate_d,
        "session": session_block.model_dump(mode="json"),
        "alternatives": [a.model_dump(mode="json") for a in alternatives],
        "skipOk": skip_ok,
        "dayType": day_type.value,
        "macroFocus": macro_focus.model_dump(mode="json"),
        "intakeYesterday": (
            intake_yesterday.model_dump(mode="json") if intake_yesterday is not None else None
        ),
    }
    brief = {"data": data, "narrative": [n.model_dump(mode="json") for n in narrative]}
    inputs_snapshot = {
        "readiness": readiness_d,
        "safety_gate": gate_d,
        "band": readiness.band.value,
        "constants": constants,
    }

    session.execute(
        insert(Suggestions).values(
            date=date_str,
            payload=json.dumps(brief),
            readiness_score=readiness.score,
            band=readiness.band.value,
            safety_gate_tripped=int(gate.triggered),
            gate_reason=(",".join(gate.reasons) or None),
            inputs_snapshot=json.dumps(inputs_snapshot),
            model=model,
            constitution_version=profile.constitution_version,
            created_at=now_sofia().isoformat(),
        )
    )
    session.execute(
        update(DailyMetrics)
        .where(DailyMetrics.date == date_str)
        .values(readiness_score=readiness.score, band=readiness.band.value)
    )
    return brief


# --------------------------------------------------------------------------- #
# DeriveSessionNode — expand picks, resolve the dayType, macros, intake (E7·P2/E8·P3).
# --------------------------------------------------------------------------- #
def resolve_day_type(out_day_type: DayType | None, card: WorkoutCard) -> DayType:
    """The guarded daily ``dayType`` (CARDS §0; LLM §1.1) fed to the macros.

    Defaults to the card's ``CARD_META[card].day_type`` when the LLM omitted one, then
    **floors at ``hard``** for a card that ``floors_day_type_hard`` (a hard/long card —
    the LLM may fuel *up* but never *under-fuel*). The floor predicate is **E7·P1's**,
    never re-derived. ``ValidateSessionNode`` re-checks the floor over the LLM's raw
    ``dayType`` (the two agree because both use ``floors_day_type_hard``). Pure, total.
    """
    day_type = out_day_type or CARD_META[card].day_type
    if floors_day_type_hard(card) and day_type is not DayType.hard:
        return DayType.hard
    return day_type


def derive_intake_summary(
    yesterday_row: DailyMetrics | None, target: MacroFocus
) -> IntakeSummary | None:
    """Yesterday's logged intake vs the day's target (MODELS ``IntakeSummary``; epic R4).

    From yesterday's ``daily_metrics`` nutrition columns build an ``IntakeSummary`` with
    ``vsTarget`` = ``{ caloriesPct = kcal_in ÷ target.caloriesKcal, proteinHit =
    protein_in_g ≥ target.proteinG }``. Returns ``None`` when nothing was logged (the row
    absent or every nutrition column null). Pure.
    """
    if yesterday_row is None:
        return None
    kcal = yesterday_row.kcal_in
    protein = yesterday_row.protein_in_g
    carbs = yesterday_row.carbs_in_g
    fat = yesterday_row.fat_in_g
    fiber = yesterday_row.fiber_in_g
    water = yesterday_row.water_in_l
    if all(v is None for v in (kcal, protein, carbs, fat, fiber, water)):
        return None

    calories_pct = (
        round(kcal / target.calories_kcal, 2)
        if kcal is not None and target.calories_kcal
        else 0.0
    )
    protein_hit = protein is not None and protein >= target.protein_g
    return IntakeSummary(
        date=date.fromisoformat(yesterday_row.date),
        calories_kcal=round(kcal) if kcal is not None else None,
        protein_g=round(protein) if protein is not None else None,
        carbs_g=round(carbs) if carbs is not None else None,
        fat_g=round(fat) if fat is not None else None,
        fiber_g=round(fiber) if fiber is not None else None,
        water_l=water,
        vs_target=IntakeVsTarget(calories_pct=calories_pct, protein_hit=protein_hit),
    )


def _llm_output(task_context: TaskContext):
    """The ``DailyBriefLLMOutput`` the AgentNode (``TuneSessionNode``) saved.

    Read by class name so a test can seed ``ctx.nodes["TuneSessionNode"]`` directly with
    a hand-built output (no agent).
    """
    output = task_context.nodes.get(TuneSessionNode.__name__)
    if output is None:
        raise ValueError("TuneSessionNode output missing — node order is wrong")
    return output


class DeriveSessionNode(Node):
    """Expand the LLM picks → ``SessionBlock``s + resolve macros + yesterday's intake.

    The derive-don't-emit node on the **clean** LLM path: reads the ``DailyBriefLLMOutput``
    (``TuneSessionNode``) + the live ``Profile`` + the open session, (1) expands ``session``
    and each ``alternatives`` pick via ``expand_session`` (E7·P2 — every card-derived field
    from ``CARD_META``), (2) resolves the guarded ``dayType`` (``resolve_day_type`` — default
    + fuel-floor), (3) computes the ``MacroFocus`` grams from it (``compute_macro_focus``,
    E8·P3), and (4) derives yesterday's ``IntakeSummary`` from ``daily_metrics`` — and
    ``save_output``s the same shape ``SafetyRestNode`` produces, so the persist node reads
    one shape on both paths. Runs **only** on the clean path (the gated path persists in
    ``SafetyRestNode``). Computes nothing by hand beyond the two thin helpers above.
    """

    class OutputType(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)

        session: SessionBlock
        alternatives: list[SessionBlock]
        skip_ok: bool
        day_type: DayType
        macro_focus: MacroFocus
        narrative: list[NarrativeSection]
        intake_yesterday: IntakeSummary | None = None

    async def process(self, task_context: TaskContext) -> TaskContext:
        session = _session_of(task_context)
        event: DailyAdjusterEvent = task_context.event
        out = _llm_output(task_context)
        profile = load_profile()

        session_block = expand_session(out.session, profile)
        alternatives = [expand_session(pick, profile) for pick in out.alternatives]
        day_type = resolve_day_type(out.day_type, out.session.card)
        macro_focus = compute_macro_focus(
            day_type=day_type,
            weight_kg=_live_weight(_metrics_row(session, event.date), profile),
            nutrition=profile.nutrition,
            athlete=profile.athlete,
        )
        intake_yesterday = derive_intake_summary(
            _metrics_row(session, event.date - timedelta(days=1)), macro_focus
        )
        self.save_output(
            self.OutputType(
                session=session_block,
                alternatives=alternatives,
                skip_ok=out.skip_ok,
                day_type=day_type,
                macro_focus=macro_focus,
                narrative=list(out.narrative),
                intake_yesterday=intake_yesterday,
            )
        )
        return task_context
