# Plan: E1·P3 — Workflow engine primitives

Status: in-progress
Branch: feature/e1-p3-workflow-engine
Risk: medium
Created: 2026-06-03

> Epic **E1 — Foundation & API Skeleton**, phase **P3**. Source of truth:
> [`epics/E01-foundation.md`](../../../epics/E01-foundation.md) (§2 R6, §3 E1·P3, §4 acceptance, §6) ·
> grounded in [`docs/architecture/ARCHITECTURE.md`](../../../docs/architecture/ARCHITECTURE.md) §1
> (Orchestration / stack note), §2 (safety-gate router), §5 (workflows + node legend) and
> [`docs/architecture/LLM.md`](../../../docs/architecture/LLM.md) §0 (the brain). Curated findings in
> [`RESEARCH.md`](./RESEARCH.md). Builds on **E1·P1** (`app/core/` package exists). Adopts/trims the kept
> GenAI Launchpad `core/` primitives at `../genai-launchpad-main/app/launchpad/core/`.

## Goal

Adopt the kept Launchpad `core/` workflow primitives into `app/core/` — a DAG of `Node`/`RouterNode`/
`AgentNode` over a shared Pydantic `TaskContext` with a `stop_workflow()` short-circuit — so the two real
workflows (E5/E9/E10/E11) have an engine to plug into, with no business logic yet.

## Scope

- **`app/core/task_context.py`** — `TaskContext(BaseModel)`: shared, mutable engine state passed between
  nodes — `event`, `nodes` (per-node outputs), `metadata`, `should_stop`; helpers `update_node()` and
  `stop_workflow()` (ARCHITECTURE §1 Orchestration, §5). Internal engine state, **not** a wire model — it
  does not inherit the camelCase base from E1·P1 (MODELS "Conventions → Casing"; see Decisions).
- **`app/core/nodes.py`** — the three node base types (ARCHITECTURE §5 node legend):
  - `Node(ABC)` — deterministic processing; abstract `async process(ctx) -> TaskContext`; `save_output()`,
    `get_output()`, `node_name`, async `cleanup()`.
  - `RouterNode` (+ `BaseRouter`) — conditional branch / short-circuit. **Two distinct roles, kept from
    Launchpad:** `BaseRouter(Node)` is the *router node placed in the DAG* — the runner calls its
    `.route(ctx)` to pick the next edge — and it owns `routes: list[RouterNode]` + a `fallback`;
    `RouterNode` is a *single routing predicate* (not itself a graph `Node`) whose
    `determine_next_node(ctx)` **returns the next node** or `None`. `BaseRouter.route()` walks its `routes`
    in order, taking the first non-`None`, else `fallback`. It does not itself stop — the §2 short-circuit
    is a router *routing to* a terminal override node whose `process()` writes the brief and calls
    `ctx.stop_workflow()` (see Decisions). Our one router (`SafetyGateRouter`) needs only a single
    predicate + fallback; the split is kept for port fidelity, so **docstrings must spell out the two
    roles** — the names invert intuition (`BaseRouter` is the concrete in-graph node; `RouterNode` is the
    predicate).
  - `AgentNode(Node, ABC)` — **abstract LLM-call placeholder**: keeps the `OutputType`/`DepsType` seam and
    an abstract `get_agent_config()` + abstract `process()`, but **no** PydanticAI/provider construction
    (real wiring is E9 — LLM.md §0). No `pydantic_ai`/`boto3`/`google` imports.
- **`app/core/workflow.py`** — `WorkflowSchema` + `NodeConfig` (`node`, `connections`, `is_router`,
  `description`; **no** `concurrent_nodes`), `WorkflowValidator` (DAG: cycle-free, all-reachable, only
  routers may fan out >1, **and `is_router=True` only on a `BaseRouter` subclass**), and the `Workflow`
  runner: sync `run()` (wraps `asyncio.run`) + async
  `run_async()` that walk the graph, honoring `should_stop` and calling each node's `cleanup()` in a
  `finally`. Routing delegates to `BaseRouter.route()`.
