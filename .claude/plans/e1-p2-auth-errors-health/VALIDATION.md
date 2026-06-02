# Validation Summary — e1-p2-auth-errors-health

**Rounds:** 3 (cap reached)
**Plan status at validation:** draft
**Run on:** 2026-06-02

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 2        | 2       | 0        | 0        |
| 2     | 2        | 2       | 0        | 0        |
| 3     | 2        | 2       | 0        | 0        |

Final Codex verdict (round 3): `needs-attention` — both round-3 findings were applied; the 3-round cap was
reached, so validation stopped after applying them (per runbook Step 3).

## Applied

### Round 1
- PLAN.md (Scope/Decisions/Acceptance/Research/Risks), TASK-001, TASK-004 — resolved the closed-`ErrorCode`
  vs "status-derived generic" contradiction: a closed enum (five MODELS codes + one named `internal_error`
  fallback) with an explicit `STATUS_TO_CODE` table (round-1 #1).
- TASK-003, TASK-004, PLAN.md:Acceptance — replaced the weak `utcoffset() is not None` `serverTime` check
  with an injectable `now_sofia()` (`ZoneInfo`) tested across a winter and a summer instant, plus a
  no-fixed-offset source guard (round-1 #2).

### Round 2
- PLAN.md (Scope/Out of Scope/Decisions/Research/Risks/Acceptance), TASK-001, TASK-004 — fold the
  `internal_error` addition into `docs/architecture/MODELS.md` "Errors" **in this same PR** (file + step +
  acceptance + final grep), removing the deferred contract drift (round-2 #1).
- TASK-003, TASK-004 — DST proof now injects only the **base UTC instant** into `now_sofia` so the
  production `astimezone(ZoneInfo("Europe/Sofia"))` path runs (helper not patched away), asserting
  Jan→`+02:00` / Jul→`+03:00` plus a `ZoneInfo`-present / fixed-offset-absent source check (round-2 #2).

### Round 3
- TASK-001 (Files/Acceptance/Steps), TASK-002 (Notes), TASK-004 — `STATUS_TO_CODE` now carries a non-null
  public `message` per status; the handler uses `exc.detail` only as `detail` (when a string), so a
  no-detail `HTTPException` (auth's bare `401`) never yields `message=None`; final validation asserts
  no-detail `401`/`404`/`400` envelopes have a non-empty `message` (round-3 #1).
- TASK-003 (Files/Acceptance/Steps/Notes), TASK-004 — DST proof strengthened to assert the **full converted
  wall-clock** (`12:00Z` → `14:00+02:00` Jan, `15:00+03:00` Jul) and a source guard requiring
  `astimezone(ZoneInfo(...))` / rejecting `.replace(tzinfo=...)`, so an instant-relabel impl is rejected
  (round-3 #2).

## Deferred

- None.

## Rejected

- None. (Round-1 #1 was labelled "reject" by Codex, but its own rationale described a genuine contract
  contradiction; per the runbook the verdict label is advisory and the defect was real, so it was applied,
  not rejected.)
