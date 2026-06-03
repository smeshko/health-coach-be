# Adversarial Validation — Round 1

**Run:** 2026-06-03 02:50 UTC
**Plan:** e4-p3-seed-reconcile
**Status at start:** draft

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

```
[codex] Starting Codex task thread.
[codex] Thread ready (019e8ae9-0270-7f30-96f9-b9f8a0031624).
[codex] Turn started (019e8ae9-052d-7ad3-8e4f-85f9d0426cfb).
[codex] Codex error: You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at 5:18 AM.
[codex] Turn failed.
# Codex Adversarial Review

Codex did not return valid structured JSON.

- Parse error: You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at 5:18 AM.
```

**codex unavailable (quota) — manual review.** Per the run instruction, codex was attempted **once** with the
`CODEX_DISABLE_IMAGE_GENERATION=1 OPENAI_IMAGE_MODEL=""` prefix; it returned a usage/quota error (resets
~05:18) and no valid review JSON. Not retried. The findings below are from a **rigorous manual adversarial
review** challenging the plan on the same two axes: (1) fidelity to the cited architecture docs
(`DB.md` §0/§1/§6/§7, `ARCHITECTURE.md` §3/§6, the epic) and (2) internal coherence (task deps, observable
acceptance, decision consistency, final-validation coverage).

## Manual review findings

**Axis 1 — fidelity to the architecture docs (DB.md §1 column-level schema):**

1. **`activity_summary` has NO `origin` column** (DB.md §1, lines 117–126 — columns are `date` PK, the four
   rings + goals; `origin TEXT NOT NULL` is listed ONLY on `records` (l.84) and `workouts` (l.103)). E2·P2's
   `activity_summary` model confirms it (no `origin`). The plan repeatedly assumes `activity_summary.origin`:
   the seed sets `origin='seed'` on it, seed idempotency does `DELETE FROM activity_summary WHERE
   origin='seed'`, reconciliation deletes its seed rows by `origin`, and an acceptance criterion asserts
   `origin='seed'` on seeded `activity_summary` rows. All wrong vs the schema. **HIGH.**
   - Correct model: `activity_summary` is **one row per Sofia day, upserted by the `date` PK** (DB.md §1
     "upsert by date"). The seed inserts it with the `date_components`→`date` rename and **no `origin`**;
     idempotency + seed/sync overlap are handled by the **date-PK upsert** (a live `/sync` for that day
     overwrites the seed row by `date`), so there is **nothing for reconciliation to delete** in
     `activity_summary`. Reconciliation applies only to `records`/`workouts` (the multi-row, origin-bearing
     tables).

2. **`workout_statistics` delete must remove children before parents (no `ON DELETE CASCADE`).** E2·P2
   declares the FK `workout_statistics.workout_id → workouts(id)` with **no `ON DELETE CASCADE`**, and
   E2·P1's connect listener sets `PRAGMA foreign_keys=ON`. So deleting a seed `workout` that still has
   `workout_statistics` children raises `IntegrityError`. The plan's seed-idempotency delete and the
   reconciliation workout delete say "via parent / cascade" loosely. **MED** — must be explicit: delete the
   child stats first, then the parent workouts, in both the seed re-run and the reconciliation.

**Axis 2 — internal coherence:**

3. **Reconciliation rule is sound and decidable, but the `activity_summary` part is moot** given #1. The
   "fully covered iff ≥1 `'sync'` row that Sofia day" rule satisfies epic §4/§6 ("keeps sync rows and
   partial-day seed rows") for `records`/`workouts`; once #1 is fixed, drop `activity_summary` from the
   reconciliation (its date-PK upsert already collapses seed/sync). **MED** (folded into #1's fix).

4. **Final-validation coverage** maps 1:1 to the (current) acceptance criteria — but the `origin='seed'`
   criterion and the three-delta criterion both mention `activity_summary.origin`; they inherit #1's fix
   (the `activity_summary` check becomes "`date` rename present, row addressable by `date` PK", not
   `origin='seed'`). **LOW** (consequential edit, not an independent defect).

**Confirmed correct (no change):**
- Whitelist set vs DB.md §1: HR/HRV-SDNN/RHR/sleep/steps/active+basal energy/PhysicalEffort/VO₂/`BodyMass`/
  running dynamics **+** the seven `HKQuantityTypeIdentifierDietary*` — matches §1's two bullet lists and the
  epic R4. Hosting it in `app/core/` (shared with E5) is consistent with DB.md §1 + the NOTES.
- `records`/`workouts` seed rows: `uuid=NULL`, `origin='seed'` — matches DB.md §1 (l.84, l.103) exactly.
- Europe/Sofia window cut via E2·P1 `period_date`, DST test — matches DB.md §0.
- Offline / never-open-`baseline.db`-at-runtime, dropped-stack exclusion — matches ARCHITECTURE §6 / §1.
- Task deps (001→002→003→004) and the depends-on chain are sane.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | `activity_summary` has no `origin` column; seed must insert it without `origin`, idempotency + seed/sync overlap handled by the `date`-PK upsert; reconciliation must NOT touch `activity_summary` | high | apply | Contradicts DB.md §1 / E2·P2 schema; would crash on insert (no such column) | PLAN.md:Scope, PLAN.md:Decisions, PLAN.md:Risks, PLAN.md:Acceptance Criteria, PLAN.md:Research Summary, TASK-002, TASK-003, TASK-004, RESEARCH.md |
| 2 | No `ON DELETE CASCADE` on the stats FK + `foreign_keys=ON` → must delete child `workout_statistics` before parent `workouts` in both the seed re-run and reconciliation | med | apply | Otherwise `IntegrityError` on parent delete | TASK-002, TASK-003, PLAN.md:Decisions |
| 3 | Reconciliation `activity_summary` branch is moot (date-PK upsert already collapses seed/sync) | med | apply | Folded into #1 — remove `activity_summary` from reconcile scope | TASK-003, PLAN.md (via #1) |
| 4 | Final-validation `origin`/three-delta checks reference `activity_summary.origin` | low | apply | Consequential to #1 — reword the `activity_summary` checks | TASK-004 (via #1) |
| 5 | Whitelist set, `uuid`/`origin` on records/workouts, Sofia window, offline boundary, task deps | — | reject | Verified correct vs DB.md §0/§1/§6/§7 + ARCHITECTURE §3/§6 — no change | — |
