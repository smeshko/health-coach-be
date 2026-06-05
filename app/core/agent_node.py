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

from pydantic import BaseModel
from pydantic_ai import Agent, ToolOutput
from pydantic_ai.settings import ModelSettings

from app.core.nodes import AgentConfig

# --- LLM §2 model settings (the single home of these knobs; observable in tests) ---

# Low temperature keeps the model's picks stable (LLM §2 "low — keep picks stable").
LOW_TEMPERATURE: float = 0.1
# The ≤ 2 output-validator retry budget the E9·P2 `@agent.output_validator` consumes
# (LLM §2/§4 "Retries ≤ 2"). There is no public `agent.retries`; this sets the
# private `agent._max_output_retries`.
MAX_RETRIES: int = 2
# Per-call request timeout so a hung upstream surfaces as `upstream_timeout` (LLM §5).
CALL_TIMEOUT_S: float = 60.0


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
