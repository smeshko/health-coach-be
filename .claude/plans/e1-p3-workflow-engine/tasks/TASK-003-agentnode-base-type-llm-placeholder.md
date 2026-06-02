# TASK-003: AgentNode base type (LLM placeholder)

Depends on: TASK-002
Suggested commit: `feat(core): add AgentNode abstract LLM placeholder`

## Goal

Add the abstract `AgentNode` base — the seam an LLM call will fill in E9 — without any PydanticAI or
provider wiring (LLM.md §0; ARCHITECTURE §5 node legend).

## Files

- `app/core/nodes.py` — add `AgentNode(Node, ABC)`:
  - inner `class OutputType(BaseModel)` and `class DepsType(BaseModel)` (the structured-output / deps
    seam; LLM.md §0–§1) — empty placeholders subclasses override.
  - `@abstractmethod def get_agent_config(self) -> AgentConfig` — abstract config hook (the PydanticAI
    `Agent`/model is constructed from this in **E9**, not here).
  - `@abstractmethod async def process(self, ctx: TaskContext) -> TaskContext` (re-declared abstract so
    `AgentNode` cannot be instantiated directly).
  - **No** `Agent`/provider construction, **no** `pydantic_ai`/`boto3`/`google`/Langfuse imports, no
    network. Adapted (stripped) from `../genai-launchpad-main/app/launchpad/core/nodes/agent.py`.
  - A minimal local `AgentConfig` dataclass holding only stack-neutral fields needed to declare intent
    now — `model_id: str`, `output_type: type = str`, `instructions: str | None = None` (enough for E9 to
    extend; no provider enum, no SDK types). Keep it tiny; richer config is E9's to add.
- `app/core/__init__.py` — re-export `AgentNode`, `AgentConfig`.
- `tests/core/test_agent_node.py` — new: abstractness + a trivial concrete subclass with no provider.

## Acceptance

- [ ] `AgentNode` cannot be instantiated directly — `AgentNode()` raises `TypeError` (abstract
      `get_agent_config` + `process`).
- [ ] A trivial concrete `AgentNode` subclass that implements `get_agent_config()` (returning an
      `AgentConfig`) and `process()` (returning the context, e.g. saving a stub `OutputType`) constructs
      and runs with **no** network/provider/SDK.
- [ ] `AgentNode` exposes the `OutputType` and `DepsType` seams (subclass can override them).
- [ ] **Phase-scoped provider check:** `grep -nE "pydantic_ai|boto3|google\.|langfuse" app/core/nodes.py`
      is empty (P3 keeps `nodes.py` provider-free; E9 adds the PydanticAI `Agent`). Note: `pydantic_ai` is
      **kept stack** — it is NOT in the durable dropped-stack ban (TASK-004), only excluded from this
      phase's `nodes.py`.
- [ ] `from app.core import AgentNode, AgentConfig` resolves.

## Steps

### RED
- [ ] `tests/core/test_agent_node.py`: assert `AgentNode()` raises `TypeError`; a concrete no-provider
      subclass constructs, `process()` runs and stores an `OutputType`, and `get_agent_config()` returns
      an `AgentConfig`.

### GREEN
- [ ] Add `AgentNode` + minimal `AgentConfig` to `app/core/nodes.py`; wire re-exports.

### REFACTOR
- [ ] Module/class docstring: "abstract placeholder — real PydanticAI wiring lands in E9 (LLM.md §0)".

## Notes

Each real workflow has exactly one `AgentNode` (`GeneratePlanNode` / `TuneSessionNode`) returning a strict
`OutputType` (LLM.md §0–§1), and the model emits only picks per derive-don't-emit (ARCHITECTURE §5). Here
we ship only the abstract shape so E9 can drop in the `Agent` without changing the engine. **PydanticAI is
kept stack** (ARCHITECTURE §1) — E9 will import `pydantic_ai` in `app/core` to wrap the `Agent`, so the
durable dropped-stack guard (TASK-004) must NOT ban `pydantic_ai`. This phase only keeps `nodes.py`
provider-free (a narrower, phase-scoped check) so the placeholder boundary is enforced without blocking E9.
