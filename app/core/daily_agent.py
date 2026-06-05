"""The daily `DAILY_ADJUSTER` AgentNode — `TuneSessionNode` (E11·P1).

`TuneSessionNode` **specialises** E9·P1's generic `PydanticAgentNode` for the
daily brief: it pins `OutputType = DailyBriefLLMOutput` (the slim `SessionPick`s
for `session` + `alternatives`, `skipOk`, the guarded `dayType` lever, and the
`narrative`), renders the constitution as the `SYSTEM` prompt, and serialises the
**code-computed** daily user context (E8·P1 readiness+band + E8·P2 gate result +
E10 week-plan cards + the check-in flags) as the `USER` message **via E9·P2's
shared `build_user_context(..., mode="daily")`** — not a forked builder (LLM
§0/§2). It **inherits** E9·P1's `process()` / `build_agent` / failure mapping
unchanged — it fills only the seams (and, in TASK-003, the validator).

`build_daily_computed(...)` is a **pure** assembler over **already-computed** feed
objects — it runs no DB query and computes no readiness/gate/macro number (E11·P2's
readiness node / gate router / week-plan lookup produce the feeds; this node
serialises them), so the LLM is fed numbers code computed (LLM §3) and the builder
is unit-testable in isolation.

`DailyDeps` carries the **subset** the wired `validate_daily` validator re-reads
(`band` + `knee_pain` + `week_plan_cards` + `safety_gate_triggered`, plus the
sentinel `budgets` the shared deps→`ValidationContext` adapter requires); the full
feeds ride in the `USER` message. The **gate-skip is E11·P2's router**, not this
node — the node runs only on the non-gated path and carries
`safety_gate_triggered` as a belt-and-suspenders signal. Pure `app/core/` module —
no FastAPI/HTTP, no Langfuse, no persistence, no other-node/graph import (mirrors
E9·P1/E10·P1).
"""

import json
from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.daily import DailyBriefLLMOutput
from app.core.agent_node import PydanticAgentNode, build_user_context
from app.core.constraints import (
    ValidationContext,
    Violation,
    WeeklyBudgets,
    validate_daily,
)
from app.core.enums import NarrativeType, ReadinessBand, WorkoutCard
from app.core.nodes import AgentConfig
from app.core.settings import Settings
from app.core.task_context import TaskContext

# The daily narrative subset (LLM §1): only these section types may appear in a
# daily brief — the full `NarrativeType` **minus** the weekly-only `plan`. A `plan`
# section is a hard violation the model retries on (the one daily narrative rule
# E7·P3's `validate_daily` doesn't encode).
_DAILY_NARRATIVE_TYPES: frozenset[NarrativeType] = frozenset(
    {
        NarrativeType.summary,
        NarrativeType.session,
        NarrativeType.nutrition,
        NarrativeType.caution,
    }
)


def _no_budgets() -> WeeklyBudgets:
    """The sentinel `WeeklyBudgets` `DailyDeps` carries.

    The **shared** `_deps_to_validation_context` adapter (E9·P2) requires a
    `budgets` on the deps (it raises without one) — but `validate_daily` never
    reads `ctx.budgets`, so a zero sentinel is harmless and keeps `DailyDeps` a
    direct 1:1 copy of the `ValidationContext` daily fields without editing the
    shared harness.
    """
    return WeeklyBudgets(
        hard_days=0, strength_sessions=0, long_run_km=None, deload=False
    )


class DailyDeps(BaseModel):
    """The PydanticAI `RunContext` deps `TuneSessionNode` passes to `agent.run`.

    Carries the **already-computed** daily context the wired `validate_daily`
    validator (TASK-003) re-reads — mapping 1:1 to E7·P3's `ValidationContext`
    daily fields: ``band`` (E8·P1 `ReadinessBand` — the RED/AMBER gating),
    ``knee_pain`` (the check-in flag — the ``> 3`` impact gate), ``week_plan_cards``
    (the E10 week's planned cards — what "card ∈ week plan" reads), and
    ``safety_gate_triggered`` (E8·P2 — belt-and-suspenders, ``False`` on this
    node's non-gated path). ``budgets`` is the sentinel the shared deps→context
    adapter requires (see ``_no_budgets``). The full feeds (readiness penalties,
    aggregates, constants) flow into the USER message, not deps.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    band: ReadinessBand = ReadinessBand.green
    knee_pain: int = 0
    week_plan_cards: frozenset[WorkoutCard] = Field(default_factory=frozenset)
    safety_gate_triggered: bool = False
    budgets: WeeklyBudgets = Field(default_factory=_no_budgets)


def _as_dict(value: Any) -> Any:
    """Flatten a feed object to a JSON-able form (frozen dataclass → ``asdict``;
    a `BaseModel` → ``model_dump(mode="json")``; a dict/primitive passes through).

    The card-system enums are ``str``-subclassing, so any enum surviving ``asdict``
    (e.g. ``Readiness.band``, ``SafetyGate.overrideTo``) serialises natively under
    ``json.dumps`` without a custom encoder.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def _card_value(card: Any) -> str:
    """The wire value of a `WorkoutCard` (or a plain string)."""
    return getattr(card, "value", card)


