# Adversarial Validation — Round 1

**Run:** 2026-06-03 03:00 UTC
**Plan:** e5-p2-upsert-services
**Status at start:** draft

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

```
[codex] Starting Codex task thread.
[codex] Thread ready (019e8aff-f609-7ea3-8994-0564b8e488a6).
[codex] Turn started (019e8aff-f8cc-75d1-8b92-1f553f8b4cfc).
[codex] Codex error: You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at 5:18 AM.
[codex] Turn failed.
# Codex Adversarial Review

Codex did not return valid structured JSON.

- Parse error: You've hit your usage limit. ... try again at 5:18 AM.
```

**codex unavailable (quota) — manual review.** Per the run instructions, codex was attempted once with
`CODEX_DISABLE_IMAGE_GENERATION=1 OPENAI_IMAGE_MODEL=""`; it returned a usage-limit error and no valid
review JSON, so it was **not** retried. The findings below are from a rigorous manual adversarial review
challenging the plan along the same two axes: (1) fidelity to the cited architecture docs
(`MODELS.md` "POST /sync"/"SyncResponse", `DB.md` §1/§2/§6, `ARCHITECTURE.md` §3 + endpoints table,
`epics/E05-sync-ingest.md`), and (2) internal coherence (task deps, observable acceptance, decision
consistency, final-validation ↔ acceptance-criteria coverage).

## Manual review notes (the challenge)

- **Wire→column mapping** cross-checked against DB.md §1 for all four tables: `records` (`category`→
  `value_text`, `value`/`unit`, `origin='sync'`, `ON CONFLICT(uuid) DO NOTHING`) ✓; `workouts`
  (`type`→`activity_type`, `durationS`→`duration`+`duration_unit='s'`, etc.) ✓; `activity_summary`
  upsert-by-`date` PK ✓; `workout_statistics` child rows ✓.
- **`SyncResponse` field set** matches MODELS exactly — seven fields, **no** `workoutsDuplicate`/
  `activityDaysDuplicate` (only `recordsDuplicate` has a split). The plan's `WorkoutUpsertResult.duplicate`
  is computed but **not** surfaced (correct — MODELS exposes only `workoutsUpserted`). Not a defect.
- **`ActivitySummary.steps`** has no `activity_summary` column (DB.md §1) → ignored. Plan documents this
  as a deliberate, non-lossy drop (steps arrive as a `step_count` record). Not a defect.
- **Final-validation coverage**: AC1–AC11 each map to a named test/command in TASK-004 (AC12 = the gate).
  1:1, non-circular. Coherent.
- **Auth / `unauthorized` / `serverTime` DST** all reuse E1·P2/E2·P1 primitives faithfully (no hard-coded
  offset; `require_auth`; `now_sofia`).
- Two real refinements surfaced (F1, F3) plus one coherence tidy (F4); see Triage.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | `workout_statistics` mapping wrote every `WorkoutStat.value` → the `average` column, but `WorkoutStat.type` ∈ {`avg_hr`,`max_hr`,`avg_speed`,`max_speed`,`avg_power`,`avg_cadence`} and DB.md §1 gives distinct `average`/`maximum` columns — a `max_hr` value belongs in `maximum`, not `average`. Mapping all to `average` loses the avg/max column semantics. | med | apply | DB.md §1 `workout_statistics` has `average` **and** `maximum`; route `max_*`→`maximum`, `avg_*`→`average` so the column matches the stat kind. | TASK-002, PLAN.md:Decisions, PLAN.md:Acceptance Criteria, TASK-004 |
| 2 | `ActivitySummary.steps` is dropped (no column). Flagged as a possible missed mapping. | low | reject | DB.md §1 `activity_summary` has no steps column; steps are a `step_count` record → `daily_metrics.steps` (E6). Plan already documents this as intentional and non-lossy. | |
| 3 | `serverTime` reuses `now_sofia`, which E1·P2 placed in `app/api/routes/health.py`; importing a helper **from one route module into another route module** is awkward layering and risks an import cycle once both routers grow. | low | apply | Make `app/core/time.py` the canonical home for `now_sofia` (a domain/time concern, like the other Europe/Sofia helpers) and have both `/health` and `/sync` import it from there. | TASK-003, PLAN.md:Decisions |
| 4 | TASK-001's title says "zone-minute capture" but the actual `workout.zoneMinutes` persistence lives in TASK-002 — an implementer reading only TASK-001 could look for a missing zone writer there. | low | apply | Add an explicit cross-reference in TASK-001 (records-level "zone signal" = HR records that feed E6; the workout `zoneMinutes` writer is TASK-002) so the split is unambiguous. (Already in Notes; promote to a one-line scope pointer.) | TASK-001 |
| 5 | `SyncResponse` has no `workoutsDuplicate`; `WorkoutUpsertResult.duplicate` is computed but unused. | low | reject | Correct per MODELS "SyncResponse" (only `recordsDuplicate` splits). Keeping `duplicate` on the result aids the idempotency assertion; not surfacing it on the wire is faithful. No change. | |
| 6 | Final-validation must cover every PLAN.md acceptance criterion. | — | reject | Verified: TASK-004 AC1–AC11 map 1:1 to the 11 PLAN.md criteria (AC12 = lint+test gate); each is a concrete named test/command. No gap. | |
| 7 | PLAN.md Scope named the auth dependency `Depends(require_token)`, but E1·P2 (the owner) defines it as `require_auth` — a fidelity bug that would send the implementer to a non-existent symbol. (Caught while applying.) | med | apply | E1·P2's `app/api/auth.py` exposes `require_auth`; the task files already used `require_auth`, so PLAN.md was the lone drift. | PLAN.md:Scope |
