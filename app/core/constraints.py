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

from app.core.cards import (
    Flag,
    downgrade_for,
    floors_day_type_hard,
    get_card,
)
from app.core.enums import DayType, ReadinessBand, WorkoutCard, Zone


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


# --------------------------------------------------------------------------
# Shared dose helper — CARDS.md §4/§1 "durationMin[Low|High] inside the card's
# dose band". One helper, one `dose_out_of_band` rule key, used by **both**
# validators (Decision: avoid two divergent dose checks).
# --------------------------------------------------------------------------
def _dose_in_band(card: WorkoutCard, low: int, high: int) -> bool:
    """Is the ``[low, high]`` dose inside ``card``'s CARD_META band?

    Valid iff ``meta.dose_min_low <= low <= high`` **and** the high fits the
    band: ``meta.dose_min_high`` of ``None`` is **open-ended** (e.g. ``long_run``
    — only the low bound applies); otherwise ``high <= meta.dose_min_high``.
    ``rest``'s ``(0, 0)`` band therefore accepts only ``low == high == 0``.
    """
    meta = get_card(card)
    if low < meta.dose_min_low or high < low:
        return False
    if meta.dose_min_high is None:
        return True
    return high <= meta.dose_min_high


def _per_pick_violations(
    pick: object,
    ctx: ValidationContext,
    allowed: frozenset[WorkoutCard],
    *,
    where: str,
) -> list[Violation]:
    """The per-pick daily checks, run over the ``session`` **and** each
    ``alternatives`` entry (Decision: alternatives are real fallback picks).

    Covers ``card_not_in_plan``, ``red_requires_rest_card`` /
    ``amber_full_intensity`` (band gating), ``knee_impact_blocked``, and
    ``dose_out_of_band``. ``where`` ("session"/"alternative") is folded into the
    message so a reader sees which pick broke.
    """
    card: WorkoutCard = pick.card  # type: ignore[attr-defined]
    meta = get_card(card)
    out: list[Violation] = []

    if card not in allowed:
        out.append(
            Violation(
                rule="card_not_in_plan",
                message=(
                    f"{where} card {card.value!r} is not in the week plan or its "
                    "allowed low-impact substitutes"
                ),
            )
        )

    if ctx.band is ReadinessBand.red and meta.day_type is not DayType.rest:
        out.append(
            Violation(
                rule="red_requires_rest_card",
                message=(
                    f"RED day requires a rest-type card; {where} card "
                    f"{card.value!r} has day_type {meta.day_type.value!r}"
                ),
            )
        )

    if ctx.band is ReadinessBand.amber and (
        card is WorkoutCard.vo2 or meta.zone is Zone.z5
    ):
        out.append(
            Violation(
                rule="amber_full_intensity",
                message=(
                    f"AMBER day forbids full vo2/z5 intensity; {where} card "
                    f"{card.value!r} is top-end"
                ),
            )
        )

    if ctx.knee_pain > 3 and Flag.impact in meta.flags:
        out.append(
            Violation(
                rule="knee_impact_blocked",
                message=(
                    f"knee_pain {ctx.knee_pain} > 3 forbids an impact card; "
                    f"{where} card {card.value!r} carries Flag.impact"
                ),
            )
        )

    low = pick.duration_min_low  # type: ignore[attr-defined]
    high = pick.duration_min_high  # type: ignore[attr-defined]
    if not _dose_in_band(card, low, high):
        out.append(
            Violation(
                rule="dose_out_of_band",
                message=(
                    f"{where} card {card.value!r} dose {low}–{high} min is outside "
                    f"its band {meta.dose_min_low}–{meta.dose_min_high}"
                ),
            )
        )

    return out


def validate_daily(out: object, ctx: ValidationContext) -> list[Violation]:
    """Police a daily LLM session pick against ``CARD_META`` + ``ctx``.

    ``out`` is a ``DailyBriefLLMOutput``-shaped value (read structurally):
    ``session`` (a slim ``SessionPick`` — ``card``/``duration_min_low``/
    ``duration_min_high``), ``alternatives`` (a list of the same), and
    ``day_type`` (the chosen ``DayType``). Returns **every** broken CARDS.md §4 /
    LLM.md §4 daily invariant as a ``Violation`` (never short-circuits, never
    raises); an empty list means a clean session.

    Per-pick checks (card-in-plan, RED/AMBER band gating, knee gate,
    dose-in-band) run over ``session`` **and** each ``alternatives`` entry.
    Whole-output checks (the ``dayType`` fuel floor and the ``alternatives``
    count) apply once, keyed off the primary ``session`` pick.
    """
    violations: list[Violation] = []

    # The allowed card set = the week plan ∪ each planned card's §3 AMBER/RED
    # downgrade substitutes (CARDS.md §3/§4; built from E7·P1's DOWNGRADE_MAP via
    # downgrade_for so it can't drift from the table).
    allowed: set[WorkoutCard] = set(ctx.week_plan_cards)
    for planned in ctx.week_plan_cards:
        dg = downgrade_for(planned)
        if dg is not None:
            allowed.update(dg.amber)
            allowed.update(dg.red)
    allowed_frozen = frozenset(allowed)

    session = out.session  # type: ignore[attr-defined]
    alternatives = list(out.alternatives)  # type: ignore[attr-defined]

    violations.extend(
        _per_pick_violations(session, ctx, allowed_frozen, where="session")
    )
    for alt in alternatives:
        violations.extend(
            _per_pick_violations(alt, ctx, allowed_frozen, where="alternative")
        )

    # Whole-output: the dayType fuel floor (epic R6; CARDS.md §0/§4). The primary
    # session card sets the floor; enforced via E7·P1's `floors_day_type_hard`,
    # never re-derived. The LLM may fuel up but never under-fuel.
    session_card: WorkoutCard = session.card  # type: ignore[attr-defined]
    day_type: DayType = out.day_type  # type: ignore[attr-defined]
    if floors_day_type_hard(session_card) and day_type is not DayType.hard:
        violations.append(
            Violation(
                rule="day_type_below_floor",
                message=(
                    f"card {session_card.value!r} floors dayType at 'hard' but "
                    f"dayType is {day_type.value!r}"
                ),
            )
        )

    # Whole-output: alternatives ≤ 2 (LLM.md §4 / MODELS).
    if len(alternatives) > 2:
        violations.append(
            Violation(
                rule="too_many_alternatives",
                message=(
                    f"alternatives has {len(alternatives)} entries; the max is 2"
                ),
            )
        )

    return violations
