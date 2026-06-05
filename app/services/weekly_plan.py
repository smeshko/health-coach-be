"""The weekly get-or-generate service keyed by ``iso_week`` (E10·P3 TASK-001).

The pure, FastAPI-free core of ``POST /brief/weekly``: ``lookup_plan`` / ``delete_plan`` /
``get_or_generate_weekly`` over the ``plans`` table, keyed by the ``UNIQUE(iso_week)`` cache
key (DB.md §4). It serves the stored brief on a **hit** (no workflow run, no LLM — epic §4)
and, on a **miss** or a ``?refresh=true``, runs the E10·P2 ``WEEKLY_PLANNER`` workflow
behind a one-method ``WeeklyPlanGenerator`` ``Protocol`` seam, then ``commit``s.

**Persistence ownership (codex round-1 #1; DECISIONS Decision 2):** the E10·P2 workflow's
``PersistPlanNode`` writes the one ``Plans`` row on the metadata session **without
committing** — "the endpoint owns the transaction … E10·P3 commits". So this service adds
**no** second writer (a duplicate insert would trip ``UNIQUE(iso_week)`` once the real
runner is wired); it owns only **lookup / refresh-delete / commit**. ``?refresh=true`` is
**delete-then-generate** (DB.md §4 verbatim), not an in-place upsert (DECISIONS Decision 1):
the prior delete + the workflow's insert + the single ``commit`` are one transaction, so the
row count stays at one.

Pure ``app/services`` module: no FastAPI/HTTP import, no workflow-node/agent/LLM import, no
clock (timestamps — ``created_at``/``generated_at`` — are E10·P2's ``PersistPlanNode``; the
route, not this service, runs the workflow). It imports only ``Plans`` (E2) +
``select``/``delete`` (SQLAlchemy).
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database.models import Plans


class GeneratedWeeklyPlan(BaseModel):
    """The bundle the E10·P2 workflow's ``save_output`` exposes and this service serves.

    ``data`` is the structured ``WeeklyPlan.data`` sub-objects as a JSON-able mapping
    (``budgets``/``core``/``extras``/``targets``/``nutrition``/``constantsRecomputed`` +
    the endpoint-stamped ``isoWeek``/``weekStart``) — exactly what ``PersistPlanNode``
    serialises into ``plans.payload``. ``narrative`` is the LLM coach prose (stored in
    ``plans.rationale``). The snapshot fields mirror the nullable ``plans`` columns
    (``rationale``/``inputs_snapshot``/``model``/``constitution_version``) plus
    ``generated_at`` (the row's ``created_at``, an ISO-8601 string ``PersistPlanNode``
    stamps via ``now_sofia()``). The route (TASK-002) maps this onto the camelCase
    ``WeeklyPlan`` wire envelope, adding ``cached``.
    """

    data: dict[str, Any]
    narrative: list[dict[str, Any]]
    rationale: str | None = None
    inputs_snapshot: Any | None = None
    model: str | None = None
    constitution_version: str | None = None
    generated_at: str | None = None


class WeeklyPlanGenerator(Protocol):
    """The E10·P2 ``WEEKLY_PLANNER`` runner seam — ``(iso_week) -> GeneratedWeeklyPlan``.

    E10·P2 supplies the concrete runner via the route provider: it builds a
    ``TaskContext(event=WeeklyPlannerEvent(...), metadata={"session": session})``, runs
    ``WeeklyPlanner().run_async(context=ctx)`` (the workflow's ``PersistPlanNode`` writes
    the ``Plans`` row through that **same** session — no commit), and adapts the
    ``save_output`` result to this bundle. This phase mocks it in tests. The service calls
    ``generate`` **only** on a miss/refresh.
    """

    def __call__(self, iso_week: str) -> GeneratedWeeklyPlan: ...


def lookup_plan(session: Session, iso_week: str) -> Plans | None:
    """The one ``plans`` row for ``iso_week`` (by the ``UNIQUE(iso_week)`` key), or ``None``."""
    return session.scalars(select(Plans).where(Plans.iso_week == iso_week)).one_or_none()


def delete_plan(session: Session, iso_week: str) -> bool:
    """Delete the ``plans`` row for ``iso_week``; return whether a row was removed.

    The ``?refresh=true`` first step (DB.md §4 "deletes the row for the period and
    regenerates"). Does **not** commit — the caller owns the transaction.
    """
    result = session.execute(delete(Plans).where(Plans.iso_week == iso_week))
    return result.rowcount > 0


def _deserialize(row: Plans) -> GeneratedWeeklyPlan:
    """Parse a stored ``plans`` row back into the **same** ``GeneratedWeeklyPlan`` a miss
    returns, so a cache hit round-trips to an identical shape (PLAN risk: round-trip drift).

    ``payload`` carries the structured ``data``; ``rationale`` carries the narrative JSON
    (split back out — ``plans`` has no narrative column; RESEARCH Uncertainty);
    ``inputs_snapshot`` is parsed back to its mapping; ``created_at`` surfaces as
    ``generated_at``.
    """
    narrative = json.loads(row.rationale) if row.rationale else []
    inputs_snapshot = json.loads(row.inputs_snapshot) if row.inputs_snapshot else None
    return GeneratedWeeklyPlan(
        data=json.loads(row.payload),
        narrative=narrative,
        rationale=row.rationale,
        inputs_snapshot=inputs_snapshot,
        model=row.model,
        constitution_version=row.constitution_version,
        generated_at=row.created_at,
    )


def get_or_generate_weekly(
    session: Session,
    iso_week: str,
    *,
    refresh: bool,
    generate: WeeklyPlanGenerator,
) -> tuple[GeneratedWeeklyPlan, bool]:
    """Get-or-generate the weekly brief for ``iso_week``; return ``(plan, cached)``.

    * ``refresh=True`` → ``delete_plan`` first (delete-then-generate; DB.md §4) and skip the
      lookup, then run the miss path.
    * otherwise look the week up — on a **hit** deserialise the stored row and return
      ``(plan, True)`` **without** calling ``generate`` (no workflow run / LLM on a hit;
      epic §4).
    * on a **miss** (or after a refresh delete): ``generate(iso_week)`` runs the workflow,
      whose ``PersistPlanNode`` has **added** the ``Plans`` row to *this* session (no
      commit); then ``session.commit()`` (the endpoint owns the transaction) and return
      ``(plan, False)``.

    This service writes **no** ``Plans`` row itself — the workflow's ``PersistPlanNode`` is
    the sole writer (a refresh's prior delete + that insert + this single commit are one
    transaction, so ``UNIQUE(iso_week)`` is never tripped under normal flow). A failed
    ``generate`` propagates **before** the commit, so a failed run caches nothing.
    """
    if refresh:
        delete_plan(session, iso_week)
    else:
        row = lookup_plan(session, iso_week)
        if row is not None:
            return _deserialize(row), True

    generated = generate(iso_week)
    session.commit()
    return generated, False
