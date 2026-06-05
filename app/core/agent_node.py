"""The shared LLM call harness behind E1's `AgentNode` seam (E9·P1).

This is the module that finally imports PydanticAI — E1's `nodes.py` deliberately
keeps the provider SDK out (its docstring: "constructs **no** `Agent` and imports
**no** provider SDK … real wiring is E9 — LLM.md §0"). Here `build_agent` turns an
E1 `AgentConfig` into a PydanticAI `Agent` with the LLM §2 model settings — Claude
**Opus**, **tool-based** structured `output_type`, **low** temperature, **caching
off**, **retries ≤ 2**, **no fallback** — and `PydanticAgentNode` subclasses the
abstract `AgentNode`, filling the `process()` E1 left open: build the agent, run it
over the `TaskContext`'s computed context, and store the typed `OutputType` back via
`save_output()`. On timeout / persistent failure it raises a mapped
`BriefGenerationError` carrying the stable `brief_generation_failed` /
`upstream_timeout` code (MODELS Errors) — **never** a synthetic fallback session.

The two concrete `*LLMOutput` types, the user-context JSON builder, the
`@agent.output_validator`, the routes, and Langfuse tracing are E7 / E9·P2 / E10 /
E11 / E12 — this module stays **generic over the OutputType** and FastAPI-free.
"""

import asyncio
import json
from enum import Enum
from typing import Any, Generic, Literal, TypeVar

import anthropic
import httpx
from pydantic import BaseModel
from pydantic_ai import (
    Agent,
    AgentRunError,
    ModelHTTPError,
    ToolOutput,
)
from pydantic_ai.settings import ModelSettings

from app.core.constitution import constitution_version, render_constitution
from app.core.nodes import AgentConfig, AgentNode
from app.core.profile import Profile
from app.core.task_context import TaskContext

# The stable machine codes MODELS "Errors" lists for the LLM failure path (LLM §5).
ErrorCodeT = Literal["brief_generation_failed", "upstream_timeout"]

# HTTP statuses that mean the upstream timed out (request timeout / gateway timeout),
# so a timeout-flavoured ModelHTTPError maps to upstream_timeout, not the generic code.
_TIMEOUT_STATUS_CODES = frozenset({408, 504})

# Concrete timeout exception types. `anthropic.APITimeoutError` is the COMMON real
# timeout: the Anthropic SDK raises it (a subclass of APIConnectionError — NOT an
# httpx.TimeoutException, NOT an APIStatusError), and PydanticAI's `_map_api_errors`
# re-wraps it into a `ModelAPIError` (no status_code). So the timeout only survives on
# the chained __cause__ — `_is_timeout` walks the cause chain to catch it (review #1).
_TIMEOUT_TYPES: tuple[type[BaseException], ...] = (
    TimeoutError,
    asyncio.TimeoutError,
    httpx.TimeoutException,
    anthropic.APITimeoutError,
)

# Real type parameters so a concrete weekly/daily node specialises the base with its
# own deps + `*LLMOutput` (E10/E11) — the brief-agnostic-but-type-safe contract the
# epic asks for (LLM §1 "differ only in their context payload and their OutputType").
DepsTypeT = TypeVar("DepsTypeT", bound=BaseModel)
OutputTypeT = TypeVar("OutputTypeT", bound=BaseModel)

# --- LLM §2 model settings (the single home of these knobs; observable in tests) ---

# Low temperature keeps the model's picks stable (LLM §2 "low — keep picks stable").
LOW_TEMPERATURE: float = 0.1
# The ≤ 2 output-validator retry budget the E9·P2 `@agent.output_validator` consumes
# (LLM §2/§4 "Retries ≤ 2"). There is no public `agent.retries`; this sets the
# private `agent._max_output_retries`.
MAX_RETRIES: int = 2
# Per-call request timeout so a hung upstream surfaces as `upstream_timeout` (LLM §5).
CALL_TIMEOUT_S: float = 60.0

