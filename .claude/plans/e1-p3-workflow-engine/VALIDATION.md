# Validation Summary — e1-p3-workflow-engine

**Rounds:** 3
**Plan status at validation:** draft
**Run on:** 2026-06-03

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 3        | 3       | 0        | 0        |
| 2     | 2        | 2       | 0        | 0        |
| 3     | 1        | 1       | 0        | 0        |

Round 3 returned one finding — the last echo of the round-1/round-2 stop-semantics fix (a documentation
consistency cleanup, no new behavioural defect). It was applied; the 3-round cap was reached, so validation
stops here. The router type-check and `pydantic_ai` fixes were confirmed resolved in round 3.

## Applied

### Round 1
- TASK-004, TASK-002, TASK-005, PLAN.md (Decisions/Risks/Acceptance), RESEARCH.md — **stop semantics:** the
  §2 safety gate routes **to** a terminal override node (`RestDayNode`) whose `process()` writes the REST
  brief **and** calls `stop_workflow()`; the router no longer stops before the terminal runs, so the gated
  code-written brief is preserved (round-1 #1).
- PLAN.md (Decisions/Risks/Acceptance), RESEARCH.md, TASK-003, TASK-004, TASK-005 — **`pydantic_ai` is kept
  stack:** removed it from the durable dropped-stack ban (now bans
  `langfuse|celery|redis|psycopg|pgvector|supabase|vecs|boto3` only); the no-provider check is scoped to
  `app/core/nodes.py` so E9 can wire the PydanticAI `Agent` in `app/core` (round-1 #2).
- PLAN.md (Decisions/Risks/Acceptance), RESEARCH.md, TASK-004, TASK-005 — **router DAG-constraint:**
  `_handle_router` rejects a route/fallback whose class is not in the current node's declared
  `connections`, with tests for an undeclared route and an undeclared fallback (round-1 #3).

### Round 2
- TASK-002 (RED + acceptance), PLAN.md (node desc + tests bullet) — removed residual "router branch sets
  stop" wording so all layers describe terminal-then-stop consistently; the stop is the terminal's
  `process()` job (round-2 #1).
- PLAN.md (Scope validator + Decisions + Acceptance), RESEARCH.md, TASK-004 (validator + acceptance + RED),
  TASK-005 — **`is_router`↔`BaseRouter` type-check:** `WorkflowValidator` rejects `is_router=True` on a node
  that is not a `BaseRouter` subclass (else the runner's `node().route()` fails at runtime), with test
  coverage (round-2 #2).

### Round 3
- TASK-002 (`## Files` test summary), RESEARCH.md (Uncertainty bullet) — last two echoes of the old
  "router calls stop" wording corrected to terminal-then-stop (round-3 #1).

## Deferred

- (none)

## Rejected

- (none)
