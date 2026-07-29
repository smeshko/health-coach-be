# Validation Summary — corroborated-hard-day

**Rounds:** 3
**Plan status at validation:** draft
**Run on:** 2026-07-28
**Reviewer:** codex (`/codex-local:adversarial-review`), plan `Risk: medium`

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 6        | 6       | 1*       | 0        |
| 2     | 5        | 3       | 0        | 2        |
| 3     | 2        | 2       | 0        | 0        |

\* Round-1 #7 is a narrower follow-up split out of finding #3 during triage, not a seventh
Codex finding.

Validation changed the plan's substance, not just its wording: three new decisions
(5–7), a new implementation task (TASK-005), two new validity gates on the corroboration
signals, and six new acceptance criteria. Two round-2 findings were rejected on the plan
owner's explicit call about this single-user setup.

## Applied

### Round 1

- `PLAN.md:Out of Scope`, `PLAN.md:Risks`, `DECISIONS.md:Decision 5` — the "July 27 stays
  as-is" promise was unenforceable; `affected_dates` recomputes any day a payload touches.
  Rewritten as documented-and-accepted rather than a guarantee (round-1 #1).
- `PLAN.md:Scope/Risks/Acceptance`, `DECISIONS.md:Decision 6`, `TASK-001`, `TASK-002`,
  `TASK-003`, `TASK-004` — a bare HR presence gate would let one warm-up sample count as
  "zones present and zero" and silently disable the typed fallback. Added the coverage gate
  (`HARD_HR_COVERAGE_MIN_FRAC = 0.5`) and made TASK-001 return credited coverage alongside
  z4+z5 minutes (round-1 #2).
- `PLAN.md:Scope/Risks/Acceptance`, `DECISIONS.md:Decision 7`, `RESEARCH.md`, `TASK-002`,
  `TASK-003`, `TASK-004` — `effort_score` is structurally unbounded (`sync.py` takes a bare
  `int | None` into an unconstrained `Float`), so 99 or -3 could promote an easy workout or
  suppress the typed fallback. Added `HARD_EFFORT_VALID_RANGE`; invalid → treated as absent
  (round-1 #3).
- `PLAN.md:Acceptance`, `TASK-002`, `TASK-004` — nothing in the plan would have failed if
  the implementation aggregated day-total or cross-workout zone minutes, which is the whole
  reason the helper exists. Added isolation criteria and tests (round-1 #4).
- `TASK-001`, `TASK-004` — the instant-credit spec would have filtered to in-window samples
  before crediting, zeroing the last in-window sample. Now mirrors `zone_minutes:465-477`:
  pick the source in-window, compute gaps over the wider window (round-1 #5).
- `TASK-002` — the 7-RPE / 19.9-min typed boundary case specified both 1 and 0 in the same
  sentence. Pinned unambiguously to 0 for both typed and untyped variants (round-1 #6).

### Round 2

- `PLAN.md:Risks`, `DECISIONS.md:Decision 5` — the round-1 rationale claimed readiness is
  recomputed alongside `hard_day`; it is not (`readiness_score`/`band` are
  `PRESERVED_COLUMNS`, `engine:803-813`). Replaced with the honest position: the preserved
  verdict is a deliberate audit trail of what the user was told (round-2 #1).
- `PLAN.md:Acceptance`, `TASK-002`, `TASK-004` — with the coverage gate in place, an
  implementation that wrongly applied it to *promotion* would still pass every named
  criterion. Added a named sub-gate promotion test (16 z4 min in a 50-min window → 1)
  (round-2 #4).
- `PLAN.md:Scope/Acceptance`, `DECISIONS.md:Decision 7 amendment`, **+TASK-005**,
  `TASK-004` — the classifier-side validity gate was one-way: `_backfill_effort_scores`
  only writes where the stored value `IS NULL`, so a stored `99` blocked its own correction
  forever, stranding the workout as permanently effort-absent (round-2 #5).

### Round 3

- `TASK-005`, `PLAN.md:Acceptance`, `TASK-004` — TASK-005 as written still missed
  same-batch duplicates: `insert_new_by_uuid` keeps the first occurrence of a uuid
  (`_upsert.py:56-61`), so `[uuid/99, uuid/9]` in one payload strands the invalid score.
  The repair now runs over all incoming uuids (round-3 #1).
- `PLAN.md:Risks`, `DECISIONS.md:Decision 5` — the round-2 wording still understated the
  blast radius: `_expand_forward_window` + `recompute_day` (`engine:852-854`) full-recompute
  every existing row through D+29, so one sync can reclassify ~30 days. Decision 5 now
  claims only what is true — nothing in the *automatic* sync path rewrites a historical
  readiness verdict (round-3 #2).

## Deferred

- (round-1 #7) **Ingestion-side bounds on `effort_score`** — add `Field(ge=1, le=10)` to the
  `/sync` schema so 99 and -3 are rejected at the door. Real, but it is an API-contract
  change that could start rejecting iOS payloads which currently succeed — a different blast
  radius from a classifier fix. The classifier-side gate (Decision 7) plus TASK-005's repair
  path already remove the misclassification risk this plan owns. *Not filed in Linear —
  Linear is not wired for this repo (`Linear: none`).*

## Rejected

- (round-2 #2) **Coverage gate should require near-complete, unique-elapsed HR coverage** —
  Codex argued 50 % of *summed* credited minutes doesn't prove a session was easy, since a
  watch recording the first 25 easy minutes of a 50-minute session then dying would pass the
  gate and still demote. Rejected on the plan owner's call: a watch dying mid-workout is not
  a real scenario in this single-user setup, so the gate is not being redesigned around it.
  The related sub-point — that interval and instant credits are summed independently and can
  overlap — is pre-existing `zone_minutes` behaviour that this plan reuses unchanged rather
  than introduces.
- (round-2 #3) **Source selection should prefer the best-covered source over the
  highest-ranked one** — grounded in real code (`source_rank` puts Apple Watch at 0 above
  Garmin at 1, so a sparse Watch sample would mask a complete Garmin recording), but the
  setup is Apple-only, making the case hypothetical here. DECISIONS.md Decision 3
  deliberately reuses `zone_minutes`' single-source rule; diverging from it would buy
  nothing for this device configuration.

## Outside the rounds

`.gitignore:14` ignores `/docs`, so this plan dir and `docs/architecture/DB.md` are
untracked — a plain `git add` will silently skip them. Prior plan dirs under
`docs/artifacts/plans/archive/` are tracked, so they were force-added; `implement-plan`
will need `git add -f` for the plan commit and for TASK-003's docs commit, or TASK-003's
"diff in the task's commit" evidence cannot be produced. Noted in TASK-003; no `.gitignore`
change made — that's the repo owner's call.

## Notes for the reviewer

Round 3 produced two further `apply` rows, which under the shared 3-round protocol is a
stop-and-ask point. Both were narrow corrections to text introduced *during validation*
(a task spec and a decision rationale) rather than defects in the plan's design, so the plan
owner chose apply-and-stop over a fourth round or a return to `create-plan`.
