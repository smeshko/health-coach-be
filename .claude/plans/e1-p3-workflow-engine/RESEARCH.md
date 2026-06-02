# Research: E1·P3 — Workflow engine primitives

Curated findings only — no raw conversation transcripts. This phase **adopts and trims** the kept GenAI
Launchpad `core/` workflow primitives for the Coach App. The Launchpad boilerplate is a sibling of the
repo at `../genai-launchpad-main/`.

## Key Files & Directories

### Launchpad source inspected (sibling boilerplate — reference only, not in this repo)
- `../genai-launchpad-main/app/launchpad/core/task.py` — `TaskContext(BaseModel)`: `event`, `nodes`,
  `metadata`, `should_stop`, `trace_id`; `update_node()`, `stop_workflow()`.
- `../genai-launchpad-main/app/launchpad/core/nodes/base.py` — `Node(ABC)` with `OutputType`,
  `process()` (abstract, async), `save_output()`, `get_output()`, `node_name`, `cleanup()`.
- `../genai-launchpad-main/app/launchpad/core/nodes/router.py` — `BaseRouter(Node)` (holds `routes` +
  `fallback`, `.route()`) and `RouterNode(ABC)` (`.determine_next_node()`).
- `../genai-launchpad-main/app/launchpad/core/nodes/agent.py` — `AgentNode(Node, ABC)` + `AgentConfig`
  dataclass + `ModelProvider` enum; wraps a PydanticAI `Agent`, constructs provider model instances
  (OpenAI/Anthropic/Bedrock/Google/Ollama/Azure) in `__init__`.
- `../genai-launchpad-main/app/launchpad/core/workflow.py` — `Workflow(ABC)`: `workflow_schema`,
  `run()` / `run_async()` / `run_stream_async()`, `__run()` graph walk, `_get_next_node_class()`,
  `_handle_router()`. Carries Langfuse spans + streaming + nested-workflow composition.
- `../genai-launchpad-main/app/launchpad/core/schema.py` — `NodeConfig` (`node`, `connections`,
  `is_router`, `description`, `concurrent_nodes`) and `WorkflowSchema` (`event_schema`, `start`, `nodes`).
- `../genai-launchpad-main/app/launchpad/core/validate.py` — `WorkflowValidator`: DAG cycle check,
  reachability, and "only routers may have >1 connection".
- `../genai-launchpad-main/app/launchpad/workflows/examples/quickstart/` — a worked `Workflow` +
  `BaseRouter`/`RouterNode` usage (`ticket_router_node.py`).

### Target files this phase creates (in THIS repo, do not exist yet)
- `app/core/task_context.py` — `TaskContext`.
- `app/core/nodes.py` — `Node`, `RouterNode` (+ `BaseRouter`), `AgentNode`.
- `app/core/workflow.py` — `WorkflowSchema`, `NodeConfig`, `WorkflowValidator`, `Workflow`/runner.
- `tests/core/test_workflow.py` (+ siblings) — linear, router-branch, early-stop tests.

## Architecture Facts

- **Orchestration contract** (ARCHITECTURE §1 Orchestration): "DAG of nodes over a shared Pydantic
  `TaskContext`; node types `Node` / `RouterNode` / `AgentNode`."
- **Node legend** (ARCHITECTURE §5): **Node** = deterministic processing · **RouterNode** = conditional
  branch / short-circuit · **AgentNode** = LLM call (Claude, structured output). A node may
  `stop_workflow()`.
- **Safety gate is a RouterNode** (ARCHITECTURE §2, §5; E11): `SafetyGateRouter` routes to a
  `RestDayNode` + stop **before** the LLM is consulted — the canonical early-`stop_workflow()` usage. The
  gated path must still return a **code-written** REST/active-recovery brief (no LLM), so the terminal
  override node (`RestDayNode`) must **run, write its output, then stop** — the router must not stop before
  the terminal runs (that would skip the REST brief). Stop is checked at the top of the next iteration.
- **The two real workflows** (ARCHITECTURE §5) that build on these primitives later:
  `WEEKLY_PLANNER` (`/brief/weekly`) and `DAILY_ADJUSTER` (`/brief/daily`), each with exactly one
  `AgentNode` (`GeneratePlanNode` / `TuneSessionNode`).
- **One AgentNode per workflow, structured output** (LLM.md §0, §1): each `AgentNode` wraps a PydanticAI
  `Agent` returning a strict `OutputType`; the model performs no arithmetic. **Real PydanticAI wiring is
  E9** — here `AgentNode` stays an abstract placeholder.
