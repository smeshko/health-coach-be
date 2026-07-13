# Adversarial Review — Round 2 (post-implementation)

**Run:** 2026-07-13 19:38 UTC
**Branch:** fix/phase-19-4-deterministic-invariant-repair
**Base:** staging
**Commits reviewed:** 9bac074..2c43095
**Prior rounds in scope:** reviews/round-1.md
**Reviewer:** Codex

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

Do not ship: the zone fallback preserves cadence validation and correctly emits/persists zones_changed=false, and migration 0004 structurally handles empty, canonical, multi-alias, and repeat-run cases. However, its collision ordering can irreversibly delete the newest plan.

Findings:
- [medium] Collision cleanup can delete the newest plan across offset changes (alembic/versions/0004_canonicalize_plans_iso_week.py:45-59)
  The survivor is chosen by lexicographically comparing offset-bearing created_at strings, not their actual instants. For ISO week 2026-W43, an older row created at 2026-10-25T03:50:00+03:00 compares greater than a newer row created after Sofia's DST rollback at 2026-10-25T03:10:00+02:00. If those rows use aliases such as W43 and W043, the migration deletes the newer plan and retains the older payload and quality-focus state. created_at is also nullable, making ties dependent on unspecified SELECT order.
  Recommendation: Parse valid timestamps as aware datetimes and compare normalized UTC instants, with id as a deterministic tie-breaker for equal, missing, or malformed timestamps. Add DST-offset, null/tie, and three-alias collision tests.

Next steps:
- Fix collision survivor ordering before deploying migration 0004.
- Add explicit empty-table, upgrade-downgrade-upgrade idempotence, multi-alias collision, and changed-zones-plus-invalid-cadence regression tests.

## Triage

Confirmed the two round-1 fixes are sufficient (Codex: cadence still validates, `zones_changed`
flows correctly, migration handles empty/canonical/multi-alias/repeat). One new finding on the
migration fix itself.

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Migration 0004 picks the collision survivor by lexicographic offset-string compare → a DST-rollback `+02:00` later row loses to an earlier `+03:00` row; null `created_at` is SELECT-order-dependent | med | fix | Real (edge) data-loss across DST; now parses aware datetimes → UTC instants with `id` tie-breaker, + DST/null/three-alias/idempotent tests | d93d3bb |
