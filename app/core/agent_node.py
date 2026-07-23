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
    ModelRetry,
    RunContext,
    ToolOutput,
)
from pydantic_ai.exceptions import UserError
from pydantic_ai.settings import ModelSettings

from app.core.constitution import constitution_version, render_constitution
from app.core.constraints import Severity, ValidationContext, WeeklyBudgets
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


def build_agent(config: AgentConfig, *, system_prompt: str, deps_type: type[BaseModel]) -> Agent:
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
        model_settings=ModelSettings(temperature=LOW_TEMPERATURE, timeout=CALL_TIMEOUT_S),
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


# --------------------------------------------------------------------------
# Output-validation wiring (E9·P2). The pure E7·P3 `validate_weekly`/`validate_daily`
# are wired here as a PydanticAI `@agent.output_validator`: a hard `Violation` does
# `raise ModelRetry(...)` (the model sees exactly what it broke); a soft-only/empty
# result is accepted. No invariant logic lives here — the pure validators stay the
# single source of truth (LLM §4). The harness is brief-agnostic: `make_output_validator`
# takes `validate_fn` as an argument, so the shared module binds neither concrete
# validator name nor any `*LLMOutput` type (E10/E11 pass `validate_weekly`/`validate_daily`).
# --------------------------------------------------------------------------


def _deps_to_validation_context(deps: Any) -> ValidationContext:
    """Adapt the node's `RunContext` deps → the E7·P3 `ValidationContext` (the
    "interface requirement on E9" E7·P3 named as this phase's acceptance).

    Reads the computed values the deps carry (the budgets / band / safety-gate /
    week-plan-cards / knee / quality-pick the pure validator policies against) and
    builds the PydanticAI-free `ValidationContext` **field-by-field**. The single
    place the PydanticAI `RunContext` deps meet E7·P3's frozen-dataclass context —
    so a drift is a failing adapter test, not a silent mismatch. E10/E11 specialise
    this for their concrete deps shapes; the shared version maps the documented
    fields, reading each structurally (a `getattr` off the deps `BaseModel`).
    """

    def _get(name: str, default: Any = None) -> Any:
        return getattr(deps, name, default)

    budgets = _get("budgets")
    if budgets is None:
        # ValidationContext.budgets is required; a deps without it can't be
        # validated against the weekly invariants. E10/E11 always populate it.
        raise ValueError("deps must carry `budgets` (WeeklyBudgets) for validation")
    if not isinstance(budgets, WeeklyBudgets):
        budgets = WeeklyBudgets(
            hard_days=budgets["hard_days"],
            strength_sessions=budgets["strength_sessions"],
            long_run_km=budgets.get("long_run_km"),
            deload=budgets["deload"],
        )

    kwargs: dict[str, Any] = {"budgets": budgets}
    for name in (
        "quality_run_pick",
        "band",
        "knee_pain",
        "week_plan_cards",
        "safety_gate_triggered",
    ):
        value = _get(name)
        if value is not None:
            kwargs[name] = value
    return ValidationContext(**kwargs)


def _format_violations(violations: list) -> str:
    """Join hard `Violation`s into one human-readable `ModelRetry` message.

    One message of **all** hard violations' `rule` + `message` (DECISIONS Decision
    2) so a single retry can repair the whole brief within the ≤ 2 budget — the
    model "sees exactly what it broke" (LLM §4).
    """
    return "; ".join(f"{v.rule}: {v.message}" for v in violations)


def make_output_validator(validate_fn):
    """Build a PydanticAI `@agent.output_validator` wrapping the pure `validate_fn`.

    Brief-agnostic: `validate_fn` is the pure E7·P3 `validate_weekly`/`validate_daily`
    (or any `(output, ctx) -> list[Violation]`) the concrete node passes in, so the
    shared harness binds no concrete validator name. The returned async callable has
    PydanticAI's output-validator signature `(ctx: RunContext[Deps], output) -> output`
    (verified 1.105.0 surface): it (1) adapts `ctx.deps` → `ValidationContext`, (2)
    calls the pure `validate_fn` (which returns `list[Violation]`, never raises), (3)
    on **any** `Severity.hard` violation `raise ModelRetry(joined_message)`; a
    soft-only / empty result is **accepted** — the validator returns `output`
    unchanged (PydanticAI requires the validator to return the validated value).
    """

    async def _validate(ctx: RunContext[Any], output: Any) -> Any:
        validation_ctx = _deps_to_validation_context(ctx.deps)
        violations = validate_fn(output, validation_ctx)
        hard = [v for v in violations if v.severity is Severity.hard]
        if hard:
            raise ModelRetry(_format_violations(hard))
        return output

    return _validate


def register_output_validator(agent: Agent, validate_fn) -> None:
    """Register `make_output_validator(validate_fn)` on `agent` (the E10/E11 hook).

    The shared registration seam: a concrete node's `validate_fn` (the pure E7·P3
    `validate_weekly`/`validate_daily`) is wired onto the agent E9·P1 built, so the
    validator runs inside the `retries=MAX_RETRIES` (=2) budget. `process()` calls
    this before `agent.run` when the node exposes a validator (below).
    """
    agent.output_validator(make_output_validator(validate_fn))


