"""`POST /brief/weekly` — the authed weekly-brief get-or-generate endpoint (E10·P3 TASK-002).

The thin HTTP shell over the TASK-001 get-or-generate service: it gates auth, resolves the
period key (default = the current Europe/Sofia ISO week, derived through the E2·P1
``iso_week`` helper over the ``health.py`` injectable clock — never a fixed offset;
ARCHITECTURE §4), runs the service behind an injected ``WeeklyPlanGenerator`` (whose default
runs the E10·P2 ``WEEKLY_PLANNER`` workflow through the request session), assembles the
``{ data, narrative }`` ``WeeklyPlan`` envelope with ``weekStart``/``generatedAt``/``cached``
set, and — **only after** the service's ``commit`` succeeds — applies the staged
``profile.yaml`` rewrite the workflow's ``PersistPlanNode`` parked under
``PENDING_PROFILE_WRITE_KEY`` (the durable file write is a non-transactional side effect, so
it must follow the DB commit; a commit failure leaves the file untouched — DECISIONS D3 in
the E10·P2 plan; the implement-plan brief's load-bearing ordering).

A workflow failure surfaces as ``BriefGenerationError(code=…)``; the route catches **nothing**
and lets it reach the route-layer handler registered in ``app/api/errors.py`` (E9 leaves the
HTTP mapping to E10/E11; the E1 catch-all would otherwise mask it as ``internal_error`` —
codex round-1 #2). Because the service commits only after a successful generate, a failed run
caches no ``Plans`` row.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.api.schemas.weekly import WeeklyBriefRequest, WeeklyPlan, WeeklyPlanData
from app.core.profile import Profile, write_profile
from app.core.task_context import TaskContext
from app.core.time import get_clock, iso_week, now_sofia
from app.core.weekly_planner import (
    PENDING_PROFILE_WRITE_KEY,
    WeeklyPlanner,
    WeeklyPlannerEvent,
)
from app.database.engine import get_session
from app.services.weekly_plan import (
    GeneratedWeeklyPlan,
    WeeklyPlanGenerator,
    get_or_generate_weekly,
    lookup_plan,
)

router = APIRouter()


def _week_monday(iso_week_key: str) -> date:
    """The Monday (``date``) of an ISO-week key (``YYYY-Www``), year-boundary-safe.

    Safe to call unguarded: the request validator already parsed the key (and the default
    key comes from ``iso_week(...)``), so this never ``ValueError``s → no ``500`` here
    (codex round-1 #4).
    """
    year_str, _, week_str = iso_week_key.partition("-W")
    return date.fromisocalendar(int(year_str), int(week_str), 1)


class _WeeklyPlannerGenerator:
    """The default ``WeeklyPlanGenerator`` — runs the E10·P2 ``WEEKLY_PLANNER`` workflow.

    Closes over the **request session**: it builds ``ctx = TaskContext(event=
    WeeklyPlannerEvent(...), metadata={"session": session})`` and runs
    ``WeeklyPlanner().run_async(context=ctx)`` — **not** ``run_async(event)``, which would
    build a *fresh* ``TaskContext`` and drop the session (E10·P2). The workflow's
    ``PersistPlanNode`` writes the ``Plans`` row through that session (no commit) and parks
    any proposed ``profile.yaml`` rewrite under ``PENDING_PROFILE_WRITE_KEY``; this
    generator surfaces that staged ``Profile`` on ``pending_profile`` so the route applies
    it **after** the service's commit (the file write must follow the DB commit — DECISIONS
    D3). It adapts the ``PersistPlanNode`` ``save_output`` (the structured ``data`` + the
    narrative + snapshots) to a ``GeneratedWeeklyPlan``.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self.pending_profile: Profile | None = None

    def __call__(self, iso_week_key: str) -> GeneratedWeeklyPlan:
        monday = _week_monday(iso_week_key)
        event = WeeklyPlannerEvent(anchor=monday, iso_week=iso_week_key, week_start=monday)
        ctx = TaskContext(event=event, metadata={"session": self._session})
        out_ctx = WeeklyPlanner().run(context=ctx)
        self.pending_profile = out_ctx.metadata.get(PENDING_PROFILE_WRITE_KEY)
        return _adapt(out_ctx)


