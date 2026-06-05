"""`POST /brief/daily` — the authed daily-brief get-or-generate endpoint (E11·P3 TASK-002).

The thin HTTP shell over the TASK-001 get-or-generate service: it gates auth, resolves the
period key (default = the current Europe/Sofia date, via `period_date(now_sofia(clock))` —
never a fixed offset; ARCHITECTURE §4), runs the service behind an injected
`DailyBriefGenerator` (whose default runs the E11·P2 `DAILY_ADJUSTER` workflow through the
request session), and assembles the `{ data, narrative }` `DailyBrief` envelope with
`date`/`generatedAt`/`cached`/`constitutionVersion` set and
`readiness`/`safetyGate`/`intakeYesterday` carried through.

A **tripped safety gate** is served as a normal `DailyBrief` (`200`, `safetyGate.triggered=
true`, the code narrative, the override session, empty `alternatives`) — never an error
(epic §1/§4). An in-engine **failure** surfaces as `BriefGenerationError(code=…)`; the route
catches **nothing** and lets it reach the shared route-layer handler in `app/api/errors.py`
(registered once, shared with `POST /brief/weekly`). Because the service commits only after a
successful generate, a failed run caches no `suggestions` row.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date as date_type
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth import require_auth
from app.api.schemas.daily import DailyBrief, DailyBriefData, DailyBriefRequest
from app.core.daily_adjuster import DailyAdjuster, DailyAdjusterEvent
from app.core.task_context import TaskContext
from app.core.time import get_clock, now_sofia, period_date
from app.database.engine import get_session
from app.services.daily_brief import (
    DailyBriefGenerator,
    GeneratedDailyBrief,
    get_or_generate_daily,
    lookup_suggestion,
)

router = APIRouter()


def _adapt(out_ctx: TaskContext) -> GeneratedDailyBrief:
    """Adapt the workflow's terminal output → `GeneratedDailyBrief`.

    The terminal is `PersistSuggestionNode` (clean path) or `SafetyRestNode` (gated path);
    both `save_output` the `{ data, narrative }` brief (the same `payload` written to the
    `suggestions` row). The readiness/gate snapshot fields are read off `data` for the
    bundle; `generated_at`/`constitution_version` are left unset and the route re-reads the
    committed row (the authoritative persisted values).
    """
    terminal = out_ctx.nodes.get("PersistSuggestionNode") or out_ctx.nodes.get(
        "SafetyRestNode"
    )
    brief = terminal.brief
    data = brief["data"]
    readiness = data.get("readiness") or {}
    gate = data.get("safetyGate") or {}
    return GeneratedDailyBrief(
        data=data,
        narrative=brief["narrative"],
        readiness_score=readiness.get("score"),
        band=readiness.get("band"),
        safety_gate_tripped=int(bool(gate.get("triggered"))),
        gate_reason=(",".join(gate.get("reasons", [])) or None),
    )


class _DailyAdjusterGenerator:
    """The default `DailyBriefGenerator` — runs the E11·P2 `DAILY_ADJUSTER` workflow.

    Closes over the **request session**: it builds `ctx = TaskContext(event=
    DailyAdjusterEvent(date=…), metadata={"session": session})` and runs
    `DailyAdjuster().run(context=ctx)` — **not** `run(event)`, which would build a *fresh*
    `TaskContext` and drop the session. The workflow's `PersistSuggestionNode` /
    `SafetyRestNode` writes the `suggestions` row + the `daily_metrics` snapshot through that
    session (no commit) and derives `intakeYesterday` into the `payload`; this generator
    adapts the terminal `save_output` to a `GeneratedDailyBrief`.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def __call__(self, date: str) -> GeneratedDailyBrief:
        event = DailyAdjusterEvent(date=date_type.fromisoformat(date))
        ctx = TaskContext(event=event, metadata={"session": self._session})
        out_ctx = DailyAdjuster().run(context=ctx)
        return _adapt(out_ctx)


def get_daily_generator(
    session: Session = Depends(get_session),
) -> DailyBriefGenerator:
    """Provider for the E11·P2 `DAILY_ADJUSTER` runner, bound to the request session.

    Tests override this with a stub (mirroring `PersistSuggestionNode`) so the route is
    exercised without a live LLM; the real runner swaps in with **no** route edit.
    """
    return _DailyAdjusterGenerator(session)


@router.post("/brief/daily", response_model=DailyBrief)
def daily_brief(
    body: DailyBriefRequest,
    refresh: bool = False,
    _: str = Depends(require_auth),
    session: Session = Depends(get_session),
    generate: DailyBriefGenerator = Depends(get_daily_generator),
    clock: Callable[[], datetime] = Depends(get_clock),
) -> DailyBrief:
    """Get-or-generate the daily brief for the resolved date; assemble `DailyBrief`.

    Resolves the period key (`body.date` or the current Europe/Sofia date), runs the
    get-or-generate service (which commits on a miss/refresh), and assembles the
    `{ data, narrative }` envelope with `date`/`generatedAt`/`cached`/`constitutionVersion`
    set. A tripped safety gate is served `200` as a normal brief (never raised).
    """
    key = body.date.isoformat() if body.date else period_date(now_sofia(clock))

    brief, cached = get_or_generate_daily(session, key, refresh=refresh, generate=generate)

    # `generatedAt`/`constitutionVersion` are stamped onto the row by the workflow's
    # PersistSuggestionNode/SafetyRestNode. A hit deserialises them off the row; a fresh
    # miss's save_output doesn't expose them, so re-read the now-committed row to surface the
    # authoritative persisted values (never minted here).
    generated_at = brief.generated_at
    constitution_version = brief.constitution_version
    if not cached:
        committed = lookup_suggestion(session, key)
        if committed is not None:
            generated_at = generated_at or committed.created_at
            constitution_version = constitution_version or committed.constitution_version

    data = DailyBriefData.model_validate(
        {
            **brief.data,
            "date": key,
            "generatedAt": generated_at,
            "cached": cached,
            "constitutionVersion": constitution_version,
        }
    )
    return DailyBrief(data=data, narrative=brief.narrative)
