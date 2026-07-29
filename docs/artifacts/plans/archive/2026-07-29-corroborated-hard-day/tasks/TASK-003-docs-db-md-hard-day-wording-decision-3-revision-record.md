# TASK-003: Docs: DB.md hard_day wording + Decision 3 revision record

Depends on: TASK-002
Suggested commit: `docs(metrics): align hard_day docs with corroborated rule`

## Goal

Every document describing `hard_day` states the corroborated rule, and the archived
Decision 3 points forward to its revision, so the next reader doesn't trust the old
label-only predicate.

## Files

- `docs/architecture/DB.md` — §2 `hard_day` row (line ~154): replace
  "(boxing/threshold/VO₂/long/HIIT)" wording with the corroborated rule (effort ≥ 7 &
  ≥ 20 min, or in-window z4+z5 ≥ 15 min; typed-label fallback when both signals are
  absent, where "absent" includes an out-of-range effort score and HR coverage below
  `HARD_HR_COVERAGE_MIN_FRAC` of the workout; ≥ 90 min long-session rule).
- `docs/artifacts/plans/archive/2026-06-04-e6-p1-per-day-recompute/DECISIONS.md` —
  append a one-line "Revised by" note under Decision 3 linking to
  `docs/artifacts/plans/corroborated-hard-day/DECISIONS.md` (do not rewrite history).
- Grep-check other mentions: `grep -rn "hard_day" docs/architecture/ *.md` — update any
  other stale rule descriptions found (e.g. ARCHITECTURE.md, HEALTH-CONSITTUTION.md).

## Acceptance

- [ ] `grep -rn "hard" docs/architecture/DB.md` shows the new rule; no doc still claims
      hard_day is decided by activity type alone.
- [ ] Archived Decision 3 carries the forward link.

Evidence: diff of the touched docs in the task's commit.

**Tracking caveat:** `.gitignore:14` ignores `/docs`, and `docs/architecture/DB.md` is
**not** currently tracked (`git ls-files` returns nothing for it), so a plain `git add`
will silently skip it and the commit-diff evidence above cannot be produced as written.
Prior plan dirs in `docs/artifacts/plans/archive/` were force-added, so the repo convention
is `git add -f <path>`. Use that here — or produce the evidence as a `git diff --no-index`
/ before-after excerpt if these docs are meant to stay local-only.

## Steps

- [ ] Update DB.md §2 row.
- [ ] Append the revision note to the archived DECISIONS.md.
- [ ] Run the grep sweep; fix or explicitly clear each remaining mention.