# The two agent shapes the one builder serves — "same shape for both agents, only
# the context payload and the OutputType differ" (LLM §2). Weekly adds `budgets`;
# daily adds the active `weekPlan` + `MacroFocus`.
ModeT = Literal["weekly", "daily"]


def _jsonable(value: Any) -> Any:
    """Coerce `value` to a JSON-serialisable form for the USER message.

    Pydantic `BaseModel`s → `model_dump(mode="json")` (enums become their wire
    string, dates ISO-format); `Enum`s → their `.value`; everything else passes
    through `json.dumps`'s native handling. Used as `json.dumps(..., default=…)`
    so any nested computed value (an E6/E8 result model, a card enum) serialises
    deterministically without this builder knowing its concrete type.
    """
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serialisable")


def build_user_context(profile: Profile, *, computed: Any, mode: ModeT) -> dict:
    """Assemble the per-period computed USER context as a JSON-able dict (LLM §2).

    This is the "USER computed context for THIS period" the model picks *within*
    (derive-don't-emit): it **collects + serialises** values the E6/E8 engines
    already computed (read off `computed`) and stamps `constitution_version` — it
    computes **no** numbers itself. The single `mode`-parameterised builder serves
    **both** agents ("same shape for both agents — only the context payload
    differs", LLM §2), so the shared harness stays brief-agnostic.

    `computed` is the period bundle the node assembled off the `TaskContext`
    (forward dep — E6 7/28-day rollups, E8 `compute_readiness`/`compute_budgets`/
    `compute_macros`); it is read **structurally** via `_get` (a key on a dict or
    an attribute on an object) so this module binds no concrete E6/E8 type.

    Common fields (both modes): `constitution_version`, `live_weight_kg`,
    `readiness`/`band`/`safetyGate`, `aggregates` (7/28-day training **and**
    nutrition intake), `flags` (knee, gi), `constants`. `mode="weekly"` adds
    `budgets` (E8 `WeeklyBudgets`) + last-week nutrition adherence; `mode="daily"`
    adds the active `weekPlan`, the `safetyGate` result, and `MacroFocus` +
    yesterday's `IntakeSummary`.

    The live weight is a **user-context** field (`live_weight_kg`), never baked
    into the system prompt (LLM §2 "live weight is fed in the user context").
    """

    def _get(key: str, default: Any = None) -> Any:
        if isinstance(computed, dict):
            return computed.get(key, default)
        return getattr(computed, key, default)

    context: dict[str, Any] = {
        "constitution_version": constitution_version(profile),
        "live_weight_kg": _get("live_weight_kg"),
        "readiness": _get("readiness"),
        "band": _get("band"),
        "safetyGate": _get("safety_gate"),
        "aggregates": _get("aggregates"),
        "flags": _get("flags"),
        "constants": _get("constants"),
    }
    if mode == "weekly":
        context["budgets"] = _get("budgets")
        context["nutritionAdherence"] = _get("nutrition_adherence")
    else:
        context["weekPlan"] = _get("week_plan")
        context["macroFocus"] = _get("macro_focus")
        context["intakeSummary"] = _get("intake_summary")
    return context