- **`app/core/__init__.py`** — re-export the public primitives (`TaskContext`, `Node`, `RouterNode`,
  `BaseRouter`, `AgentNode`, `Workflow`, `WorkflowSchema`, `NodeConfig`).
- **Tests** (`tests/core/`) — a linear flow (Node → Node), a router branch (Node → RouterNode → one of two
  terminals), and a gated short-circuit (router routes to a terminal override whose `process()` calls
  `stop_workflow()` → the terminal runs and writes output, the downstream sentinel does not run), plus the
  3-node `Node → RouterNode → Node` end-to-end shape from epic §4 over one `TaskContext`. Plus the router
  DAG-constraint (undeclared route/fallback rejected) and the no-dropped-deps import guard.

## Out of Scope

- **Real LLM wiring** — PydanticAI `Agent` construction, provider models, structured `OutputType`s, the
  constitution prompt: all E9 (LLM.md §0). `AgentNode` stays abstract here.
- **The two real workflows** `WEEKLY_PLANNER` / `DAILY_ADJUSTER` and their domain nodes
  (`LoadAggregatesNode`, `SafetyGateRouter`, `GeneratePlanNode`, …) — E5/E9/E10/E11 (ARCHITECTURE §5).
- **Streaming** (`run_stream_async`, `AgentStreamingNode`), **`concurrent_nodes`**, and
  Celery/Redis/Postgres/Supabase/`vecs` — genuinely dropped, never carried over (ARCHITECTURE §1 stack
  note).
- **Langfuse tracing / spans / `trace_id`** — **deferred to E12, not dropped.** Langfuse is *kept-stack*
  observability (ARCHITECTURE §1 Components — "trace every LLM call"; epic R2 settings carry Langfuse keys;
  epic §7 "Langfuse (E12)"). It is simply not wired into the P3 primitives because there are no LLM calls
  yet (`AgentNode` is an abstract placeholder). The P3 port strips the Launchpad's inline spans; **E12
  re-adds tracing in `app/core`**, so — exactly like `pydantic_ai` — `langfuse` is **NOT** in the durable
  dropped-stack import ban (banning it would block E12). `trace_id` is left off `TaskContext` for now and
  returns with Langfuse in E12.
- DB persistence, endpoints, settings/auth/health (E1·P1, E1·P2, E2, E5).

## Research Summary

The Coach App reuses Datalumina's GenAI Launchpad but keeps **only** its FastAPI app, the `core/`
workflow primitives, PydanticAI, Jinja2, and Alembic; Postgres/pgvector, Celery, Redis, Supabase,
streaming and RAG are dropped (ARCHITECTURE §1 stack note). This phase ports the Launchpad
`core/` (`task.py`, `nodes/base.py`, `nodes/router.py`, `nodes/agent.py`, `workflow.py`, `schema.py`,
`validate.py`) into `app/core/`, trimmed to the kept stack. The contract (ARCHITECTURE §1, §5) is a DAG
of nodes over a shared Pydantic `TaskContext`: **Node** = deterministic, **RouterNode** = conditional
branch / short-circuit, **AgentNode** = LLM call (Claude, structured output) — but real PydanticAI
wiring lands in E9 (LLM.md §0), so `AgentNode` is an abstract placeholder here. A node may
`stop_workflow()`; the §2 safety-gate router (a `RouterNode`) short-circuits before the LLM — the
canonical early-stop the engine must support. Full keep/adapt/drop matrix and citations in
[`RESEARCH.md`](./RESEARCH.md).

## Decisions

- **Port (not import) the Launchpad `core/` into `app/core/`, trimmed to the kept stack** — the Launchpad
  is a sibling boilerplate, not a dependency; we own the primitives and strip Langfuse/streaming/
  concurrency/Celery so the kept-stack invariant (ARCHITECTURE §1) holds in our own tree.