- **derive-don't-emit** (ARCHITECTURE §5, LLM.md §3): the `AgentNode` emits only picks; downstream
  `Node`s fill every derived attribute — confirms the engine just needs a clean `Node`/`RouterNode`/
  `AgentNode` separation; no business logic here.
- **Invoked synchronously** (ARCHITECTURE §5): workflows run inline from their endpoints in one
  synchronous process — no Celery/Redis/background workers (ARCHITECTURE §1 stack note). The runner needs
  a synchronous entry (`run()`), even though nodes' `process()` is `async`.
- **Casing** (MODELS "Conventions → Casing"): wire is camelCase / Python snake_case via a Pydantic
  `alias_generator`. `TaskContext` is **internal engine state**, not a wire model, so it is plain
  snake_case `BaseModel` (it does not inherit the camelCase wire base from E1·P1); the camelCase brief
  payloads are separate response models built in later epics.

## Constraints

- **Keep ONLY the workflow primitives.** Drop everything the Coach App doesn't use (ARCHITECTURE §1
  stack note): Langfuse tracing/spans, Celery/Redis, streaming (`run_stream_async`,
  `AgentStreamingNode`), `concurrent_nodes`, Postgres/Supabase, `vecs`/RAG.
- **AgentNode is abstract here** — no PydanticAI `Agent` construction, no provider SDK imports
  (`boto3` / `google`) and no `pydantic_ai` in `app/core/nodes.py` **for this phase**. Real wiring lands
  in E9 (LLM.md §0). `process()` stays `@abstractmethod`; `get_agent_config()` is the abstract seam
  subclasses fill in E9. NOTE: `pydantic_ai` is **kept stack** (ARCHITECTURE §1) — E9 *will* import it in
  `app/core`, so the durable dropped-stack guard must NOT ban `pydantic_ai`; the P3 no-provider check is
  scoped to `app/core/nodes.py` only.
- **No genuinely-dropped imports anywhere** under `app/core/`: Langfuse, Celery, Redis,
  Postgres/`psycopg`/pgvector, Supabase, `vecs`, `boto3` (epic §4 acceptance / ARCHITECTURE §1).
  `pydantic_ai` is excluded from this ban (kept stack).
- **`stop_workflow()` short-circuits — but the routed-to terminal runs first.** Stop is checked at the
  top of each iteration. The §2 gate pattern is: router routes **to** `RestDayNode`; `RestDayNode.process`
  writes the REST brief **and** calls `ctx.stop_workflow()`; the loop then breaks before the `AgentNode`.
  A router must not stop *before* its terminal runs (ARCHITECTURE §2/§5; E11).
- **DAG validation + runtime DAG-constraint**: statically, only `is_router` nodes may have multiple
  connections; non-routers with >1 connection are a schema error; cycles and unreachable nodes are
  rejected (carried from Launchpad `validate.py`). **Add a type-check the Launchpad lacks**: a node marked
  `is_router=True` must be a `BaseRouter` subclass — otherwise it passes the fanout rule but the runner's
  `node().route(ctx)` call (only on `BaseRouter`) blows up at runtime with `AttributeError`. At runtime,
  `_handle_router` additionally rejects a router target (route or fallback) whose class is not among the
  current node's declared `connections`, so routing can't jump off the validated DAG (Launchpad leaves
  this unguarded too).
- Stay greenfield-minimal: the engine ships with no domain nodes — those arrive in E5/E9/E10/E11.

## What we KEEP vs ADAPT vs DROP (Launchpad → Coach App)