def build_agent(
    config: AgentConfig, *, system_prompt: str, deps_type: type[BaseModel]
) -> Agent:
    """Construct a PydanticAI `Agent` from an E1 `AgentConfig` with the LLM §2 settings.

    The model is the **deferred string** id `f"anthropic:{config.model_id}"` with
    `defer_model_check=True` — a concrete `AnthropicModel(config.model_id)` eagerly
    infers the provider and raises `UserError: Set the ANTHROPIC_API_KEY ...` at
    construction, so the deferred string form is used to keep construction **key-free**
    (the real model resolves only on a live `agent.run`; tests `override` it). The Opus
    id flows from `config.model_id` (default `claude-opus-4-8`), so a Sonnet downshift
    stays a config change (LLM §5).

    `output_type` is wrapped in `ToolOutput(...)` for **tool-based** structured output
    (LLM §0/§2 "tool call"); `instructions` is the rendered constitution passed **fresh**
    per build (caching off — no prompt-cache breakpoint set anywhere; LLM §2/§5); the
    `deps_type` is the `RunContext` deps seam E9·P2's validator reads; `model_settings`
    pins the low temperature and the request timeout; `retries` is the ≤ 2 budget.
    """
    return Agent(
        f"anthropic:{config.model_id}",
        output_type=ToolOutput(config.output_type),
        instructions=system_prompt,
        deps_type=deps_type,
        model_settings=ModelSettings(
            temperature=LOW_TEMPERATURE, timeout=CALL_TIMEOUT_S
        ),
        retries=MAX_RETRIES,
        defer_model_check=True,
    )


class BriefGenerationError(Exception):
    """In-engine signal that an LLM brief call failed (LLM §5; MODELS Errors).

    Carries the stable machine `code` — `brief_generation_failed` or `upstream_timeout`
    — that the E10/E11 **route** layer later renders into the MODELS
    `{ error: { code, message, detail } }` envelope. It builds **no** HTTP envelope
    itself (no FastAPI in `app/core/`); the route layer owns the wire shape + status.
    """

    def __init__(
        self,
        code: ErrorCodeT,
        message: str | None = None,
        detail: str | None = None,
    ):
        self.code: ErrorCodeT = code
        self.message: str | None = message
        self.detail: str | None = detail
        super().__init__(message or code)


def _is_timeout(exc: Exception) -> bool:
    """True if `exc` is an upstream timeout (vs a generic LLM failure).

    Matches a direct timeout type, a timeout-flavoured `ModelHTTPError` (408/504), **and**
    a timeout carried on the chained cause — PydanticAI wraps the provider SDK's timeout
    (`anthropic.APITimeoutError`) into a `ModelAPIError`, so the common real timeout only
    appears as `exc.__cause__` (review #1). The chain walk is bounded + cycle-safe.
    """
    if isinstance(exc, ModelHTTPError) and exc.status_code in _TIMEOUT_STATUS_CODES:
        return True
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, _TIMEOUT_TYPES):
            return True
        current = current.__cause__ or current.__context__
    return False


