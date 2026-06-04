"""Pure, LLM-free output validators for the card system (E7·P3).

``validate_weekly(out, ctx)`` and ``validate_daily(out, ctx)`` police a weekly
plan / daily session pick against ``CARD_META`` (E7·P1) and a computed
``ValidationContext``, returning a ``list[Violation]`` — one ``Violation`` per
broken invariant, an **empty list** for a clean plan/session. They encode exactly
the CARDS.md §4 / LLM.md §4 invariant families and **nothing else** — no
food/drug/health-condition layer (epic R7; CARDS.md §2 is LLM context, weighed by
the model from the system prompt, not a code-enforced check here).

The validators **return** the full list and **never raise** — acting on a hard
violation (the LLM-retry on the wired agent) is E9·P2's job (LLM.md §4; epic §7).
This is a pure ``app/core/`` module: it imports only ``enum``/``dataclasses`` +
``app.core.cards``/``app.core.enums``; no FastAPI/SQLAlchemy/PydanticAI/profile
import, no I/O.

TASK-001 ships the value-type foundations below; TASK-002/TASK-003 add the two
validators + the shared dose helper.
"""

from dataclasses import dataclass, field
from enum import Enum

from app.core.enums import ReadinessBand, WorkoutCard


class Severity(str, Enum):
    """A ``Violation``'s severity (LLM.md §4).

    A **hard** violation drives the LLM retry on the wired agent (E9·P2);
    ``soft`` is advisory (forward use — every E7·P3 invariant is currently
    ``hard``). The repo ``class X(str, Enum)`` convention
    (``app/api/errors.py:ErrorCode``).
    """

    hard = "hard"
    soft = "soft"


@dataclass(frozen=True)
class Violation:
    """One broken invariant (LLM.md §4 ``Violation {rule, message, severity}``).

    ``rule`` is the **stable machine key** (one per invariant family, pinned in
    ``WEEKLY_RULES``/``DAILY_RULES``) that E9's retry payload and E10/E11's
    surfacing key on; ``message`` is human-readable and names the offending
    card/day/value; ``severity`` defaults to ``hard`` (Decision 1). Frozen +
    immutable, matching the ``app/core/`` value-type convention.
    """

    rule: str
    message: str
    severity: Severity = Severity.hard


# --------------------------------------------------------------------------
# The closed set of emittable `rule` keys — one per invariant family. Pinned,
# greppable, and asserted exact in the tests so E9's retry-payload contract and
# E10/E11's surfacing keys can't drift. `dose_out_of_band` is shared by both
# validators (one dose helper, one key — Decision).
# --------------------------------------------------------------------------
#: Every `rule` `validate_weekly` can emit.
WEEKLY_RULES: frozenset[str] = frozenset(
    {
        "hard_day_count",
        "hard_day_spacing",
        "hard_run_after_boxing",
        "strength_count",
        "core_size",
        "extras_size",
        "long_run_count",
        "quality_run_mismatch",
        "deload_hard_cap",
        "dose_out_of_band",
    }
)

#: Every `rule` `validate_daily` can emit.
DAILY_RULES: frozenset[str] = frozenset(
    {
        "card_not_in_plan",
        "red_requires_rest_card",
        "amber_full_intensity",
        "knee_impact_blocked",
        "dose_out_of_band",
        "day_type_below_floor",
        "too_many_alternatives",
    }
)


@dataclass(frozen=True)
class WeeklyBudgets:
    """The code-computed weekly budgets the weekly validator reads (MODELS
    ``WeeklyBudgets`` — ``hardDays``/``strengthSessions``/``longRunKm``/``deload``).

    Defined locally (Decision 2) so this phase depends only on E7·P1, not on the
    unbuilt E8 that computes the real values; the field names mirror MODELS so
    E9's adapter is a thin field copy.
    """

    hard_days: int
    strength_sessions: int
    long_run_km: float
    deload: bool


@dataclass(frozen=True)
class ValidationContext:
    """The computed inputs both validators read (Decision 2).

    A local, typed, frozen container so the validators stay pure and
    unit-testable in isolation; the caller (E9/E10/E11) populates it from
    already-computed values (E8 budgets/readiness, the persisted ``WeeklyPlan``'s
    cards, the live ``knee_pain``, the code-decided threshold↔VO₂ pick). **No**
    DB/HTTP/LLM read happens here.

    Weekly fields: ``budgets`` (the ``WeeklyBudgets``) and ``quality_run_pick``
    (the code-decided ``threshold``↔``vo2`` card for the week, or ``None`` when
    neither is expected). Daily fields: ``band`` (``ReadinessBand``),
    ``knee_pain`` (0–10, the §6.2 gate is ``> 3``), ``week_plan_cards`` (the
    active week's planned cards — what "card ∈ week plan" reads), and
    ``safety_gate_triggered`` (documented for the caller; when ``True`` the LLM
    was skipped and ``validate_daily`` is simply not called — see Out of Scope).
    """

    # weekly
    budgets: WeeklyBudgets
    quality_run_pick: WorkoutCard | None = None
    # daily
    band: ReadinessBand = ReadinessBand.green
    knee_pain: int = 0
    week_plan_cards: frozenset[WorkoutCard] = field(default_factory=frozenset)
    safety_gate_triggered: bool = False