def build_daily_computed(
    *,
    readiness: Any = None,
    safety_gate: Any = None,
    week_plan_cards: Any = (),
    flags: Any = None,
    aggregates: Any = None,
    constants: Any = None,
    live_weight_kg: float | None = None,
    macro_focus: Any = None,
    intake_summary: Any = None,
) -> dict:
    """Assemble the daily `computed` bundle E9·P2's `build_user_context(...,
    mode="daily")` consumes — a **pure** serialiser over already-computed feeds.

    Gathers the E8·P1 `Readiness` (its `band` surfaced as the top-level ``band``
    the daily validator context reads), the E8·P2 `SafetyGate` (un-triggered on
    this path), the E10 week-plan cards (as a sorted ``{"cards": [...]}`` list),
    the check-in ``flags`` (`knee_pain`, `gi_symptoms`), and the optional
    aggregates / constants / live weight / `MacroFocus` / yesterday `IntakeSummary`
    slots. The keys line up 1:1 with `build_user_context`'s ``mode="daily"``
    ``_get`` reads. Does **no** I/O and computes **no** number — it serialises the
    feed objects E11·P2 produces.
    """
    band = getattr(readiness, "band", None)
    return {
        "readiness": _as_dict(readiness),
        "band": band,
        "safety_gate": _as_dict(safety_gate),
        "week_plan": {"cards": sorted(_card_value(c) for c in (week_plan_cards or ()))},
        "flags": _as_dict(flags),
        "aggregates": _as_dict(aggregates),
        "constants": _as_dict(constants),
        "live_weight_kg": live_weight_kg,
        "macro_focus": _as_dict(macro_focus),
        "intake_summary": _as_dict(intake_summary),
    }


def _flag_int(flags: Any, name: str) -> int:
    """Read an integer check-in flag (e.g. ``knee_pain``) off a dict-or-object."""
    if isinstance(flags, dict):
        value = flags.get(name, 0)
    else:
        value = getattr(flags, name, 0)
    return int(value or 0)


