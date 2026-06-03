# Adversarial Validation — Round 2

**Run:** 2026-06-03 02:48 UTC
**Plan:** e5-p3-checkin-strength-hook
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

```
Codex remained unavailable this round — quota exhausted (resets ~05:18 AM); per the run instruction codex
was attempted once in round 1 and NOT retried. Round 2 is a manual verification pass: confirm the three
round-1 applies are sufficient and self-consistent, and that they introduced nothing new.
```

**Manual verification of the round-1 applies (#1, #2, #3):**

- **#1 (affected-date extraction → `to_sofia(start).date()`):** TASK-003 now extracts each record/workout
  `start` via `to_sofia(start).date()` (returns a `datetime.date`, consistent with the `date`-typed
  activity/checkin/test members of the `set[date]`), and explicitly says **not** to use `period_date(...)`
  (which returns a string). The stray "`period_date`/`to_sofia` … only tz authority" phrasing in the
  REFACTOR step was also tightened to `to_sofia` only. Sufficient and consistent.
- **#2 (empty affected set):** TASK-003 Files, an added acceptance bullet, and the PLAN "Recompute fires
  AFTER `commit()`" decision now state the call is **unconditional** with `affected_dates(body)`, and that
  an empty set → `noop_recompute(set())` no-op (and a real E6 engine treats `set()` as "nothing to do").
  An `affected_dates`-on-empty-body assertion was added to `tests/services/test_recompute.py` +
  `tests/api/routes/test_sync.py`. Behaviour is now pinned, not guessed. Sufficient.
- **#3 (midnight-Sofia combine for `iso_week`):** TASK-002 now specifies
  `datetime.combine(test.date, time.min, tzinfo=ZoneInfo("Europe/Sofia"))` (local midnight, not UTC) and
  adds a "midnight-Sofia combine is week-stable" assertion that the derived `iso_week` equals
  `test.date.isocalendar()[:2]`-formatted for every tested date — guarding the day-boundary off-by-one.
  Sufficient and consistent with the E2·P1 aware-only helper contract.

**New issues surfaced this round:** none. The edits are localized, internally consistent, and the
final-validation task (TASK-004) still maps 1:1 to the now-9 PLAN acceptance criteria (the added
empty-set acceptance is covered by the existing "recompute spy … or noop" selector and the
`test_recompute.py` gate). No further applies.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Round-1 #1 applied — verify `affected_dates` no longer references `period_date` anywhere and uses `to_sofia(...).date()` for the `set[date]`. | — | reject (verified, no defect) | Confirmed: Files + REFACTOR now use `to_sofia` only; `period_date` is explicitly excluded with a rationale. | — |
| 2 | Round-1 #2 applied — verify the empty-set behaviour is stated as unconditional and asserted. | — | reject (verified, no defect) | Confirmed in TASK-003 Files/Acceptance + PLAN Decisions + the new test assertion. | — |
| 3 | Round-1 #3 applied — verify the midnight-Sofia combine and the week-stability assertion are present and correct. | — | reject (verified, no defect) | Confirmed in TASK-002 Files + Acceptance; matches the E2·P1 aware-only `iso_week(dt)` contract and the independently-verified `isocalendar()` edge cases. | — |
| 4 | Whole-plan re-scan for any other doc-fidelity or coherence defect after the edits. | — | reject (no defect) | Check-in objective-only/no-weight (DB.md §3/epic R7), strength `UNIQUE(iso_week)` upsert (DB.md §3), recompute-as-seam with E6 as implementer (DB.md §6/epic §7), saved flags completing E5·P2 stubs (MODELS SyncResponse), no readiness (epic §3) — all faithful. Task deps and one-commit sizing sane. Final-validation 1:1. | — |

**Outcome:** approve — round 2 produced no applies (verification-only). Validation stops at 2 rounds.
