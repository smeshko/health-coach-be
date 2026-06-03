# Adversarial Validation — Round 1

**Run:** 2026-06-03 00:50 UTC
**Plan:** e5-p1-sync-models
**Status at start:** draft

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

```
[codex] Starting Codex task thread.
[codex] Thread ready (019e8af6-188c-7b01-aab0-0fc0f969479a).
[codex] Turn started (019e8af6-1b42-7bb2-9fcf-d2460baeea43).
[codex] Codex error: You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at 5:18 AM.
[codex] Turn failed.
# Codex Adversarial Review

Codex did not return valid structured JSON.

- Parse error: You've hit your usage limit. Upgrade to Pro ... or try again at 5:18 AM.
```

**Codex unavailable (usage/quota limit, resets ~05:18). Per the runbook, no retry — a rigorous
MANUAL adversarial review follows.** The plan dir was found with a fully-authored `PLAN.md` but
**four unfilled scaffolding stubs** under `tasks/` (Flutter-flavoured placeholders); the manual
review's primary finding addresses that.

## Manual adversarial review

Reviewed `PLAN.md` + `tasks/TASK-001..004` against `epics/E05-sync-ingest.md`,
`docs/architecture/MODELS.md` ("POST /sync" + "Enums"), and `docs/architecture/DB.md` §1, on two axes:
(1) fidelity to the cited docs, (2) internal coherence + final-validation AC coverage.

### Fidelity checks (all PASS — no defects)
- `RecordType` (24 values) — matches MODELS "Enums → RecordType" verbatim, incl. the seven `dietary_*`
  and `body_mass`.
- `HealthRecord` / `Workout` / `WorkoutStat` / `ActivitySummary` / `DailyCheckin` / `StrengthTest` /
  `SyncRequest` / `SyncResponse` — every field matches the MODELS "POST /sync" tables field-for-field
  (incl. camelCase wire names `durationS`/`distanceM`/`activeEnergyKcal`/`recordsUpserted`/`serverTime`).
- DB.md §1 — `records.type` is the only whitelist gate (workouts/activity not type-gated); `body_mass`
  is the single live-weight source, **no** check-in weight field. The plan honours all three.
- `DailyCheckin.kneePain` bounded 0–10 (MODELS "integer 0–10"); objective-only (epic R7). Honoured.

### Findings

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | The four `tasks/*.md` files are unfilled scaffolding stubs (Flutter `dart analyze`/`flutter test`, `path/to/file.dart`, "One sentence", all `Depends on: None`) — they do not implement the fully-authored PLAN.md and TASK-004 maps to no PLAN.md acceptance criterion. | high | apply | A plan whose task files are empty Flutter placeholders is not implementable and violates runbook Step 2/Final-validation requirements; the PLAN design is sound but unexecuted at the task level. | TASK-001, TASK-002, TASK-003, TASK-004 |
| 2 | PLAN parenthetical names both `respiratory_rate` **and** `running_cadence` as candidate recognised-but-unstored types, but DB.md §1 lists "running cadence & dynamics" as **stored** — only `respiratory_rate` is genuinely unstored. | low | reject | The plan already self-corrects in the same Decision ("`running_cadence` resolves to E4's `CADENCE_TYPE`") and defers the actual stored/unstored relationship to a TASK-003 test, so no false claim survives; pinning a single example would over-specify a greenfield E4 detail. | — |
| 3 | PLAN attributes `serialize_by_alias=True` to "E1·P1 TASK-004", but E1 epic R5 names only `alias_generator=to_camel` + `populate_by_name=True`. | low | reject | This is the runbook's own prescribed convention (known-finding #3: "camelCase must be explicit `serialize_by_alias=True`") and a cross-phase dependency assumption, not a contradiction of MODELS; round-trip tests in TASK-001/002 assert the camelCase wire output regardless. | — |
| 4 | Task dependency graph + AC↔final-validation coverage. | n/a | (verified) | After applying #1: TASK-002/003 `Depends on: TASK-001`, TASK-004 `Depends on: all prior`; TASK-004 enumerates a concrete non-circular check for all 8 PLAN.md acceptance criteria (AC1–AC8, 1:1). No gap. | — |

### Applied (finding #1)
Authored all four task files to match the already-authored PLAN.md design (no design change):
- **TASK-001** — `RecordType` enum (exact 24-value list) + `HealthRecord` in `app/api/schemas/sync.py`;
  real `app/...` + `tests/...` paths; RED/GREEN/REFACTOR; quantity/category + null-vs-absent +
  unknown-type-rejection acceptance.
- **TASK-002** — the remaining seven models with snake_case Python → camelCase wire fields, `Field(ge=0,
  le=10)` on `kneePain`, objective-only `DailyCheckin`, `SyncRequest` defaults, MODELS-example
  round-trip; `Depends on: TASK-001`.
- **TASK-003** — `RECORD_TYPE_TO_HK` bridge + `is_record_type_whitelisted` / `filter_whitelisted_records`
  deriving membership **from** E4's `WHITELISTED_TYPES` (completeness + agreement tests; no second list);
  `Depends on: TASK-001`.
- **TASK-004** — rewritten for the Python/uv stack (`uv run ruff check .`, `uv run pytest <paths>`) with a
  concrete, non-circular check mapped 1:1 to every PLAN.md acceptance criterion (AC1–AC8) plus scope
  boundaries (no route/ORM/auth; `WHITELISTED_TYPES` not re-declared).
