# TASK-004: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for corroborated-hard-day`

## Goal

Confirm the plan is fully implemented and production-ready.

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked
- [ ] Project analyzer/linter passes with no issues
- [ ] Full test suite passes (or every failing-to-run criterion is explicitly listed as CI-pending — see implement-plan's "When CI is the test gate")
- [ ] Module/import boundaries respected
- [ ] Manual smoke test performed
- [ ] `PLAN.md` acceptance criteria all met, each with its Evidence produced (test output, screenshot, log) — no criterion ticked on "the code looks right"

### Named evidence (round-1 #4 — a generic sweep would let an aggregation bug pass)

Each line below must be satisfied by a **named passing test**, quoted in the evidence:

- [ ] July 27 regression → `hard_day = 0`
- [ ] Promotion via effort (≥ 7 & ≥ 20 min) and via in-window z4+z5 ≥ 15
- [ ] Promotion fires at sub-gate coverage (16 z4 min in a 50-min window → 1), proving the
      coverage gate is not applied to promotion
- [ ] Typed fallback with both signals absent → 1
- [ ] Sparse HR coverage (3 min of a 50-min window) → fallback holds → 1; the same fixture
      at ≥ 50 % coverage → 0
- [ ] Out-of-range effort (99 and -3) treated as absent
- [ ] A later valid effort score replaces a stored invalid one; a valid stored score is not
      overwritten; a same-batch `[uuid/99, uuid/9]` pair ends at `9` (TASK-005)
- [ ] **Isolation**: z4/z5 earned outside the workout window does not flag it; two
      sub-threshold workouts (8 + 8 in-window z4 min) do not sum to a flag
- [ ] Instant-credit successor context: last in-window instant credits its clipped gap, not 0
- [ ] Boundary inclusivity at 7 / 20 / 15 / 90 and at the 50 % coverage line
- [ ] Long-session (≥ 90 min) rule still flags unconditionally

### Epic update (only if `PLAN.md`'s `Epic:`/`Phase:` are not `none`)

- [ ] Tick this phase's `### Acceptance criteria` in `docs/artifacts/epics/<NN>-*.md`, plus any epic-level criteria this phase satisfies
- [ ] Mark the phase done: `python3 ~/.claude/skills/create-epic/scripts/link_plan.py <NN> --phase <NN.M> --plan <plan-slug> --status done`
- [ ] Update the epic's row in `docs/artifacts/epics/EPICS.md` (`In progress` after the first phase merges; `Done` when this is the last phase — then tick the remaining epic-level criteria and note any newly-unblocked epics)