- **`AgentNode` is an abstract placeholder, no provider/LLM wiring** — real PydanticAI `Agent`/model
  construction is **E9** (LLM.md §0). **PydanticAI is part of the kept stack** (ARCHITECTURE §1) and E9
  will import `pydantic_ai` in `app/core` to wrap the `Agent`, so `pydantic_ai` is **not** in the durable
  dropped-stack ban. What this phase forbids is narrower and **phase-scoped**: `app/core/nodes.py` must
  not yet import `pydantic_ai` or any provider SDK (`boto3`, `google`) — keeping P3 to the abstract seam
  subclasses fill in E9. The durable dropped-stack guard bans only the genuinely dropped deps
  (Langfuse/Celery/Redis/Postgres/pgvector/Supabase/`vecs`).
- **The safety-gate short-circuit runs its terminal node, *then* stops** — per ARCHITECTURE §2/§5 and
  E11, the gated path must still return a **code-written** REST/active-recovery brief (no LLM). So the
  router routes **to** the terminal override node (e.g. a `SafetyRestNode`); that node does its work in
  `process()` **and** calls `ctx.stop_workflow()`; the runner then breaks before downstream nodes
  (notably the `AgentNode`). The router itself does not stop before the terminal runs — that would skip
  the REST brief. This matches the Launchpad walk (stop checked at the top of the *next* iteration).
- **`TaskContext` is a plain snake_case `BaseModel`, not the camelCase wire base** — it is internal
  engine state never serialized to the client (MODELS "Conventions → Casing"); the camelCase brief
  payloads are separate response models in later epics. Avoids forcing engine state through wire aliasing.
- **Keep both sync `run()` and async `run_async()`** — workflows are invoked synchronously inline from
  endpoints (ARCHITECTURE §5), but nodes' `process()` is `async`; `run()` wraps `asyncio.run` for
  scripts/sync callers while `run_async()` lets an async route `await` it. Matches Launchpad.
- **Drop `concurrent_nodes` from `NodeConfig`** — single-user synchronous flows (ARCHITECTURE §1) never
  fan out concurrently; carrying it would be dead surface.
- **Keep `WorkflowValidator` (DAG/cycle/reachability/router-fanout) + add `is_router`↔`BaseRouter`
  type-check** — cheap correctness guard that makes malformed workflows fail at construction, not mid-run.
  The runner resolves a router edge by calling `node().route(ctx)`, which only exists on `BaseRouter`; so
  `is_router=True` on a node that is not a `BaseRouter` subclass must be rejected at construction (else it
  passes the fanout rule but blows up at runtime with `AttributeError`). The §5 workflows rely on both
  rules.
- **Constrain router output to the validated DAG** — a router's returned next node (route or `fallback`)
  must be one of the current node's declared `connections`; `_handle_router` rejects an undeclared target
  with a clear error. The static `WorkflowValidator` only checks declared edges, so without this a router
  could jump to an undeclared node at runtime (mid-run `KeyError` or an unreviewed path). This keeps the
  PLAN's claim that routing edges are declared in `WorkflowSchema` true at runtime, not just statically.

## Risks

