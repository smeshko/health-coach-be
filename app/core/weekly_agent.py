"""The weekly `WEEKLY_PLANNER` AgentNode — `GeneratePlanNode` (E10·P1).

`GeneratePlanNode` **specialises** E9·P1's generic `PydanticAgentNode` for the
weekly brief: it pins `OutputType = WeeklyPlanLLMOutput` (the slim
`PlannedPick`s in `core`/`extras` + `narrative`), renders the constitution as the
`SYSTEM` prompt, and serialises the **code-computed** weekly user context (E8·P4
budgets + E6·P3 7/28-day rollups & nutrition adherence + E8·P5 recomputed
constants) as the `USER` message (LLM §0/§2). It **inherits** E9·P1's `process()`
/ `build_agent` / failure mapping unchanged — it fills only the seams (and, in
TASK-003, the validator).

`build_weekly_context(...)` is a **pure** serialiser over **already-computed** feed
objects — it runs no DB query and computes no number (E10·P2's
`LoadAggregatesNode`/`ComputeBudgetsNode`/`RecomputeConstants` produce the feeds;
this phase serialises them), so the LLM is fed numbers code computed (LLM §3) and
the builder is unit-testable in isolation.

`WeeklyDeps` carries the **subset** the wired `validate_weekly` validator re-reads
(`budgets` + the threshold↔VO₂ `quality_run_pick`); the full feeds ride in the
`USER` message. Pure `app/core/` module — no FastAPI/HTTP, no Langfuse, no
persistence, no other-node/graph import (mirrors E9·P1).
"""

from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.api.schemas.weekly import WeeklyPlanLLMOutput
from app.core.agent_node import PydanticAgentNode
from app.core.constraints import WeeklyBudgets
from app.core.enums import WorkoutCard
from app.core.nodes import AgentConfig
from app.core.settings import Settings
from app.core.task_context import TaskContext


