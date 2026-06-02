# Validation Summary — e1-p1-project-scaffold

**Rounds:** 3
**Plan status at validation:** draft
**Run on:** 2026-06-02

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 5        | 5       | 0        | 0        |
| 2     | 2        | 2       | 0        | 0        |
| 3     | 0        | 0       | 0        | 0        |

Round 3 returned **approve** with no material findings.

## Applied

### Round 1
- TASK-001, TASK-002 — add `httpx` as a dev dependency so FastAPI `TestClient` works (round-1 #1)
- PLAN.md:Acceptance, TASK-002/003/005 — settings validated at app **startup** (`create_app()`), with a
  negative boot smoke (round-1 #2)
- PLAN.md:Scope, TASK-001, TASK-005 — bound `requires-python` to `>=3.13,<3.14` (not a bare floor) + record
  `python --version` in final validation (round-1 #3)
- TASK-004, TASK-005 — make camelCase JSON explicit (`serialize_by_alias=True`) and assert real wire JSON
  via a FastAPI route (round-1 #4)
- TASK-005 — enumerate concrete, non-circular final-validation checks for every acceptance criterion
  (round-1 #5)

### Round 2
- TASK-002 — remove the lifespan-only path; require construction-time `get_settings()` in `create_app()`
  and assert `create_app()` itself raises (round-2 #1)
- TASK-004, TASK-005 — test an optional `T | None = None` field accepting both omission and explicit
  `null`; document the convention (round-2 #2)

## Deferred

- (none)

## Rejected

- (none)
