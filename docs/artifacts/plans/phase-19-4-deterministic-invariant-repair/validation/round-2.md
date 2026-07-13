# Adversarial Validation — Round 2

**Run:** 2026-07-13 14:45 UTC
**Plan:** phase-19-4-deterministic-invariant-repair
**Status at start:** ready
**Prior rounds in scope:** validation/round-1.md
**Reviewer:** Codex

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship. Always carrying quality_focus does not currently corrupt constantsRecomputed or known snapshot readers, and the Phase 19.6 deferral is defensible. However, the rewrite can crash against legacy rows, falsely claims out-of-order safety, and still fails to prove the complete zone and weekly-alternation contracts.

Findings:
- [high] Apply — legacy not-due rows can crash the prior-focus lookup (tasks/TASK-001:8-12)
  Existing not-due plans persist valid JSON with inputs_snapshot.constants set to null, and inputs_snapshot itself is nullable. The proposed constants["quality_focus"] access therefore raises TypeError rather than taking the documented fallback. This is a likely first-week-after-deployment failure, not merely malformed-data handling.
  Recommendation: Apply; require structural type guards plus tests for legacy constants:null, nullable snapshots, non-object JSON, missing keys, and invalid focus values.
- [high] Apply — exact-W-1 lookup is not out-of-order or concurrency safe (PLAN.md:88-91)
  Generating W+1 before W exists, or before W commits, makes W+1 take the cold-start THRESHOLD fallback; later generating W can also persist THRESHOLD. The per-week UNIQUE constraint serializes only duplicate writes to the same week, so adjacent stored weeks can violate the core alternation invariant and remain stale indefinitely.
  Recommendation: Apply; define order-independent anchoring, serialization/reconciliation, and concurrent/backfill tests, or explicitly remove the unsupported out-of-order-safe claim.
- [high] Apply — zone acceptance can pass while rhr_baseline remains stale (PLAN.md:127-130)
  The merge steps mention zones.new_rhr, but acceptance tests assert only moved max-HR and zone bounds. Because compute_zones ignores RHR, those assertions cannot detect omission of thresholds.rhr_baseline. The default-path demand that all thresholds remain byte-identical is also ambiguous on a due run because cadence_current_spm may independently change.
  Recommendation: Apply; add an RHR-only move with unchanged zone bounds and rhr_baseline==new_rhr, and narrow default byte-identity to max_hr/rhr_baseline or pin cadence to a no-op.
- [medium] Apply — TASK-003 does not exercise the full weekly acceptance path (tasks/TASK-003:3-6)
  TASK-001 explicitly tests only prior THRESHOLD to current VO2, not the required persisted W to persisted W+1 transition back to THRESHOLD. Its reader comparison can directly feed the same dict to both helpers, bypassing ComputeBudgetsNode metadata transport, while "refresh/re-run" can avoid the actual refresh=true delete/regenerate transaction.
  Recommendation: Apply; require two committed adjacent generations, transport through metadata["computed"]["constants"] into GeneratePlanNode.build_deps, and a service/route refresh=true replacement whose persisted focus is unchanged.
- [medium] Apply — prior-week key conversion is underspecified at ISO-year boundaries (tasks/TASK-001:8-10)
  The task specifies Monday minus seven days followed by "YYYY-Www" but does not require conversion through isocalendar or ISO %G/%V formatting. At W01, calendar-year formatting can silently query the wrong year, and no W01/W53 test would detect the repeated cold-start focus.
  Recommendation: Apply; prescribe date.isocalendar-based formatting and test W01 across both 52- and 53-week predecessor years.
- [medium] Apply — RESEARCH still recommends the rejected Meta persistence design (RESEARCH.md:17-33)
  The original quality-focus section concludes "Hence D1 (persist in Meta)" and documents the Meta schema path, directly contradicting the later DB-row decision and PLAN's explicit rejection.
  Recommendation: Apply; rewrite or remove the stale Meta section so RESEARCH consistently specifies plans.inputs_snapshot persistence.

Next steps:
- Revise PLAN.md, RESEARCH.md, TASK-001, TASK-002, and TASK-003 around the findings above.
- Keep the runtime max-HR provider in Phase 19.6.
- Re-run adversarial validation after the acceptance tests are made explicit.

## Triage

All six confirmed against current code (`plans.inputs_snapshot` is nullable; not-due rows
store `constants: null` per `weekly_planner.py:745`; `compute_zones` is %max-only).

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Legacy `constants: null` / nullable snapshot / non-object JSON crashes `constants["quality_focus"]` | high | apply | Real first-week-after-deploy crash; needs structural `isinstance` guards + tests | TASK-001, TASK-003 |
| 2 | Exact-W-1 lookup not out-of-order/backfill safe; adjacent stored weeks can both be THRESHOLD | high | apply | True; over-claimed. Scope to in-order (normal path), document backfill as a deterministic known limitation — no reconciliation engine | PLAN.md D1/Risks, TASK-001, TASK-003 |
| 3 | Zone acceptance can't detect a stale `rhr_baseline` (compute_zones ignores RHR); default byte-identity ambiguous vs cadence | high | apply | Add an RHR-only-move test asserting `rhr_baseline==new_rhr` + zones unchanged; narrow default identity to max_hr/rhr_baseline | PLAN.md AC, TASK-002, TASK-003 |
| 4 | TASK-003 helper-level checks bypass metadata transport + real `refresh=true` | med | apply | Require two committed adjacent generations + transport through `metadata["computed"]["constants"]` + a real refresh replacement | TASK-003 |
| 5 | Prior-week key at ISO-year boundary needs `isocalendar`/`%G-W%V`, not calendar-year formatting; add W01/W53 tests | med | apply | Correct — `_iso_week_monday` parses safely but the reverse (date→key) must be ISO-formatted | TASK-001, TASK-003 |
| 6 | RESEARCH.md still concludes "persist in Meta", contradicting the DB decision | med | apply | Stale; rewrite the section to the `inputs_snapshot` persistence | RESEARCH.md |
