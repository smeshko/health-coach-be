# Adversarial Review — Round 1

**Run:** 2026-06-03 09:04 UTC
**Branch:** feature/e1-p3-workflow-engine
**Base:** staging
**Commits reviewed:** f07a5a7..aeb3738

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

No-ship: the engine has shared router state across concurrent runs, a validator/runtime graph mismatch, and exception paths that corrupt nested contexts.

Findings:
- [high] Router predicates are shared mutable instances across runs (app/core/nodes.py:96-109)
  `routes` and `fallback` are class-level node instances, and `route()` mutates each predicate's `task_context` before calling it. Concurrent workflow runs share the same `RouterNode` object, so any predicate using the provided `save_output()`/`get_output()` helpers can write to the wrong `TaskContext` or lose output. This is a data-isolation and corruption risk that single-threaded tests will not catch.
  Recommendation: Store router routes/fallbacks as classes or factories and instantiate them per route evaluation, or remove mutable `task_context` from `RouterNode` and make helpers take the context explicitly. Add a concurrent routing regression test.
- [high] Duplicate node configs can bypass DAG validation (app/core/workflow.py:131-137)
  Runtime registry construction silently overwrites `registry[node_config.node]` when the schema contains the same node twice, while the validator's `_config_for()` uses the first matching config. That lets validation approve one graph and execution run another; for example, a later duplicate can introduce a self-loop after cycle validation passed, causing stuck requests or repeated expensive nodes.
  Recommendation: Reject duplicate `NodeConfig.node` entries before DAG validation and build one config map that both validation and execution share. Add a test asserting duplicate node configs are invalid.
- [medium] Nested context metadata is not restored on failure (app/core/workflow.py:163-188)
  `metadata["nodes"]` is overwritten before execution and restored only after normal loop completion. If a node, cleanup, or router raises, the restore block is skipped, leaving an existing parent `TaskContext` pointed at the child workflow registry. A parent workflow that catches or retries after the child failure will operate with corrupted metadata.
  Recommendation: Wrap the metadata override and execution loop in a `try/finally` that restores the prior registry or removes `metadata["nodes"]` on every exit. Add a failing nested-workflow test.

Next steps:
- Fix the blocking engine-state issues above, then run the core tests in an environment with a writable temp directory.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Router predicates are shared class-level instances; `route()` mutates them (data isolation) | high | fix | Real latent footgun. Per Codex's rec, declare `routes`/`fallback` as **classes** and instantiate predicates fresh per `route()` call; return the fallback as a class (so an AgentNode fallback isn't constructed just to read its type in E9). Concurrency isn't a runtime condition (single sync process) but the fix is clean and future-proofs. | 544d6ee |
| 2 | Duplicate `NodeConfig.node` lets validator and runtime see different graphs | high | fix | Validator `_config_for` uses the first match; runtime registry overwrites with the last — a real validate/execute mismatch. Reject duplicate node entries at validation. | 2c41de1 |
| 3 | `metadata["nodes"]` not restored if a node/router raises (corrupts parent context) | med | fix | Real bug in the composition path. Wrap the registry override + walk in try/finally so the parent registry is restored on every exit. | 171b4b6 |
