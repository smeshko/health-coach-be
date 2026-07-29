# Adversarial Validation — Round 3

**Run:** 2026-07-28
**Plan:** corroborated-hard-day
**Status at start:** draft
**Reviewer:** codex
**Prior rounds in scope:** validation/round-1.md, validation/round-2.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: TASK-005 still misses a supported duplicate/retry path that can strand invalid effort, and Decision 5 understates the breadth and durability of historical reclassification.

Findings:
- [medium] TASK-005 skips valid corrections when the UUID is classified as new (docs/artifacts/plans/corroborated-hard-day/tasks/TASK-005-let-a-valid-effort-score-replace-an-invalid-stored-one.md:36-43)
  Proposed verdict: apply. TASK-005 only directs the implementer to widen the SQL update predicate and tests sequential syncs. The existing `_backfill_effort_scores` excludes every UUID in `new_uuids`, while `insert_new_by_uuid` derives that set before knowing whether an `ON CONFLICT DO NOTHING` insert actually won. Consequently, an intra-request pair `[uuid/99, uuid/9]` inserts the first invalid value and skips the valid correction. The same assumption creates a concurrent-sync race: a valid writer can lose the insert conflict but still be treated as new and excluded from repair. The workout then remains effort-absent and may be misclassified.
  Recommendation: Apply — require same-batch duplicate and conflicting-insert tests, and run the guarded valid-score repair for all incoming UUIDs rather than excluding `new_uuids`; update TASK-005, PLAN.md acceptance, and TASK-004 named evidence.
- [medium] Decision 5 still describes a narrower and more durable historical audit trail than the code provides (docs/artifacts/plans/corroborated-hard-day/DECISIONS.md:157-165)
  Proposed verdict: apply. A sync touching historical day D expands to every existing row through D+29 and calls full `recompute_day`, so the new classifier can change `hard_day` on many days whose workouts were not in the payload—not only D. Moreover, a dated `POST /brief/daily?refresh=true` recomputes the input fingerprint and can regenerate historical readiness after such a change. Therefore the claims that the preserved verdict is the durable record of what was shown and that “only forward days are scored under the new rule” are not generally true. The accepted historical mutation surface is materially broader than documented.
  Recommendation: Apply — document the D…D+29 full-recompute cascade and the explicit-refresh exception, or add guards/tests if historical readiness must be immutable; update DECISIONS.md and PLAN.md, plus TASK-004 if a behavioral guarantee is chosen.

Next steps:
- Repair TASK-005's dedupe/concurrency coverage before implementation.
- Clarify or constrain Decision 5's historical cascade and refresh behavior.
- No change is needed for task ordering or constant definitions: PLAN.md order places TASK-005 before final TASK-004, and TASK-002 defines the shared constants first.
- Do not reopen the two explicit round-2 rejects; neither finding depends on watch failure or non-Apple source selection.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | TASK-005 misses same-batch duplicates — `insert_new_by_uuid` keeps the first occurrence, so `[uuid/99, uuid/9]` in one payload strands the invalid score | med | apply | Verified at `_upsert.py:56-61`: the `seen` set keeps the first row per uuid and reports it in `new_uuids`, so the corrected copy is dropped by the insert *and* excluded from the backfill. The fix is free — the NULL-or-invalid WHERE guard already protects valid stored data, so the `new_uuids` exclusion can just go. Concurrent-writer race not separately specified (single-user, sequential syncs). | TASK-005, PLAN.md:Acceptance Criteria, TASK-004 |
| 2 | Decision 5 understates the historical mutation surface — the cascade is D…D+29, and `refresh=true` can regenerate a historical brief | med | apply | Verified: `_expand_forward_window` + `recompute_day` at `engine:852-854` recompute every existing row through D+29, and `refresh: bool` exists on both brief routes (`daily.py:106`, `weekly.py:155`). The round-2 wording I wrote was narrower than the code. Rewritten to claim only what is true: nothing in the *automatic* sync path rewrites a historical readiness verdict. | PLAN.md:Risks, DECISIONS.md:Decision 5 |

**Round-3 close-out.** Both findings were narrow corrections to text added during
validation, not defects in the plan's design — no structural rewrite indicated. Per the
3-round cap, the plan owner chose apply-and-stop; no round 4.