- **Carrying over genuinely dropped-stack imports while porting** (streaming, Celery, Redis,
  Postgres/pgvector, Supabase, `vecs`) — mitigation: TASK-004 + final validation `grep` `app/core/` for
  `celery|redis|psycopg|pgvector|supabase|vecs|boto3` and assert none (epic §4 "no Postgres/Celery/Redis/
  pgvector imports"). **`pydantic_ai` and `langfuse` are deliberately NOT in this list** — both are kept
  stack (ARCHITECTURE §1): E9 imports `pydantic_ai` and E12 imports `langfuse` in `app/core`, so banning
  either durably would block a later epic. The P3 port still strips the Launchpad's inline Langfuse spans
  (no LLM calls yet) — a phase-scoped concern handled in the port (TASK-004 REFACTOR), not a durable ban.
- **`AgentNode` accidentally instantiable / requiring an LLM** — mitigation: keep `process()` and
  `get_agent_config()` `@abstractmethod`; a test asserts `AgentNode` cannot be instantiated directly and
  that a trivial concrete subclass needs no network/provider. A **phase-scoped** check
  (`! grep -nE "pydantic_ai|boto3|google\." app/core/nodes.py`) keeps P3's `nodes.py` provider-free
  without banning `pydantic_ai` elsewhere.
- **Gated short-circuit skips its terminal brief (stop fires too early)** — mitigation: the runner checks
  `should_stop` at the **top** of each iteration, so the terminal override node (routed-to) runs and sets
  stop in its own `process()` before the break; an early-stop test asserts the terminal node's output IS
  present and the downstream `AgentNode`-stand-in sentinel is NOT executed.
- **Router contract drift (router can't read context / can't stop / jumps off-DAG)** — mitigation:
  preserve Launchpad's `BaseRouter.route(ctx)` → assigns `ctx` to each sub-router before
  `determine_next_node`; `_handle_router` rejects a returned node whose class is not in the current node's
  declared `connections`; tests route via context state, stop from within the routed-to terminal, and
  assert an undeclared route/fallback raises.
- **DAG validator false-rejects a valid linear/branch shape** — mitigation: validator tests cover an
  accepted linear graph, an accepted router-fanout graph, and rejected cycle / unreachable / non-router
  multi-connection graphs.

## Acceptance Criteria

- [ ] `TaskContext` round-trips as a Pydantic model with `event`, `nodes`, `metadata`, `should_stop`;
      `update_node()` merges per-node output and `stop_workflow()` sets `should_stop=True` (unit test).
- [ ] `Node` is abstract (cannot instantiate without `process`); a concrete `Node` runs and
      `save_output()`/`get_output()` round-trip via `TaskContext.nodes` (unit test).
- [ ] `RouterNode`/`BaseRouter` select the next node from context state and fall back to `fallback` when no
      route matches (unit test).
- [ ] `AgentNode` is abstract — direct instantiation raises `TypeError`; a trivial concrete subclass needs
      **no** network/provider and exposes the `OutputType`/`get_agent_config()` seam (unit test). For the
      P3 placeholder boundary, `app/core/nodes.py` imports **no** `pydantic_ai`/`boto3`/`google` provider
      SDK (phase-scoped grep) — but `pydantic_ai` is kept stack and NOT durably banned (E9 adds it).
- [ ] `WorkflowValidator` **accepts** a valid linear graph and a valid router-fanout graph, and **rejects**
      a cycle, an unreachable node, a non-router node with >1 connection, **and a node marked
      `is_router=True` that is not a `BaseRouter` subclass** (unit tests).
- [ ] **Router output is DAG-constrained:** `_handle_router` raises a clear error when a router's returned
      route or `fallback` is a node class **not** in the current node's declared `connections` (unit test
      for an undeclared route and an undeclared fallback).
- [ ] A **linear** workflow (Node → Node) runs end-to-end over one `TaskContext`, both nodes' outputs
      present (test).
- [ ] A **router-branch** workflow (the epic §4 `Node → RouterNode → Node` 3-node shape) runs end-to-end
      over one `TaskContext` and reaches the branch the context selects (test).
- [ ] **Gated short-circuit (terminal-then-stop):** a router routes to a terminal override node that does
      its work in `process()` **and** calls `ctx.stop_workflow()`; the terminal node's output IS present,
      a sentinel node wired downstream of the router is NOT executed, and the run returns the partial
      `TaskContext` with `should_stop=True` (test). This is the §2 `SafetyGateRouter → SafetyRestNode + stop`
      pattern (REST brief still written, AgentNode skipped).
- [ ] Both `run()` (sync) and `run_async()` (async) drive the same workflow to the same result (test).
- [ ] **No dropped-stack imports** anywhere under `app/core/`:
      `grep -REn "celery|redis|psycopg|pgvector|supabase|vecs|boto3" app/core` is empty (epic §4;
      ARCHITECTURE §1 stack note). `pydantic_ai` (E9) and `langfuse` (E12) are intentionally excluded —
      both are kept stack; the P3 port ships no Langfuse spans yet, but the durable ban must not block E12.
- [ ] `uv run ruff check .` and `uv run pytest tests/core` pass.

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [x] TASK-001: TaskContext shared Pydantic state
- [x] TASK-002: Node and RouterNode base types
- [x] TASK-003: AgentNode base type (LLM placeholder)
- [x] TASK-004: WorkflowRunner executor with stop_workflow and tests
- [ ] TASK-005: Final Validation
