# Adversarial Validation — Round 2

**Run:** 2026-06-02 23:15 UTC
**Plan:** e2-p3-derived-state-tables
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: the DB.md/E02 table and constraint fidelity otherwise lines up, and TASK-004 maps every PLAN.md acceptance criterion 1:1, but the round-1 partial-revision hazard is still not fully neutralized.

Findings:
- [high] Partial state_tables revision can still be committed or stamped before it is complete (.claude/plans/e2-p3-derived-state-tables/tasks/TASK-001-daily-metrics-model-and-migration.md:31-36)
  Verdict: apply. Rationale: TASK-001 still creates a real Alembic head revision with only daily_metrics and even has a suggested commit for that partial state; TASK-002/003 then mutate the same revision id in place. The new parity check only runs after a fresh temp-file upgrade, so it does not exercise an app.db already stamped with the early revision id. If that happens, Alembic skips the later table creation and final fresh-DB validation can still pass while a real DB is missing checkins/strength_tests/plans/suggestions. Plan files to change: PLAN.md, TASK-001, TASK-003, TASK-004.
  Recommendation: Either move creation of the single state_tables revision to TASK-003, split the work into linear revisions, or explicitly mark TASK-001/TASK-002 as non-committable/non-publishable and add final validation that simulates an already-stamped partial DB and proves it cannot pass.

Next steps:
- Harden the migration strategy before implementation starts.
- Keep the existing parity criterion, but add a stale-stamped-DB check or remove the partial revision state entirely.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Partial `state_tables` revision still possible: round-1's fix kept the revision created in TASK-001 (with a suggested commit) and grown in TASK-002/003, so an already-stamped early revision id could leave a real DB missing tables; the fresh-DB parity check wouldn't catch it. | high | apply | Codex's first recommendation ("move creation of the single state_tables revision to TASK-003") is the cleanest, fully-removes-the-hazard option. Applied: **TASK-001/002 now add only models** (validated via engine-level `Base.metadata.create_all` on temp DBs — no Alembic revision, retitled goals + "no revision added" acceptance), and the **single complete `state_tables` revision (all five tables) is authored once in TASK-003**, where the up/down round-trip, 9-table exact-set, and parity tests also live. There is therefore never an intermediate revision to stamp — the hazard is structurally eliminated, not just guarded. | `PLAN.md:Decisions` (single-revision-in-TASK-003), `PLAN.md:Risks` (rewritten), `PLAN.md:Scope` (migration bullet), `TASK-001` (models-only, no revision), `TASK-002` (models-only, no revision), `TASK-003` (authors the one complete revision + all Alembic tests), `TASK-004` (parity wording) |

**Note:** Codex confirmed this round that DB.md/E02 table & constraint **fidelity lines up** and that
TASK-004 **maps every PLAN.md acceptance criterion 1:1** — no other findings.
