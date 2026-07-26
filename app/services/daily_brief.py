"""The daily get-or-generate service keyed by ``date`` (E11·P3 TASK-001).

The pure, FastAPI-free core of ``POST /brief/daily``: ``lookup_suggestion`` /
``delete_suggestion`` / ``get_or_generate_daily`` over the ``suggestions`` table, keyed by
the ``UNIQUE(date)`` cache key (DB.md §4). It serves the stored brief on a **hit** (no
workflow run, no LLM — epic §4) and, on a **miss** or a ``?refresh=true``, runs the E11·P2
``DAILY_ADJUSTER`` workflow behind a one-method ``DailyBriefGenerator`` ``Protocol`` seam,
then ``commit``s.

**Persistence ownership:** the E11·P2 workflow's ``PersistSuggestionNode`` (or, on a tripped
gate, ``SafetyRestNode``) writes the one ``suggestions`` row on the metadata session
**without committing** — "the endpoint owns the transaction … E11·P3 commits" — and snapshots
``readiness_score``/``band`` onto ``daily_metrics``; its ``DeriveSessionNode`` derives
``intakeYesterday`` into the ``payload`` (``{ data, narrative }``). So this service adds
**no** second writer (a duplicate insert would trip ``UNIQUE(date)``), derives **no**
``intakeYesterday``, and owns only **lookup / refresh-delete / commit** — carrying the
workflow-produced ``intakeYesterday`` through and round-tripping it on a hit. ``?refresh=true``
is **delete-then-generate** (DB.md §4 verbatim), not an in-place upsert: the prior delete +
the workflow's insert + the single ``commit`` are one transaction, so the row count stays at
one — except when the stored ``inputs_snapshot`` equals the caller-supplied ``current_inputs``
fingerprint, in which case the refresh is a **no-op cache hit** (identical deterministic
inputs ⇒ identical LLM prompt ⇒ regeneration would be sampling noise; 2026-07-26 incident). A **gate-tripped** brief is a normal ``GeneratedDailyBrief`` (``triggered=True``) served
like any other — **never** an error (the ``BriefGenerationError`` mapping is the route's, for
in-engine *failures* only).

Pure ``app/services`` module: no FastAPI/HTTP import, no workflow-node/agent/LLM import, no
clock, no ``daily_metrics`` read. It imports only ``Suggestions`` (E2) + ``select``/``delete``.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database.models import Suggestions


class GeneratedDailyBrief(BaseModel):
    """The bundle the E11·P2 workflow's ``save_output`` exposes and this service serves.

    ``data`` is the structured ``DailyBrief.data`` sub-object as a JSON-able mapping
    (``date``/``readiness``/``safetyGate``/``session``/``alternatives``/``skipOk``/
    ``macroFocus``/``intakeYesterday`` — ``intakeYesterday`` derived by the E11·P2
    ``DeriveSessionNode``) — exactly what the workflow serialises into ``payload``'s
    ``data``. ``narrative`` is the LLM/code coach prose (the ``payload``'s ``narrative``).
    The snapshot fields mirror the nullable ``suggestions`` columns plus ``generated_at``
    (the row's ``created_at``, an ISO-8601 string the workflow stamps via ``now_sofia()``).
    The route (TASK-002) maps this onto the camelCase ``DailyBrief`` wire envelope, adding
    the endpoint-stamped ``cached``.
    """

    data: dict[str, Any]
    narrative: list[dict[str, Any]]
    readiness_score: int | None = None
    band: str | None = None
    safety_gate_tripped: int | None = None
    gate_reason: str | None = None
    model: str | None = None
    constitution_version: str | None = None
    generated_at: str | None = None


class DailyBriefGenerator(Protocol):
    """The E11·P2 ``DAILY_ADJUSTER`` runner seam — ``(date) -> GeneratedDailyBrief``.

    E11·P2 supplies the concrete runner via the route provider: it builds a
    ``TaskContext(event=DailyAdjusterEvent(date=…), metadata={"session": session})``, runs
    ``DailyAdjuster().run(context=ctx)`` (the workflow's ``PersistSuggestionNode`` /
    ``SafetyRestNode`` writes the ``suggestions`` row + the ``daily_metrics`` snapshot
    through that **same** session — no commit, and derives ``intakeYesterday`` into the
    ``payload``), and adapts the ``save_output`` result to this bundle. The service calls
    ``generate`` **only** on a miss/refresh; tests mock it.
    """

    def __call__(self, date: str) -> GeneratedDailyBrief: ...


def lookup_suggestion(session: Session, date: str) -> Suggestions | None:
    """The one ``suggestions`` row for ``date`` (by the ``UNIQUE(date)`` key), or ``None``."""
    return session.scalars(select(Suggestions).where(Suggestions.date == date)).one_or_none()


def delete_suggestion(session: Session, date: str) -> bool:
    """Delete the ``suggestions`` row for ``date``; return whether a row was removed.

    The ``?refresh=true`` first step (DB.md §4 "deletes the row for the period and
    regenerates"). Does **not** commit — the caller owns the transaction.
    """
    result = session.execute(delete(Suggestions).where(Suggestions.date == date))
    return result.rowcount > 0


def _deserialize(row: Suggestions) -> GeneratedDailyBrief:
    """Parse a stored ``suggestions`` row back into the **same** ``GeneratedDailyBrief`` a
    miss returns, so a cache hit round-trips to an identical shape.

    ``payload`` carries the ``{ data, narrative }`` brief (``data`` incl.
    ``intakeYesterday``); the snapshot columns surface the readiness/gate/model values and
    ``created_at`` surfaces as ``generated_at``. A gate-tripped row round-trips with
    ``safetyGate.triggered=true`` (it is a normal brief, never raised).
    """
    payload = json.loads(row.payload) if row.payload else {}
    return GeneratedDailyBrief(
        data=payload.get("data", {}),
        narrative=payload.get("narrative", []),
        readiness_score=row.readiness_score,
        band=row.band,
        safety_gate_tripped=row.safety_gate_tripped,
        gate_reason=row.gate_reason,
        model=row.model,
        constitution_version=row.constitution_version,
        generated_at=row.created_at,
    )


def _refresh_is_noop(row: Suggestions, current_inputs: dict[str, Any] | None) -> bool:
    """Whether a ``?refresh=true`` over ``row`` may serve the cache instead of regenerating.

    True iff the caller supplied the freshly recomputed deterministic-inputs fingerprint
    (``compute_inputs_snapshot`` — the same builder ``_persist_brief`` stored the row's
    ``inputs_snapshot`` through) and it equals the stored one: an equal fingerprint means an
    identical LLM prompt, so a regeneration could only differ by sampling noise — the
    2026-07-26 incident, where a client force-refreshing on every open flipped the session
    pick with zero input change. Anything unparseable / missing / pre-guard (thin legacy
    snapshots) compares unequal → regenerate honestly.
    """
    if current_inputs is None or not row.inputs_snapshot:
        return False
    try:
        stored = json.loads(row.inputs_snapshot)
    except (TypeError, ValueError):
        return False
    return stored == current_inputs


def get_or_generate_daily(
    session: Session,
    date: str,
    *,
    refresh: bool,
    generate: DailyBriefGenerator,
    current_inputs: dict[str, Any] | None = None,
) -> tuple[GeneratedDailyBrief, bool]:
    """Get-or-generate the daily brief for ``date``; return ``(brief, cached)``.

    * ``refresh=True`` → look the day up first: when a row exists and its stored
      ``inputs_snapshot`` equals ``current_inputs`` (the route-recomputed fingerprint of
      every deterministic feed the LLM reads), the refresh is a **no-op** — serve the
      stored row ``(brief, True)`` and never touch the LLM (regenerating over identical
      inputs could only produce sampling noise; 2026-07-26). Otherwise
      ``delete_suggestion`` (delete-then-generate; DB.md §4) and run the miss path.
      ``current_inputs=None`` (a caller that computed nothing) always regenerates — the
      pre-guard behaviour.
    * otherwise look the day up — on a **hit** deserialise the stored row and return
      ``(brief, True)`` **without** calling ``generate`` (no workflow run / LLM on a hit;
      epic §4). A gate-tripped row round-trips as a normal brief, never raised.
    * on a **miss** (or after a refresh delete): ``generate(date)`` runs the workflow, whose
      ``PersistSuggestionNode``/``SafetyRestNode`` has **added** the ``suggestions`` row to
      *this* session (no commit) + snapshotted ``daily_metrics``; then ``session.commit()``
      (the endpoint owns the transaction) and return ``(brief, False)``.

    This service writes **no** ``suggestions`` row itself — the workflow is the sole writer
    (a refresh's prior delete + that insert + this single commit are one transaction, so
    ``UNIQUE(date)`` is never tripped under normal flow). A failed ``generate`` propagates
    **before** the commit, so a failed run caches nothing. The service stays pure: the
    fingerprint is a **value** computed by the caller (the route, via
    ``compute_inputs_snapshot``) — no ``daily_metrics``/profile read happens here.
    """
    if refresh:
        row = lookup_suggestion(session, date)
        if row is not None and _refresh_is_noop(row, current_inputs):
            return _deserialize(row), True
        delete_suggestion(session, date)
    else:
        row = lookup_suggestion(session, date)
        if row is not None:
            return _deserialize(row), True

    generated = generate(date)
    session.commit()
    return generated, False