class WeeklyDeps(BaseModel):
    """The PydanticAI `RunContext` deps `GeneratePlanNode` passes to `agent.run`.

    Carries the **already-computed** weekly context the wired `validate_weekly`
    validator (TASK-003) re-reads — mapping 1:1 to E7·P3's `ValidationContext`
    weekly fields: ``budgets`` (E8·P4 `WeeklyBudgets`, the validator's
    ``ctx.budgets``) and ``quality_run_pick`` (the code-decided threshold↔VO₂
    pick from E8·P5 `next_quality_focus`, ``None`` when neither is expected — the
    **same name + type** as `ValidationContext.quality_run_pick`, so E9·P1's
    `_deps_to_validation_context` adapter is a direct field copy). The full feeds
    (rollups/adherence/constants) flow into the USER message, not deps.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    budgets: WeeklyBudgets
    quality_run_pick: WorkoutCard | None = None


def build_weekly_context(
    *,
    budgets: WeeklyBudgets,
    training_7d: Any,
    training_28d: Any,
    nutrition_adherence: Any,
    constants: Any,
) -> dict:
    """Assemble the weekly `USER` computed-context payload as a JSON-able dict.

    Pure serialiser over the **already-computed** feed objects (E8·P4
    `WeeklyBudgets`; E6·P3 `TrainingRollup` for 7d + 28d; E6·P3
    `NutritionAdherence`; the E8·P5 recomputed-constant outputs). Returns
    ``{ "budgets": {...}, "aggregates": { "training7d": {...}, "training28d":
    {...}, "nutritionAdherence": {...} }, "constants": {...} }`` (LLM §0/§2). The
    E8·P4 ``long_run_km`` ≤10% ramp cap is part of the serialised ``budgets`` so
    the LLM plans within it (the derive-enforcement of the long-run *duration* is
    E10·P2's EXPAND step, not here).

    Does **no** I/O and runs **no** query — it is handed the feed objects (E10·P2
    produces them). The feed objects are frozen dataclasses (or plain dicts), so
    ``_as_dict`` flattens each to primitives without this builder binding their
    concrete types beyond the budgets one the validator shares.
    """
    return {
        "budgets": asdict(budgets),
        "aggregates": {
            "training7d": _as_dict(training_7d),
            "training28d": _as_dict(training_28d),
            "nutritionAdherence": _as_dict(nutrition_adherence),
        },
        "constants": _as_dict(constants),
    }


def _as_dict(value: Any) -> Any:
    """Flatten a feed object to a JSON-able dict (frozen dataclass → ``asdict``;
    a dict passes through; anything else via ``model_dump`` if available)."""
    if isinstance(value, dict):
        return value
    if hasattr(type(value), "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


class GeneratePlanNode(PydanticAgentNode[WeeklyDeps, WeeklyPlanLLMOutput]):
    """The `WEEKLY_PLANNER` AgentNode — a concrete E9·P1 `PydanticAgentNode`.

    Fills E9·P1's seams for the weekly brief: ``get_agent_config`` (Opus,
    ``output_type=WeeklyPlanLLMOutput``), ``build_system_prompt`` (the rendered
    constitution — inherited default, reading the live `Profile` off the
    `TaskContext`), and ``build_run_input`` (the JSON of the pure
    `build_weekly_context` over the code-computed feeds). It **inherits** E9·P1's
    ``process()`` / ``build_agent`` / `BriefGenerationError` failure mapping
    unchanged. The wired `validate_weekly` validator (``build_deps`` +
    ``get_validate_fn``) is TASK-003.
    """

    DepsType = WeeklyDeps
    OutputType = WeeklyPlanLLMOutput
    mode = "weekly"

    def get_agent_config(self) -> AgentConfig:
        """Opus model id (from `Settings`, not hard-coded) + the weekly
        ``output_type``; ``instructions`` left ``None`` so the constitution flows
        through ``build_system_prompt`` (one source, no double-instruction)."""
        return AgentConfig(
            model_id=Settings.model_fields["model_id"].default,
            output_type=WeeklyPlanLLMOutput,
            instructions=None,
        )

    def build_run_input(self, task_context: TaskContext) -> str:
        """Serialise the code-computed weekly USER context to deterministic JSON.

        Reads the **already-computed** feed objects off the `TaskContext` (E10·P2
        places them) and serialises them via the pure `build_weekly_context` —
        the node runs no query and computes no number (LLM §3). ``sort_keys`` keeps
        traces/tests stable across runs.
        """
        import json

        feeds = self._weekly_feeds(task_context)
        return json.dumps(build_weekly_context(**feeds), sort_keys=True)

    def build_deps(self, task_context: TaskContext) -> WeeklyDeps:
        """Build the `RunContext` deps from the code-computed feeds.

        Populates ``budgets`` (the required E8·P4 `WeeklyBudgets` — the validator's
        ``ctx.budgets``) and ``quality_run_pick`` (the threshold↔VO₂ pick off the
        E8·P5 ``constants``), so a deps carrying everything `_deps_to_validation_context`
        + `validate_weekly` (TASK-003) need is threaded into `RunContext`. The
        deps shape is the same whether or not a validator is registered — the run
        always needs a populated `WeeklyDeps` (``budgets`` is required).
        """
        feeds = self._weekly_feeds(task_context)
        return WeeklyDeps(
            budgets=feeds["budgets"],
            quality_run_pick=self._quality_run_pick(feeds["constants"]),
        )

    @staticmethod
    def _quality_run_pick(constants: Any) -> WorkoutCard | None:
        """The code-decided threshold↔VO₂ pick off the E8·P5 ``constants``.

        Reads the ``quality_focus`` cue (``"threshold"``/``"vo2"``, the
        `next_quality_focus` output) and maps it to the matching `WorkoutCard`;
        ``None`` (no quality run expected → the validator skips the threshold↔VO₂
        rule) when absent/unrecognised.
        """
        if isinstance(constants, dict):
            focus = constants.get("quality_focus")
        else:
            focus = getattr(constants, "quality_focus", None)
        if focus is None:
            return None
        focus = str(focus)
        if focus in (WorkoutCard.threshold.value, WorkoutCard.vo2.value):
            return WorkoutCard(focus)
        return None

    def _weekly_feeds(self, task_context: TaskContext) -> dict:
        """The already-computed weekly feed bundle (E8·P4 budgets, E6·P3 7/28d
        rollups & adherence, E8·P5 constants) the USER context serialises.

        Read off ``task_context.metadata["computed"]`` — the seam E10·P2's code
        nodes populate; a test supplies it directly. Read structurally (dict key
        or attribute) so this node binds no concrete E6/E8 result type beyond the
        shared `WeeklyBudgets`.
        """
        computed = task_context.metadata.get("computed", {})

        def _get(name: str) -> Any:
            if isinstance(computed, dict):
                return computed.get(name)
            return getattr(computed, name, None)

        return {
            "budgets": _get("budgets"),
            "training_7d": _get("training_7d"),
            "training_28d": _get("training_28d"),
            "nutrition_adherence": _get("nutrition_adherence"),
            "constants": _get("constants"),
        }
