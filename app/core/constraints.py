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
    is_hard_card,
)
from app.core.enums import DayType, ReadinessBand, Weekday, WorkoutCard, Zone

# Weekday order (mon→sun) for spacing adjacency. A plan is one ISO week, so
# adjacency does **not** wrap sun→mon (Decision).
_WEEKDAY_ORDER: tuple[Weekday, ...] = (
    Weekday.mon,
    Weekday.tue,
    Weekday.wed,
    Weekday.thu,
    Weekday.fri,
    Weekday.sat,
    Weekday.sun,
)
_WEEKDAY_INDEX: dict[Weekday, int] = {d: i for i, d in enumerate(_WEEKDAY_ORDER)}


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

    ``long_run_km`` is part of the MODELS budgets contract (carried for the E9
    adapter), but is **not** a deterministic invariant this validator enforces
    (review #3): a weekly ``PlannedPick`` carries minutes, not distance, so the
    long-run ramp/distance cap has no code input here — it is a plan-generation /
    prompt-time concern (LLM.md), outside this phase's CARDS.md §4 invariant set.
    It is ``float | None`` because the E8·P4 budget engine returns ``None`` when
    there is no prior long-run history (week one / no prior long run) — MODELS
    ``longRunKm`` is nullable.
    """

    hard_days: int
    strength_sessions: int
    long_run_km: float | None
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
    dose-in-band, **and the ``dayType`` fuel floor**) run over ``session``
    **and** each ``alternatives`` entry — a hard/long alternative under a
    sub-``hard`` ``dayType`` under-fuels the user just like the primary would.
    The ``alternatives``-count check is the one whole-output check, applied once.
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

    # The dayType fuel floor (epic R6; CARDS.md §0/§4). Enforced via E7·P1's
    # `floors_day_type_hard`, never re-derived. The LLM may fuel up but never
    # under-fuel. Applied to the primary `session` AND each `alternatives` entry
    # (review #1): an alternative is a real fallback pick the UI may show, so a
    # hard/long alternative under a sub-`hard` dayType under-fuels the user just
    # as the primary would — parity with the other per-pick safety gates (AMBER,
    # knee, dose) that already cover alternatives.
    day_type: DayType = out.day_type  # type: ignore[attr-defined]
    for pick, where in [(session, "session"), *((a, "alternative") for a in alternatives)]:
        pick_card: WorkoutCard = pick.card  # type: ignore[attr-defined]
        if floors_day_type_hard(pick_card) and day_type is not DayType.hard:
            violations.append(
                Violation(
                    rule="day_type_below_floor",
                    message=(
                        f"{where} card {pick_card.value!r} floors dayType at 'hard' "
                        f"but dayType is {day_type.value!r}"
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


# --------------------------------------------------------------------------
# Weekly validator. Reads the **training-load** axis `is_hard` (never `day_type`)
# for the hard-day rules — a `long_run` is `is_hard=False`, so it does not consume
# a hard slot or trip spacing (the E7·P1 two-axes rule).
# --------------------------------------------------------------------------
def _weekday_index(day: Weekday) -> int:
    """The mon→sun (0–6) index of ``day``. Only ever called on a non-``None``
    ``suggestedDay`` — day-less picks are filtered out first."""
    return _WEEKDAY_INDEX[day]


def _is_hard_run(card: WorkoutCard) -> bool:
    """A "hard run" for the post-boxing spacing rule: a card that is both
    ``is_hard`` **and** a run (carries ``Flag.impact`` — ``threshold``/``vo2``/
    ``progression_run``). A flag-derived predicate, not a literal card list, so a
    future running card is covered automatically (Decision)."""
    return is_hard_card(card) and Flag.impact in get_card(card).flags


def validate_weekly(out: object, ctx: ValidationContext) -> list[Violation]:
    """Police a weekly LLM plan against ``CARD_META`` + ``ctx``.

    ``out`` is a ``WeeklyPlanLLMOutput``-shaped value (read structurally):
    ``core`` and ``extras`` are lists of slim ``PlannedPick``s (``card``/
    ``suggested_day``/``duration_min_low``/``duration_min_high``). Returns
    **every** broken CARDS.md §4 / LLM.md §4 weekly invariant as a ``Violation``
    (never short-circuits, never raises); an empty list means a clean plan.

    The hard-day rules read ``is_hard`` (the load axis). ``strength_count`` is an
    **equality** check (strength is protected at the budget); ``hard_day_count`` /
    ``long_run_count`` / ``deload_hard_cap`` are ceilings. Spacing adjacency runs
    mon→sun with **no** sun→mon wrap; day-less (``suggested_day is None``) picks
    are excluded from the two day-relative rules.
    """
    core = list(out.core)  # type: ignore[attr-defined]
    extras = list(out.extras)  # type: ignore[attr-defined]
    picks = core + extras
    violations: list[Violation] = []

    hard_picks = [p for p in picks if is_hard_card(p.card)]
    n_hard = len(hard_picks)

    # hard_day_count — count(is_hard) ≤ budgets.hard_days.
    if n_hard > ctx.budgets.hard_days:
        violations.append(
            Violation(
                rule="hard_day_count",
                message=(
                    f"{n_hard} hard cards exceed the budget of "
                    f"{ctx.budgets.hard_days} hard days"
                ),
            )
        )

    # hard_day_spacing — no two is_hard picks on the same or adjacent
    # suggestedDays (mon→sun, no wrap). Day-less picks excluded. `b - a <= 1`
    # catches both same-day (delta 0 — two hard sessions stacked on one day, zero
    # recovery) and adjacent (delta 1) collisions; non-adjacent (>=2) is clean
    # (review #2 — `== 1` alone let two same-day hard cards through).
    hard_days_idx = sorted(
        _weekday_index(p.suggested_day)
        for p in hard_picks
        if p.suggested_day is not None
    )
    if any(b - a <= 1 for a, b in zip(hard_days_idx, hard_days_idx[1:])):
        violations.append(
            Violation(
                rule="hard_day_spacing",
                message="two hard cards sit on the same or adjacent days",
            )
        )

    # hard_run_after_boxing — a hard run the day after boxing. Day-less excluded.
    boxing_days = {
        _weekday_index(p.suggested_day)
        for p in picks
        if p.card is WorkoutCard.boxing and p.suggested_day is not None
    }
    hard_run_days = {
        _weekday_index(p.suggested_day)
        for p in picks
        if _is_hard_run(p.card) and p.suggested_day is not None
    }
    if any((d + 1) in hard_run_days for d in boxing_days):
        violations.append(
            Violation(
                rule="hard_run_after_boxing",
                message="a hard run is scheduled the day after boxing",
            )
        )

    # strength_count — equality: count(strength) == budgets.strength_sessions.
    n_strength = sum(1 for p in picks if Flag.strength in get_card(p.card).flags)
    if n_strength != ctx.budgets.strength_sessions:
        violations.append(
            Violation(
                rule="strength_count",
                message=(
                    f"{n_strength} strength sessions != the budget of "
                    f"{ctx.budgets.strength_sessions}"
                ),
            )
        )

    # core_size — 2 ≤ len(core) ≤ 3.
    if not (2 <= len(core) <= 3):
        violations.append(
            Violation(
                rule="core_size",
                message=f"core has {len(core)} picks; must be 2–3",
            )
        )

    # extras_size — 1 ≤ len(extras) ≤ 2.
    if not (1 <= len(extras) <= 2):
        violations.append(
            Violation(
                rule="extras_size",
                message=f"extras has {len(extras)} picks; must be 1–2",
            )
        )

    # long_run_count — ≤ 1 long_run.
    n_long_run = sum(1 for p in picks if p.card is WorkoutCard.long_run)
    if n_long_run > 1:
        violations.append(
            Violation(
                rule="long_run_count",
                message=f"{n_long_run} long_run picks; the max is 1",
            )
        )

    # quality_run_mismatch — any picked threshold/vo2 must equal the code-decided
    # quality pick. Skipped when ctx.quality_run_pick is None.
    if ctx.quality_run_pick is not None:
        for p in picks:
            if (
                p.card in (WorkoutCard.threshold, WorkoutCard.vo2)
                and p.card is not ctx.quality_run_pick
            ):
                violations.append(
                    Violation(
                        rule="quality_run_mismatch",
                        message=(
                            f"quality run {p.card.value!r} does not match the "
                            f"code-decided pick {ctx.quality_run_pick.value!r}"
                        ),
                    )
                )

    # deload_hard_cap — on a deload week, count(is_hard) ≤ 1 (a tighter, distinct
    # cap from hard_day_count; both may fire on a deload week — Decision).
    if ctx.budgets.deload and n_hard > 1:
        violations.append(
            Violation(
                rule="deload_hard_cap",
                message=(
                    f"deload week allows ≤ 1 hard day; the plan has {n_hard}"
                ),
            )
        )

    # dose_out_of_band — per pick (shared helper + key with validate_daily). A
    # weekly pick may omit its dose (suggested_day-only sequencing); a pick with a
    # None bound is left to the daily expansion, so only check filled doses.
    for p in picks:
        low = p.duration_min_low
        high = p.duration_min_high
        if low is None or high is None:
            continue
        if not _dose_in_band(p.card, low, high):
            meta = get_card(p.card)
            violations.append(
                Violation(
                    rule="dose_out_of_band",
                    message=(
                        f"card {p.card.value!r} dose {low}–{high} min is outside "
                        f"its band {meta.dose_min_low}–{meta.dose_min_high}"
                    ),
                )
            )

    return violations