class TuneSessionNode(PydanticAgentNode[DailyDeps, DailyBriefLLMOutput]):
    """The `DAILY_ADJUSTER` AgentNode — a concrete E9·P1 `PydanticAgentNode`.

    Fills E9·P1's seams for the daily brief: ``get_agent_config`` (Opus,
    ``output_type=DailyBriefLLMOutput``), ``build_system_prompt`` (the rendered
    constitution — inherited default, reading the live `Profile` off the
    `TaskContext`), and ``build_run_input`` (the JSON of E9·P2's shared
    `build_user_context(..., mode="daily")` over the daily `computed` bundle this
    node assembles purely from the code-computed feeds). It **inherits** E9·P1's
    ``process()`` / ``build_agent`` / `BriefGenerationError` failure mapping
    unchanged. The wired `validate_daily` validator (``get_validate_fn``) is
    TASK-003.
    """

    DepsType = DailyDeps
    OutputType = DailyBriefLLMOutput
    mode = "daily"

    def get_agent_config(self) -> AgentConfig:
        """Opus model id (from `Settings`, not hard-coded) + the daily
        ``output_type``; ``instructions`` left ``None`` so the constitution flows
        through ``build_system_prompt`` (one source, no double-instruction)."""
        return AgentConfig(
            model_id=Settings.model_fields["model_id"].default,
            output_type=DailyBriefLLMOutput,
            instructions=None,
        )

    def build_run_input(self, task_context: TaskContext) -> str:
        """Serialise the code-computed daily USER context to deterministic JSON.

        Reads the **already-computed** feed objects off the `TaskContext` (E11·P2
        places them), assembles the daily `computed` bundle via the pure
        `build_daily_computed`, and serialises it through E9·P2's **shared**
        `build_user_context(..., mode="daily")` — the node runs no query and
        computes no number (LLM §3). ``sort_keys`` keeps traces/tests stable.
        """
        profile = self._profile(task_context)
        computed = build_daily_computed(**self._daily_feeds(task_context))
        context = build_user_context(profile, computed=computed, mode="daily")
        return json.dumps(context, sort_keys=True)

    def build_deps(self, task_context: TaskContext) -> DailyDeps:
        """Build the `RunContext` deps from the code-computed feeds.

        Populates ``band`` (off the E8·P1 `Readiness`), ``knee_pain`` (off the
        check-in flags), ``week_plan_cards`` (the E10 cards), and
        ``safety_gate_triggered`` (off the E8·P2 gate — ``False`` on this path), so
        the deps carry everything the shared `_deps_to_validation_context` adapter
        + `validate_daily` (TASK-003) re-read. ``budgets`` stays the sentinel.
        """
        feeds = self._daily_feeds(task_context)
        readiness = feeds.get("readiness")
        safety_gate = feeds.get("safety_gate")
        band = getattr(readiness, "band", None) or ReadinessBand.green
        return DailyDeps(
            band=band,
            knee_pain=_flag_int(feeds.get("flags"), "knee_pain"),
            week_plan_cards=frozenset(feeds.get("week_plan_cards") or ()),
            safety_gate_triggered=bool(getattr(safety_gate, "triggered", False)),
        )

    def _daily_feeds(self, task_context: TaskContext) -> dict:
        """The already-computed daily feed bundle (E8·P1 readiness, E8·P2 gate,
        E10 week-plan cards, the check-in flags + optional aggregates/constants/
        weight/macro/intake) the USER context + deps read.

        Read off ``task_context.metadata["computed"]`` — the seam E11·P2's code
        nodes populate; a test supplies it directly. Read structurally (dict key
        or attribute) so this node binds no concrete E6/E8 result type.
        """
        computed = task_context.metadata.get("computed", {})

        def _get(name: str) -> Any:
            if isinstance(computed, dict):
                return computed.get(name)
            return getattr(computed, name, None)

        return {
            "readiness": _get("readiness"),
            "safety_gate": _get("safety_gate"),
            "week_plan_cards": _get("week_plan_cards"),
            "flags": _get("flags"),
            "aggregates": _get("aggregates"),
            "constants": _get("constants"),
            "live_weight_kg": _get("live_weight_kg"),
            "macro_focus": _get("macro_focus"),
            "intake_summary": _get("intake_summary"),
        }

    def get_validate_fn(
        self,
    ) -> Callable[[DailyBriefLLMOutput, ValidationContext], list[Violation]]:
        """The pure daily validator E9·P1's `process()` wires as the agent's
        `@agent.output_validator` (a hard `Violation` ⇒ `ModelRetry` within the
        ``retries ≤ 2`` budget; a clean session returns unchanged).

        Returns `validate_daily_output` — E7·P3's `validate_daily` (card-in-plan,
        RED/AMBER band gating, knee gate, dose-in-band, the `dayType` fuel-floor
        `day_type_below_floor`, and the `too_many_alternatives` ≤ 2 cap) **plus**
        the one daily-only `summary|session|nutrition|caution` narrative-subset
        check (LLM §1). E9·P2's `make_output_validator` builds the
        `ValidationContext` from `RunContext[DailyDeps].deps` and drives the
        `ModelRetry`; this node writes no `@agent.output_validator` boilerplate.
        """
        return validate_daily_output


def validate_daily_output(
    out: DailyBriefLLMOutput, ctx: ValidationContext
) -> list[Violation]:
    """The daily output validator — `validate_daily` (E7·P3) + the narrative subset.

    Pure, LLM-free, same signature as `validate_daily` so it slots straight into
    E9·P2's `make_output_validator`. Runs every E7·P3 daily invariant (card ∈ week
    plan ∪ subs, RED ⇒ rest card, AMBER ⇒ no full vo2/z5, `knee_pain > 3` ⇒ no
    impact card, dose-in-band, the `dayType` fuel-floor `day_type_below_floor`, and
    the `too_many_alternatives` ≤ 2 cap) and **appends** one hard `Violation` per
    narrative section whose `type` is outside the daily
    `summary|session|nutrition|caution` subset (LLM §1) — i.e. the weekly-only
    `plan` kind, the one daily narrative rule E7·P3 doesn't encode. All hard
    violations flow through E9·P1's single `ModelRetry` path; an empty list means a
    clean session.
    """
    violations = list(validate_daily(out, ctx))
    for section in out.narrative:
        if section.type not in _DAILY_NARRATIVE_TYPES:
            violations.append(
                Violation(
                    rule="daily_narrative_type",
                    message=(
                        f"narrative section type {section.type.value!r} is not in the "
                        "daily subset (summary|session|nutrition|caution)"
                    ),
                )
            )
    return violations
