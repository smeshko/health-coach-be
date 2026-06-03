# Adversarial Validation — Round 1

**Run:** 2026-06-03 02:55 UTC
**Plan:** e4-p1-build-db-etl
**Status at start:** draft

## Codex output

<!-- Codex was unavailable (hard usage limit, not the gpt-image-2 bug — the
CODEX_DISABLE_IMAGE_GENERATION=1 / OPENAI_IMAGE_MODEL="" env fix was applied and the runtime got past
image-gen). Two attempts both returned:
  "You've hit your usage limit. ... try again at 5:18 AM."
Per the runbook fallback, this is a rigorous MANUAL adversarial review challenging the same two axes:
(1) fidelity vs the cited architecture docs, (2) internal coherence + final-validation coverage. -->

**codex unavailable — manual review.** Codex hit a hard usage/credits limit on two attempts (the
image-generation env fix worked; the runtime got past it and failed on quota). Falling back to a manual
adversarial review per the runbook.

### Manual review notes

**Axis 1 — fidelity vs architecture docs (DB.md §0/§1/§6, ARCHITECTURE §3/§6):**
- Four-table set (`records`/`workouts`/`workout_statistics`/`activity_summary`) matches DB.md §1's mirrored
  ingest set. ✓
- Raw deltas correctly excluded: no `uuid`/`origin`/`effort_score`/`physical_effort`; `activity_summary`
  keeps `date_components` (rename deferred to E4·P3); TEXT timestamps verbatim. Matches DB.md §1 callout +
  ARCHITECTURE §3, DB.md §0. ✓
- Streaming mandate (`iterparse` + `clear`, no DOM) matches epic R1 + ARCHITECTURE §6. ✓
- Wholesale `DROP TABLE` rebuild / never-opened-at-runtime / offline matches DB.md §0/§3/§7-d1 +
  ARCHITECTURE §3/§6. ✓
- **Finding 1 (apply, low/med):** ARCHITECTURE §3 says the raw dump has "no PKs" (plural), yet the plan
  keeps `workouts.id` as an `INTEGER PRIMARY KEY AUTOINCREMENT`. The plan justifies it (local FK target for
  `workout_statistics`, mirrors the existing `../db/health.db`) but does not explicitly reconcile with the
  literal "no PKs" wording — a reviewer could read it as a contradiction. Make the reconciliation explicit.

**Axis 2 — internal coherence + final-validation coverage:**
- Task deps are linear and sane: T1(None)→T2(T1)→T3(T2)→T4(all). ✓
- All 10 substantive PLAN acceptance criteria map 1:1 into TASK-004 with named pytest `-k` selectors / grep
  commands, plus the lint+pytest criterion; TASK-004 adds non-circular extras (tests never read the real
  corpus). No "all criteria met" hand-wave. ✓
- Acceptance criteria are observable/testable (PRAGMA introspection, count asserts, byte-equal timestamp,
  source-text scan for `iterparse`/`clear`/no-`ET.parse`). ✓
- **Finding 2 (apply, low):** `workouts.id` is `AUTOINCREMENT`; the idempotency AC asserts "second run's
  four-table contents equal the first's" (incl. ids). This holds **because** `DROP TABLE` clears the
  table's `sqlite_sequence` row so the recreated table restarts ids at 1 — but the plan never states this
  assumption, so the idempotency-of-ids guarantee looks unproven. Make it explicit (decision + test note).
- **Finding 3 (reject):** "Add the `workout_events` table the prior `../db/build_db.py` writes." Rejected —
  DB.md §1's mirrored set is exactly the four tables; the phase task list names only those. The plan
  already documents this exclusion (Out of Scope + RESEARCH Uncertainty). Adding it would exceed scope.
- **Finding 4 (reject):** "Assert the output `baseline.db` is byte-for-byte identical across runs."
  Rejected — `ANALYZE` writes nondeterministic `sqlite_stat*` tables and SQLite free-page layout isn't
  byte-stable; the plan correctly scopes idempotency to per-table **counts + contents**, not file bytes.
  This is the right contract (epic R1/§4 say "identical baseline.db" in the count/no-duplication sense).

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | ARCHITECTURE §3 "no PKs" vs the kept `workouts.id` AUTOINCREMENT PK is not explicitly reconciled | med | apply | Real coherence/fidelity gap — a reviewer reads it as a contradiction; one decision sentence fixes it | PLAN.md:Decisions, PLAN.md:Acceptance(Raw column shape) |
| 2 | Idempotency-of-`workouts.id` depends on `DROP TABLE` resetting `sqlite_sequence`; assumption unstated | low | apply | The idempotency AC compares contents incl. ids; the stability guarantee should be made explicit + tested | PLAN.md:Decisions, PLAN.md:Risks, TASK-002 |
| 3 | Add a `workout_events` table (prior script wrote one) | low | reject | DB.md §1's mirrored set is the four tables only; already documented as out of scope | — |
| 4 | Assert byte-for-byte identical `baseline.db` across runs | low | reject | `ANALYZE`/`sqlite_stat*`/free-page layout aren't byte-stable; idempotency is correctly scoped to counts+contents | — |
