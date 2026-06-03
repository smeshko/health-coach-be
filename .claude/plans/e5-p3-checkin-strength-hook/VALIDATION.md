# Validation Summary — e5-p3-checkin-strength-hook

**Rounds:** 2
**Plan status at validation:** draft
**Run on:** 2026-06-03

> **codex unavailable (quota) — manual review.** Codex was attempted exactly once in round 1 with the
> `CODEX_DISABLE_IMAGE_GENERATION=1 OPENAI_IMAGE_MODEL=""` prefix and returned a usage-limit/quota error
> (resets ~05:18 AM) with no valid review JSON; per the run instruction it was **not** retried. Both
> rounds are rigorous **manual** adversarial reviews challenging (1) fidelity to the cited architecture
> docs (DB.md §3/§6, MODELS.md DailyCheckin/StrengthTest/SyncResponse, ARCHITECTURE.md §3/§4) and the epic
> (E05 R4/R7, §3 E5·P3, §4), and (2) internal coherence. Cross-doc facts (ISO-week edges via
> `isocalendar()`, wire attribute names, dependency symbol names) were independently verified.

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 7        | 3       | 0        | 4        |
| 2     | 4        | 0       | 0        | 4        |

## Applied

### Round 1
- `TASK-003` — affected-date fan-out extracts each record/workout `start` via `to_sofia(start).date()`
  (a `datetime.date`), not `period_date(...)` (a string), keeping the `set[date]` type-consistent; the
  REFACTOR step's tz-authority note was tightened to `to_sofia` only (round-1 #1).
- `TASK-003` + `PLAN.md:Decisions` — recompute is fired **unconditionally** post-commit with
  `affected_dates(body)`, including the **empty-set** case (`noop_recompute(set())` is a no-op; a real E6
  engine treats `set()` as "nothing to do"); added an empty-body `affected_dates`→`set()` assertion so the
  behaviour is pinned, not guessed (round-1 #2).
- `TASK-002` — `iso_week` derivation combines the bare wire `date` to **local midnight in Europe/Sofia**
  (`datetime.combine(test.date, time.min, tzinfo=ZoneInfo("Europe/Sofia"))`, not a UTC combine) before the
  E2·P1 aware-only `iso_week(dt)` helper; added a "midnight-Sofia combine is week-stable" assertion
  (derived `iso_week` == `test.date.isocalendar()`) guarding a day-boundary off-by-one (round-1 #3).

### Round 2
- (none — verification-only; the three round-1 applies were confirmed sufficient and self-consistent, and
  no new issue was surfaced.)

## Deferred

- (none)

## Rejected

- (round-1 #4) Fan-out only the days whose data **persisted** (exclude dropped non-whitelisted records) —
  rejected: DB.md §6 says recompute the days the sync **touched**; E6 re-derives each day from current
  `app.db` state (idempotent), and filtering by persisted-rows risks **missing** a day another collection
  touched and couples the fan-out to each writer's internals. Consistent with the PLAN Decision.
- (round-1 #5) Recompute outside the ingest transaction leaves a stale-cache window on failure — rejected:
  intentional. `daily_metrics` is a rebuildable materialized cache (DB.md §2); an ingest must not roll back
  on an E6 recompute error. Post-commit firing is an explicit PLAN Decision with rationale.
- (round-1 #6) Final-validation may not cover every acceptance criterion — rejected (no defect): each of
  the 9 PLAN acceptance criteria maps to a named `uv run pytest … -k …` selector or a `grep` boundary
  check in TASK-004; no circular "all met".
- (round-1 #7) Task dependencies / one-commit sizing — rejected (no defect): TASK-001 → TASK-002 →
  TASK-003 → TASK-004 is coherent, each task is one focused service/edit + tests = one commit.
- (round-2 #1–#4) Verification-only re-checks of the three applies + a whole-plan re-scan — all confirmed
  consistent; no new applies. Outcome: approve.