| Item | Decision | Notes |
|---|---|---|
| `TaskContext` (event/nodes/metadata/should_stop, `update_node`, `stop_workflow`) | **KEEP** | Drop `trace_id` (Langfuse-only). |
| `Node` (OutputType/process/save_output/get_output/node_name/cleanup) | **KEEP** | As-is; `process()` abstract async. |
| `BaseRouter` + `RouterNode` (routes/fallback/route/determine_next_node) | **KEEP** | The conditional-branch/short-circuit primitive. |
| `AgentNode` | **ADAPT → abstract placeholder** | Keep the class + `OutputType`/`DepsType` seam + abstract `get_agent_config()`/`process()`; **strip** PydanticAI/provider construction (E9 fills it). |
| `WorkflowSchema` / `NodeConfig` | **ADAPT** | Drop `concurrent_nodes` (no concurrency in single-user sync flows). Keep `event_schema`, `start`, `nodes`, `is_router`. |
| `WorkflowValidator` (DAG/cycle/reachability/router-fanout) | **KEEP** | Core correctness guard. |
| `Workflow.run()` / `run_async()` / `__run()` graph walk + `_handle_router()` | **KEEP (trimmed) + HARDEN** | Keep sync `run()` + async `run_async()` and the walk honoring `should_stop`. **Drop** Langfuse spans/`_observation_context`/`NoOpSpan`, `run_stream_async`, `AgentStreamingNode` branch. Keep `cleanup()` in a `finally`. **Add** a DAG-constraint in `_handle_router`: reject a route/fallback whose class is not in the current node's declared `connections` (Launchpad leaves this unguarded). |
| Langfuse (`get_client`, spans, `LangfuseAuthenticationError`, `trace_id`) | **DROP** | E12 concern; not in kept stack. |
| Streaming (`run_stream_async`, `AgentStreamingNode`) | **DROP** | Streaming dropped (ARCHITECTURE §1). |
| `concurrent_nodes` / `core/nodes/concurrent.py` | **DROP** | No concurrency needed. |
| Celery/Redis/Postgres/Supabase/`vecs` | **DROP** | ARCHITECTURE §1 stack note. |

## Useful Commands

```bash
# inspect the kept Launchpad primitives we adopt
ls ../genai-launchpad-main/app/launchpad/core ../genai-launchpad-main/app/launchpad/core/nodes
# guard: no genuinely-dropped-stack imports leak into app/core (pydantic_ai is kept stack — excluded)
grep -REn "langfuse|celery|redis|psycopg|pgvector|supabase|vecs|boto3" app/core || echo "clean"
# phase-scoped: P3 nodes.py must stay provider-free (pydantic_ai/agent wiring is E9)
grep -nE "pydantic_ai|boto3|google\." app/core/nodes.py || echo "nodes.py provider-free"
# run the engine tests
uv run pytest tests/core -q
uv run ruff check .
```

## Uncertainty

- **Sync vs async runner.** Launchpad nodes' `process()` is `async`; the Coach App runs workflows inline
  in a sync FastAPI handler (ARCHITECTURE §5). Resolved: keep both — `run()` (sync, wraps `asyncio.run`)
  and `run_async()` — matching Launchpad, so an async route can `await run_async()` and a script can call
  `run()`. Nodes stay `async def process`.
- **Does the router instance get the context?** In Launchpad `_handle_router()` instantiates the router
  with no args then calls `route(task_context)`, which assigns `task_context` onto each sub-router before
  `determine_next_node`. Resolved: preserve that exact contract so the §2 `SafetyGateRouter` can read
  context and **select** the terminal (`RestDayNode`). The router does not stop — `task_context.`
  `stop_workflow()` is called by the routed-to terminal's `process()` (see next bullet).
- **Where does `stop_workflow()` get called from, and does the terminal still run?** The §2 gate must
  route **to** a terminal (`RestDayNode`) that writes a code-only REST brief, so stop cannot fire before
  that node runs. Resolved: the terminal node's own `process()` writes its output **and** calls
  `ctx.stop_workflow()`; the runner checks `should_stop` at the top of the *next* iteration, so the
  terminal runs and the downstream `AgentNode` is skipped. Test asserts the terminal's output is present
  AND the downstream sentinel did not run (not just "later nodes don't run").
- **Can a router jump off the validated DAG?** Launchpad's `_handle_router` maps whatever node
  `route()` returns to its class with no check against `connections`, so a buggy route/fallback could hit
  an undeclared node (mid-run `KeyError` / unreviewed path). Resolved: harden `_handle_router` to reject a
  returned class not in the current node's declared `connections`; tests cover undeclared route + fallback.

## References

- `epics/E01-foundation.md` §1, §2 (R6), §3 (E1·P3), §4 (acceptance), §6.
- `docs/architecture/ARCHITECTURE.md` §1 (Orchestration / stack note), §2 (safety gate router), §5
  (workflows + node legend).
- `docs/architecture/LLM.md` §0 (the brain — one AgentNode/workflow, structured OutputType, no
  arithmetic), §1 (the two agents).
- `docs/architecture/MODELS.md` "Conventions → Casing" (TaskContext is internal, not a wire model).
- Launchpad `core/` sources listed under **Key Files** above.
