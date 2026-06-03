# Adversarial Review — Round 4 (verification)

**Run:** 2026-06-03 09:32 UTC
**Branch:** feature/e1-p3-workflow-engine
**Base:** staging
**Commits reviewed:** f07a5a7..2628cfb
**Prior rounds in scope:** reviews/round-1.md, round-2.md, round-3.md

> Verification pass after the round-3 fixes. It confirmed the within-schema fixes hold and found one
> residual: the node-name uniqueness check is per-schema, so the same-name collision can still happen
> across **composed** workflows. Fixed with composition-time collision detection. Codex loop stopped here
> (round 4, well past the 3-round cap): the remaining risk is a narrow edge of the composition feature the
> app's two independent workflows don't use, and every finding is fixed with a regression.

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

No-ship: the round-3 node-name fix is still incomplete for supported workflow composition and can corrupt parent outputs.

Findings:
- [high] Composed workflows can still overwrite same-named node outputs (app/core/nodes.py:36-46)
  `save_output()` stores every output under `self.node_name`, and `node_name` is only `__class__.__name__`. The new uniqueness validator only checks nodes within one `WorkflowSchema`, so two independently valid workflows can both contain a `Step` node and then be composed on the same `TaskContext`. The child run overwrites `ctx.nodes['Step']`, and downstream parent nodes can read the child's output instead of the parent's. I verified this with two valid one-node workflows named `Step`: after `ChildWF().run(context=parent_ctx)`, the parent `Step` output was replaced by the child output.
  Recommendation: Use a globally unique or namespaced output key, such as `module.qualname` or an explicit `NodeConfig.node_id` propagated into `save_output()`/`get_output()`, or reject parent/child output-key overlap before running with an existing context. Add a composed-workflow regression where parent and child have same-named nodes and the parent output must remain addressable.

Next steps:
- Fix output keying or add composition-time collision detection before shipping.
- Add a regression for same-named parent/child workflow nodes sharing one `TaskContext`.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Per-schema name uniqueness misses cross-workflow collisions under composition | high | fix | Took Codex's "reject parent/child output-key overlap" option (keeps the ergonomic class-name keys). When running with an existing parent context, reject a child node whose name matches a *different* parent node. Regression added. The app's two workflows are independent (no composition), so this hardens a feature not yet used. | f3bee5e |

Round-3 fixes confirmed: explicit-config requirement, name uniqueness, and model_validate parsing all hold; `tests/core` green and `ruff` clean.