def recheck_output(output: Any, validate_fn, validation_ctx: ValidationContext) -> None:
    """The belt-and-suspenders re-check before persist (LLM §4; DECISIONS Decision 3).

    After a **clean** `agent.run` returns the validated `output`, run the **same**
    pure `validate_fn` once more against the **same** `ValidationContext` — if it now
    reports a `Severity.hard` `Violation` (the LLM slipped one past, or a final
    adapter mismatch), `raise BriefGenerationError(code="brief_generation_failed")`
    so a constraint-breaking brief **never reaches the cache**. Deterministic and
    **LLM-free**: it runs the validator once and **errors**; it does **not**
    `ModelRetry` / re-invoke the model (the retries were the agent's job inside
    `agent.run`). This is the last gate before `save_output`.
    """
    violations = validate_fn(output, validation_ctx)
    if any(v.severity is Severity.hard for v in violations):
        raise BriefGenerationError(code="brief_generation_failed")


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

    def get_validate_fn(self):
        """The pure `(output, ValidationContext) -> list[Violation]` validator, or `None`.

        The brief-agnostic registration seam: E10/E11 return the pure E7·P3
        `validate_weekly`/`validate_daily` so `process()` wires it as the agent's
        `@agent.output_validator` (a hard `Violation` ⇒ `ModelRetry`). The shared
        base binds no concrete validator name; the default `None` leaves the agent
        un-validated (the E9·P1 behaviour).
        """
        return None

    def _instrument(self, agent: Agent) -> Agent:
        """The E12·P1 tracing hook — instrument the agent for Langfuse, or no-op.

        Delegates to `app.core.tracing.instrument_agent`, which sets `agent.instrument`
        to a Langfuse-backed `InstrumentationSettings` when the Langfuse keys are
        configured, and is a **hard no-op** otherwise (no client, no spans, no network) —
        so the brief behaviour is unchanged on the no-key path. Overridable; both
        AgentNodes inherit it. Imported inside so `agent_node.py`'s top level stays
        Langfuse/OTel-free (E9·P1's pure-core boundary).
        """
        from app.core.tracing import instrument_agent

        return instrument_agent(agent)

    def _trace_name(self) -> str:
        """The Langfuse trace name = the brief kind (E12·P1)."""
        return {"weekly": "WEEKLY_PLANNER", "daily": "DAILY_ADJUSTER"}.get(
            getattr(self, "mode", ""), "BRIEF"
        )

    def _traced_run(self, task_context: TaskContext, deps: Any):
        """The tagging context manager around `agent.run` (E12·P1) — a no-op when off.

        Tags the trace with `constitutionVersion` (the live `Profile`'s version when on the
        `TaskContext`, else the deps value, else the `Settings` fallback) + the model id.
        Imported inside so the top level stays Langfuse/OTel-free.
        """
        from app.core.tracing import resolve_constitution_version, traced_run

        profile = task_context.metadata.get("profile")
        version = getattr(profile, "constitution_version", None) or resolve_constitution_version(
            deps
        )
        return traced_run(
            self._trace_name(),
            constitution_version=version,
            model_id=self.get_agent_config().model_id,
        )

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
        # E12·P1: instrument the agent for Langfuse tracing (a no-op when unconfigured).
        agent = self._instrument(agent)
        validate_fn = self.get_validate_fn()
        if validate_fn is not None:
            register_output_validator(agent, validate_fn)
        deps = self.build_deps(task_context)
        try:
            # E12·P1: tag the trace (constitutionVersion + model) around the run; no-op off.
            with self._traced_run(task_context, deps):
                result = await agent.run(
                    self.build_run_input(task_context),
                    deps=deps,
                )
        except Exception as exc:
            if _is_timeout(exc):
                raise BriefGenerationError(code="upstream_timeout") from exc
            # Exhausted retries (UnexpectedModelBehavior) — the E9·P2 output-validator
            # ModelRetry'd past the retries=2 budget — invalid structure, and every
            # other model/HTTP failure (ModelHTTPError/ModelAPIError) derive from
            # AgentRunError → the generic LLM-failure code.
            if isinstance(exc, AgentRunError):
                raise BriefGenerationError(code="brief_generation_failed") from exc
            # Deferred model resolution (defer_model_check=True above) surfaces a
            # missing/blank ANTHROPIC_API_KEY here as pydantic-ai's UserError, on the
            # FIRST live run — map it to the stable LLM-failure code so a config gap
            # answers as the envelope 502, not an unhandled 500 (seen live 2026-07-23).
            if isinstance(exc, UserError):
                raise BriefGenerationError(code="brief_generation_failed") from exc
            raise
        # Belt-and-suspenders re-check before persist (E9·P2; LLM §4): re-run the
        # SAME pure validator against the SAME deps-derived ValidationContext once
        # more. A hard violation raises and stores NOTHING, so a constraint-breaking
        # brief never reaches the cache. Deterministic + LLM-free — no model re-run.
        if validate_fn is not None:
            recheck_output(result.output, validate_fn, _deps_to_validation_context(deps))
        self.save_output(result.output)
        return task_context
