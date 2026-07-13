# Adversarial Validation — Round 3

**Run:** 2026-07-13 15:02 UTC
**Plan:** phase-19-4-deterministic-invariant-repair
**Status at start:** ready
**Prior rounds in scope:** validation/round-1.md, validation/round-2.md
**Reviewer:** Codex

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: the round-2 design repairs are otherwise coherent, but the plan is not implementation-ready because canonical prior-week lookup can miss API-accepted keys, and the required legacy fallback matrix remains incompletely tested.

Findings:
- [medium] Canonical lookup misses API-accepted ISO-week keys (tasks/TASK-001:10-16)
  The helper always formats the predecessor as zero-padded `YYYY-Www`, but `WeeklyBriefRequest` currently accepts and preserves values such as `2026-W1`, and `PersistPlanNode` stores that text verbatim. An in-order next-week generation therefore queries `2026-W01`, misses the accepted prior row, and cold-starts to `threshold`; textual aliases can also create multiple plans for one logical week. This is outside the documented backfill limitation and breaks the core in-order invariant.
  Recommendation: Apply — require canonicalization before lookup/persistence, compatibility for existing noncanonical rows, and padded/unpadded-key tests.
- [medium] Legacy fallback branches remain unpinned (tasks/TASK-001:35-43)
  Round 2 required missing-key and invalid-focus tests, and PLAN Risks promises those fallbacks, but TASK-001 tests only `constants:null`, null snapshots, and non-object JSON. An implementation that verifies `constants` is a dict but then uses `constants["quality_focus"]` passes every listed legacy test while still raising `KeyError` for `{}` or `{"constants": {}}`; invalid enum conversion can similarly raise if not caught.
  Recommendation: Apply — add missing `constants`, missing `quality_focus`, and invalid-value cases to TASK-001, TASK-003 item 3, and PLAN acceptance criteria.

Next steps:
- Apply both plan corrections, then rerun the plan review; the remaining focus transport, refresh replacement, ISO-calendar algorithm, and zone-merge requirements are coherent.

## Triage

Both verified. #1 confirmed against `app/api/schemas/weekly.py:103` `_validate_iso_week` —
it checks `week_str.isdigit()` then `return value` **verbatim**, so `2026-W1` (and even
`2026-W001`) persist unpadded. The design is otherwise called coherent/implementation-ready;
this is a converging tail (round 1: 5 high, round 2: 6 apply, round 3: 2 medium polish), not
a rewrite signal — so applied and proceeding to implement rather than pausing.

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Unpadded API-accepted `2026-W1` stored verbatim → padded prior-lookup misses it; aliases dup plans | med | apply | Root-cause fix: canonicalize `iso_week` at the request validator (D5), padded/unpadded tests | PLAN.md Scope/D5, TASK-001 step 0, TASK-003 |
| 2 | Legacy fallback matrix under-tested (`{}`, `{"constants": {}}`, invalid value would KeyError/ValueError) | med | apply | Specify `.get()`-only guards + full malformed-input test matrix | TASK-001 step 1 + tests, TASK-003 item 3 |
