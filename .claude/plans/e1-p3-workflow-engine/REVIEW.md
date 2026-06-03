# Review Summary — e1-p3-workflow-engine

**Rounds:** 4 (3 review + 1 verification)
**Fix commits:** 544d6ee..f3bee5e

## Rounds

| Round | Findings | Fixed | Deferred | Rejected |
|-------|----------|-------|----------|----------|
| 1     | 3        | 3     | 0        | 0        |
| 2     | 3        | 3     | 0        | 0        |
| 3     | 3        | 3     | 0        | 0        |
| 4 (verify) | 1   | 1     | 0        | 0        |

## Fixes

### Round 1 — shared state & validate/execute mismatch
- `544d6ee` — isolate router predicates per evaluation (routes/fallback as classes) (round-1 #1)
- `2c41de1` — reject duplicate `NodeConfig.node` at validation (round-1 #2)
- `171b4b6` — restore parent registry on workflow failure (try/finally) (round-1 #3)

### Round 2 — composition & router-config integrity
- `4f06ca8` — preserve a parent's `stop_workflow()` across composition (round-2 #1)
- `bc1b613` — reject a `BaseRouter` node without `is_router=True` (round-2 #2)
- `ac4a6de` — require the `start` node to have a `NodeConfig` (round-2 #3)

### Round 3 — validator completeness & event parsing
- `2628cfb` — require explicit configs for all connection targets (no post-validation synthesis);
  validate node class-name uniqueness; parse the event via `model_validate` (dict **or** model)
  (round-3 #1/#2/#3)

### Round 4 (verification) — cross-workflow composition
- `f3bee5e` — reject output-key collisions between a composed child and a different parent node (round-4 #1)

## Deferred

- None.

## Rejected

- None. Two Codex sub-suggestions were intentionally narrowed rather than rejected: (a) keying outputs by
  `module.qualname` — instead kept the ergonomic class-name keys and added name-uniqueness +
  composition-collision validation; (b) requiring every connection target declared was *adopted* (round-3),
  but auto-adding implicit terminal configs was removed rather than kept.

## Notes

- The engine now validates: unique node objects, unique class names, all connection targets declared,
  `start` present, `is_router ⟺ BaseRouter`, DAG cycle-free + all-reachable, DAG-constrained routing,
  and cross-composition output-key safety. Plus runtime: terminal-then-stop short-circuit, parent stop
  preservation, and registry restoration on failure.
- `pydantic_ai` (E9) and `langfuse` (E12) stay out of the durable dropped-stack ban (both kept stack);
  `app/core/nodes.py` is provider-free this phase.
- Codex logged transient sandbox `pytest`/temp-dir failures across rounds; `uv run pytest` is green
  (98 passed) here and they were never raised as findings.
- Final state: `uv run pytest` → 98 passed (`tests/core`: 38); `uv run ruff check .` clean; no dropped-stack
  imports under `app/core`.
