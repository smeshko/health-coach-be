# Adversarial Review — Round 3

**Run:** 2026-06-03 09:25 UTC
**Branch:** feature/e1-p3-workflow-engine
**Base:** staging
**Commits reviewed:** f07a5a7..ac4a6de
**Prior rounds in scope:** reviews/round-1.md, reviews/round-2.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

No-ship: the prior fixes are present, but the engine still accepts schemas that silently skip routers and can corrupt node outputs under plausible workflow composition.

Findings:
- [high] Implicit connection configs bypass router validation (app/core/workflow.py:157-158)
  `_initialize_nodes()` synthesizes `NodeConfig(node=connected)` for omitted connection targets after validation. That means an omitted `BaseRouter` never hits the `BaseRouter`/`is_router` checks, is registered with `is_router=False` and no connections, and then terminates without evaluating predicates. I confirmed `A -> omitted BaseRouter` validates and running it only executes `A`, which can bypass a safety/conditional router without an error.
  Recommendation: Require explicit `NodeConfig` entries for every connection target, or at minimum reject omitted `BaseRouter` and abstract node targets before registry construction. Add a regression for `Start -> omitted BaseRouter` that must fail at construction.
- [high] Node outputs collide on class-name keys (app/core/nodes.py:36-46)
  `save_output()` stores outputs under `self.node_name`, and `node_name` is only `__class__.__name__`. Distinct node classes from different modules with the same class name pass duplicate validation because validation keys by class object, but they write the same `TaskContext.nodes` slot. In composed workflows, generic names like `Start` or `Validate` can overwrite earlier outputs and make downstream nodes read the wrong result. I confirmed two different `Step` classes validate and the second overwrites the first.
  Recommendation: Key outputs by a unique stable identifier such as `module.qualname`, or add an explicit `output_key`/`node_id` to `NodeConfig` and validate uniqueness across the workflow before execution.
- [medium] Model event instances fail before the first node (app/core/workflow.py:186-187)
  For a fresh run, `_execute()` coerces input with `event_schema(**event)`, which only works for mappings. A caller passing an already parsed Pydantic event model gets `TypeError: argument after ** must be a mapping`, despite the public API accepting `event: Any` and workflows being intended for endpoint/script callers. Tests only cover dict input, so this would surface on first integration with a FastAPI handler that passes the request model directly.
  Recommendation: Use `self.workflow_schema.event_schema.model_validate(event)` for fresh runs and add regressions for both dict input and an existing event-model instance. Define whether `context=` runs should also validate or explicitly require a prevalidated shared event.

Next steps:
- Run `tests/core` in an environment with writable temp/cache; here `uv run pytest` and direct `python -m pytest` were blocked by read-only temp/cache access.
- Add adversarial regressions for omitted router configs, duplicate node output keys, and Pydantic model event input.

## Triage

All three are convergent validator/parsing completeness gaps (each round surfaces a different one on this
foundational engine). Fixed rather than escalated per the maintainer's "work autonomously" directive; a
verification round (round-4) follows and the codex loop stops there.

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Omitted connection targets synthesized after validation → an omitted BaseRouter is silently skipped | high | fix | Took Codex's stronger option: require every connection target to have an explicit NodeConfig and drop the post-validation synthesis (registry is just the declared configs). Closes the router-bypass and makes the graph fully explicit. | 2628cfb |
| 2 | Outputs key on `__class__.__name__` → two same-named classes overwrite each other | high | fix | Kept the ergonomic class-name keys and added a node-name uniqueness validation, rejecting the collision at construction. | 2628cfb |
| 3 | `event_schema(**event)` rejects an already-parsed event model | med | fix | Use `event_schema.model_validate(event)` so the runner accepts a dict or a model (an endpoint may pass its request model directly). Regressions for both. | 2628cfb |