def _adapt(out_ctx: TaskContext) -> GeneratedWeeklyPlan:
    """Adapt the workflow's terminal ``PersistPlanNode`` output → ``GeneratedWeeklyPlan``.

    ``PersistPlanNode`` ``save_output``s the structured ``data`` dict (budgets + expanded
    ``core``/``extras`` + targets + nutrition + ``constantsRecomputed``/``weekStart``/
    ``isoWeek``); the narrative is the LLM ``GeneratePlanNode`` output (stored in
    ``plans.rationale``, not in ``data``). ``generated_at`` is the row's ``created_at``,
    re-read by the service's hit path; on a fresh miss the response stamps it from the
    structured run via the wire model's own validation, so it is left unset here (the
    cache round-trip surfaces it on subsequent hits).
    """
    data = out_ctx.nodes["PersistPlanNode"].data
    llm_output = out_ctx.nodes.get("GeneratePlanNode")
    narrative = [n.model_dump(mode="json") for n in getattr(llm_output, "narrative", [])]
    return GeneratedWeeklyPlan(data=data, narrative=narrative)


def get_weekly_generator(
    session: Session = Depends(get_session),
) -> WeeklyPlanGenerator:
    """Provider for the E10·P2 ``WEEKLY_PLANNER`` runner, bound to the request session.

    Tests override this with a stub (mirroring ``PersistPlanNode``) so E10·P3 ships/tests
    without the workflow and the real runner swaps in with **no** route edit.
    """
    return _WeeklyPlannerGenerator(session)


@router.post("/brief/weekly", response_model=WeeklyPlan)
def weekly_brief(
    body: WeeklyBriefRequest,
    refresh: bool = False,
    _: str = Depends(require_auth),
    session: Session = Depends(get_session),
    generate: WeeklyPlanGenerator = Depends(get_weekly_generator),
    clock: Callable[[], datetime] = Depends(get_clock),
) -> WeeklyPlan:
    """Get-or-generate the weekly brief for the resolved ISO week; assemble ``WeeklyPlan``.

    Resolves the period key (``body.iso_week`` or the current Europe/Sofia week), runs the
    get-or-generate service (which commits on a miss/refresh), applies the staged
    ``profile.yaml`` rewrite **only after** that commit succeeded, and assembles the
    ``{ data, narrative }`` envelope with ``weekStart``/``generatedAt``/``cached`` set.
    """
    key = body.iso_week or iso_week(now_sofia(clock))

    plan, cached = get_or_generate_weekly(session, key, refresh=refresh, generate=generate)

    # ── Apply the staged profile.yaml rewrite AFTER the commit (load-bearing ordering) ──
    # The workflow's PersistPlanNode parks the proposed Profile under
    # PENDING_PROFILE_WRITE_KEY instead of writing the file in-node, because the durable
    # file write is a non-transactional side effect: it must happen ONLY after the DB
    # commit succeeds, or a commit failure would advance profile.yaml for a plan whose row
    # rolled back. On a cache hit the workflow never ran (no pending write); on a miss/
    # refresh the service already committed before returning, so applying it here is
    # post-commit. A commit failure raises out of get_or_generate_weekly above, so this is
    # never reached and the file stays byte-identical (DECISIONS D3).
    if not cached:
        pending = getattr(generate, "pending_profile", None)
        if pending is not None:
            write_profile(pending)

    # `generatedAt` is the row's `created_at` stamped by PersistPlanNode. A hit deserialises
    # it off the row; a fresh miss's `save_output` doesn't expose it, so re-read the now-
    # committed row to surface the authoritative persisted timestamp (never minted here).
    generated_at = plan.generated_at
    if generated_at is None:
        committed = lookup_plan(session, key)
        generated_at = committed.created_at if committed is not None else None

    week_start = _week_monday(key)
    data = WeeklyPlanData.model_validate(
        {
            **plan.data,
            "isoWeek": key,
            "weekStart": week_start,
            "generatedAt": generated_at,
            "cached": cached,
        }
    )
    return WeeklyPlan(data=data, narrative=plan.narrative)