class PydanticAgentNode(AgentNode, Generic[DepsTypeT, OutputTypeT]):
    """A generic, brief-agnostic `AgentNode` wrapping a PydanticAI `Agent` (E9·P1).

    Subclasses E1's abstract `AgentNode(Node, ABC)` and fills the `process()` it left
    open — honouring the existing seam (`get_agent_config()`, the `DepsType`/`OutputType`
    class attrs) rather than redefining it; `nodes.py` is **not** edited. It is generic
    over the deps + output types so the E10 (weekly) and E11 (daily) nodes each specialise
    it with their own deps + output models — e.g. ``class WeeklyNode(PydanticAgentNode[
    WeeklyDeps, WeeklyOut]): ...`` — keeping this base brief-agnostic (it imports neither
    concrete output type).

    E9·P2 fills the two context seams `build_system_prompt` (the rendered
    constitution for the live period) and `build_run_input` (the computed-context
    USER JSON via `build_user_context`), reading the live `Profile` + the computed
    bundle off the `TaskContext` through the `_profile`/`_computed` extraction
    seams E10/E11 specialise. The `mode` (`"weekly"`/`"daily"`) parameterises the
    one builder so it serves both agents. The `@agent.output_validator` wiring +
    the pre-persist re-check are E9·P2 (below); the `deps_type` + `retries` budget
    are the E9·P1 seams that wiring consumes.
    """

    #: The agent shape ("weekly"/"daily") the one `build_user_context` builder
    #: serves; E10/E11 pin it on their concrete node so the harness stays
    #: brief-agnostic (LLM §2 "same shape for both agents").
    mode: ModeT = "weekly"

    def _profile(self, task_context: TaskContext) -> Profile:
        """The live per-period `Profile` (constants) the workflow loaded.

        Read off `task_context.metadata["profile"]` by default — the seam the
        workflow populates; E10/E11 may override to source it differently. Used by
        both `build_system_prompt` (the rendered constitution) and
        `build_user_context` (the `constitution_version` stamp).
        """
        profile = task_context.metadata.get("profile")
        if not isinstance(profile, Profile):
            raise ValueError(
                "task_context.metadata['profile'] must be a Profile for the agent call"
            )
        return profile

    def _computed(self, task_context: TaskContext) -> Any:
        """The per-period computed bundle (E6/E8 numbers) the USER context carries.

        Read off `task_context.metadata["computed"]` by default; E10/E11 specialise
        where their period's computed values live. `build_user_context` reads it
        structurally (dict key or attribute) so this base binds no concrete E6/E8
        type. Defaults to an empty dict so a missing bundle yields null fields
        rather than raising.
        """
        return task_context.metadata.get("computed", {})

    def build_system_prompt(self, task_context: TaskContext) -> str:
        """Return the rendered-constitution system prompt for the live `Profile` (E3).

        Calls `render_constitution(profile)` **fresh** each `process()` — caching is
        off (LLM §2/§5; E3 "no cache"), so nothing memoizes the prompt. Takes only
        the `Profile` (constants); the live weight enters via the USER context, not
        the prompt (LLM §2).
        """
        return render_constitution(self._profile(task_context))

    def build_run_input(self, task_context: TaskContext) -> str:
        """Serialise the per-period USER context to the deterministic JSON USER message.

        Assembles `build_user_context(profile, computed=…, mode=self.mode)` and
        dumps it with `sort_keys=True` so traces and tests are stable across runs.
        Nested computed `BaseModel`/`Enum` values serialise via `_jsonable`.
        """
        context = build_user_context(
            self._profile(task_context),
            computed=self._computed(task_context),
            mode=self.mode,
        )
        return json.dumps(context, sort_keys=True, default=_jsonable)

    def build_deps(self, task_context: TaskContext) -> DepsTypeT:
        """Build the `RunContext` deps for the run; default is a bare `DepsType` (E9·P2 enriches)."""
        return self.DepsType()

    async def process(self, task_context: TaskContext) -> TaskContext:
        """Build the agent, run it over the context, and store the typed `OutputType`.

        Runs the agent with **async** `await agent.run(...)` — the workflow runner already
        awaits `process` (E1 `workflow.py`), so a sync `run_sync` here would nest an event
        loop and raise. On success the validated `OutputType` lands in
        `task_context.nodes[node_name]` via E1's `save_output`.

        On failure it raises a mapped `BriefGenerationError` (LLM §5; MODELS Errors) — a
        **timeout** → `upstream_timeout`, exhausted retries / invalid structure / any other
        model-HTTP failure → `brief_generation_failed`, with the cause chained. There is
        **no synthetic fallback**: a failure raises and `save_output` never runs, so nothing
        half-baked lands in `task_context.nodes` for a downstream node to read (LLM §2/§5
        "Fallback: none").
        """
        config = self.get_agent_config()
        agent = build_agent(
            config,
            system_prompt=self.build_system_prompt(task_context),
            deps_type=self.DepsType,
        )
        try:
            result = await agent.run(
                self.build_run_input(task_context),
                deps=self.build_deps(task_context),
            )
        except Exception as exc:
            if _is_timeout(exc):
                raise BriefGenerationError(code="upstream_timeout") from exc
            # Exhausted retries (UnexpectedModelBehavior), invalid structure, and every
            # other model/HTTP failure (ModelHTTPError/ModelAPIError) derive from
            # AgentRunError → the generic LLM-failure code.
            if isinstance(exc, AgentRunError):
                raise BriefGenerationError(code="brief_generation_failed") from exc
            raise
        self.save_output(result.output)
        return task_context
