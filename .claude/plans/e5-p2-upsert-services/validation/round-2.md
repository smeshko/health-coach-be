# Adversarial Validation — Round 2

**Run:** 2026-06-03 03:10 UTC
**Plan:** e5-p2-upsert-services
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

```
codex unavailable (quota) — manual review. Codex was attempted once in round 1 with
CODEX_DISABLE_IMAGE_GENERATION=1 OPENAI_IMAGE_MODEL="" and returned a usage-limit error
("You've hit your usage limit … try again at 5:18 AM") with no valid review JSON; per the run
instructions it was not retried, so round 2 is a manual re-review verifying the round-1 applies and
hunting for anything the edits introduced.
```

## Re-review of round-1 applies (verification)

- **#1 (avg/max column routing) — verified sufficient.** PLAN.md Scope + a new Decision + AC7,
  TASK-002 (Files/Acceptance/RED) and TASK-004 AC7 now all say `max_*`→`maximum`, `avg_*`→`average`.
  RESEARCH.md updated to match. No remaining `value→average` blanket statement (grep clean). Consistent
  with DB.md §1's distinct `average`/`maximum` columns.
- **#3 (`now_sofia` relocation) — verified sufficient & self-consistent.** TASK-003 Files now list the
  **move** to `app/core/time.py` + the `/health` import update + a "keep `/health` DST tests green"
  acceptance item; PLAN.md Decisions records the move and rationale (avoid route→route import). One new
  obligation it introduces — touching E1·P2's `health.py` — is explicitly covered by the new acceptance
  bullet, so it is not a hidden side-effect.
- **#4 (TASK-001 title vs zone writer) — verified sufficient.** TASK-001 now opens with a blockquote
  stating the records-level "zone signal" = HR records (E6 derives `daily_metrics` zone-min) and that the
  workout `zoneMinutes` writer is TASK-002 — an implementer reading only TASK-001 won't hunt for a
  missing writer.
- **#7 (`require_token`→`require_auth`) — verified fixed.** PLAN.md Scope now says `Depends(require_auth)`
  (the E1·P2 name); grep finds `require_token` only inside the round-1 finding text. Task files already
  used `require_auth`.

## New scan (did the edits introduce anything? any missed defect?)

- **Final-validation ↔ acceptance coverage still 1:1.** The applies edited wording, not the AC set: 11
  PLAN.md acceptance criteria + the lint/test gate; TASK-004 AC1–AC11 (+AC12 gate) still map one-to-one,
  each a concrete named test/command. The relocation's "/health stays green" check is a TASK-003
  acceptance item (not a new PLAN-level AC), so no coverage gap is created.
- **No cross-phase contradiction introduced.** Moving `now_sofia` to `app/core/time.py` is a refactor of
  an E1·P2 symbol's *home*, not a contract change; the wire `serverTime` shape is unchanged and the
  E1·P2 `/health` behaviour is preserved (asserted). E5·P1/E2·P2 symbols are only consumed, never
  redefined (boundary checks in TASK-004 still hold).
- **Idempotency story intact.** `records`/`workouts` `ON CONFLICT(uuid) DO NOTHING` with deterministic
  `upserted`/`duplicate` split; `workout_statistics` (incl. `zone_minutes_*`) written only for net-new
  workouts; `activity_summary` `ON CONFLICT(date) DO UPDATE`. Replay asserts unchanged row counts at both
  the service and endpoint level. No regression from the edits.
- **No new defect found.** The plan is faithful to MODELS "POST /sync"/"SyncResponse", DB.md §1/§2/§6,
  ARCHITECTURE §3 + endpoints table, and epic §3 E5·P2 / §4 / §7.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Round-1 applies (#1, #3, #4, #7) are present, consistent across PLAN/RESEARCH/tasks, and grep-clean. | — | reject | Verification only — no change needed; all four applied correctly. | |
| 2 | `now_sofia` relocation touches an E1·P2 file; could be read as a hidden side-effect. | low | reject | Already made explicit: TASK-003 lists the `health.py` import update + a "/health DST tests stay green" acceptance item. No further change. | |
| 3 | Any remaining acceptance-criterion not covered by final-validation? | — | reject | Re-checked: AC1–AC11 ↔ TASK-004 AC1–AC11 1:1 (AC12 = gate). Complete. | |

**Outcome: approve — no applies in round 2.** Round-1 applies are verified sufficient and no new defects
surfaced; per the cap rule, validation stops here (rounds run: 2).
