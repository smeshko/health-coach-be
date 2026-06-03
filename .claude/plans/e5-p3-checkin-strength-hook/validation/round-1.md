# Adversarial Validation — Round 1

**Run:** 2026-06-03 02:40 UTC
**Plan:** e5-p3-checkin-strength-hook
**Status at start:** draft

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

```
[codex] Starting Codex task thread.
[codex] Thread ready (019e8b0a-9d88-7583-9caf-fc52148d6f69).
[codex] Turn started (019e8b0a-a06c-7cb1-be72-6a3f7fc23f0a).
[codex] Codex error: You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro),
visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at 5:18 AM.
[codex] Turn failed.
# Codex Adversarial Review
Codex did not return valid structured JSON.
- Parse error: You've hit your usage limit. ... try again at 5:18 AM.
```

**Codex unavailable (quota exhausted, resets ~05:18) — manual adversarial review performed instead.**
Per the run instruction, codex was attempted exactly once with the
`CODEX_DISABLE_IMAGE_GENERATION=1 OPENAI_IMAGE_MODEL=""` prefix; it returned a usage/quota error and no
valid review JSON, so it was **not** retried. The findings below are from a rigorous manual review
challenging the plan on two axes: (1) fidelity to the cited architecture docs
(`docs/architecture/DB.md` §3/§6, `MODELS.md` DailyCheckin/StrengthTest/SyncResponse, `ARCHITECTURE.md`
§3/§4) and the epic (`epics/E05-sync-ingest.md` R4/R7, §3 E5·P3, §4), and (2) internal coherence (task
deps, observable/testable acceptance, decision consistency, and final-validation 1:1 coverage). Cross-doc
facts were independently verified: the ISO-week edge assertions baked into TASK-002 were checked against
Python `isocalendar()` (2026-06-07 Sun → 2026-W23, 2026-06-08 Mon → 2026-W24, 2024-12-30 → 2025-W01,
2021-01-01 → 2020-W53 — all confirmed); the wire Python attribute names (`body.checkin`,
`body.strength_test`, `body.activity_summary`) and the dependencies it leans on (`require_auth`,
`SessionLocal`, `now_sofia`/`iso_week`/`period_date`/`to_sofia` in `app/core/time.py`) were confirmed
against the E5·P1/E5·P2/E2·P1/E2·P3 plans.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | TASK-003 describes the record/workout `start` → affected-date extraction as `period_date(<start>)` "then parsed to a `date`" OR `to_sofia(start).date()`. `period_date` returns a `YYYY-MM-DD` **string** (E2·P1), so the first phrasing implies a needless string round-trip; the clean form is `to_sofia(start).date()`, which returns a `datetime.date` consistent with the other `set[date]` members. | low | apply | E2·P1 signatures: `period_date(dt)->str`, `to_sofia(dt)->datetime`. Use `to_sofia(start).date()` so the fan-out builds a `set[date]` without re-parsing a string; keeps types consistent with the `date`-typed activity/checkin/test members. | TASK-003 |
| 2 | `affected_dates(...)` can return an **empty set** (e.g. a sync carrying only non-whitelisted records, or an empty body). The plan says recompute fires post-commit with `affected_dates(body)` but doesn't state the empty-set behaviour, so an implementer might guess (skip vs call-with-empty). | low | apply | Make it explicit and deterministic: recompute is **always** called with `affected_dates(body)`; the default `noop_recompute(set())` is a harmless no-op (and a real E6 engine treats an empty set as "nothing to do"). Add a one-line note + an `affected_dates` empty-input assertion so behaviour is pinned, not guessed. | TASK-003, PLAN.md:Decisions |
| 3 | TASK-002 says to combine the wire `StrengthTest.date` (a bare calendar `date`) to an aware Europe/Sofia datetime before calling `iso_week`, because the E2·P1 helper rejects naive datetimes. For a bare calendar date this is correct but slightly subtle — worth pinning that the **midnight-Sofia** combine yields the same ISO week as the calendar date itself (no off-by-one from the time-of-day or offset). | low | apply | The combine must use `time.min` with `tzinfo=Europe/Sofia` (midnight local) so `iso_week` of the resulting instant equals `date.isocalendar()`; a stray UTC combine near a day boundary could shift the week. Make the midnight-Sofia combine explicit and add an assertion that the derived `iso_week` matches the calendar date's ISO week for a same-day check. | TASK-002 |
| 4 | Should `affected_dates` only fan-out dates whose data was **actually persisted** (e.g. exclude non-whitelisted records that `upsert_records` dropped, or a day with zero stored rows)? The plan fans out by the **request** payload, not by what landed. | med | reject | DB.md §6 says "recompute affected days on every sync"; the affected set is the days the sync **touched**, and E6 recomputes a day's metrics from whatever is now in `app.db` for it (idempotent, cheap, correct even if a given collection was empty). Filtering by persisted-rows would couple the fan-out to each writer's internals and risk **missing** a day that another collection touched. Fanning out by the request's Sofia dates is the simpler, correct contract — and a recompute of a day with unchanged data is a harmless no-op. (Consistent with PLAN Decision "buckets every touched datum… the exact set DB.md §6 says to recompute".) | — |
| 5 | Recompute fires **after** `commit()` and outside the request transaction — does that leave a window where data is committed but `daily_metrics` is stale if recompute fails? | med | reject | Intentional and correct: an ingest must not roll back because a *derived-cache* recompute failed (the raw data is the source of truth; `daily_metrics` is a rebuildable materialized cache — DB.md §2). Post-commit firing is an explicit PLAN Decision with rationale; coupling recompute into the ingest transaction would make `/sync` fail on an E6 bug. The seam + idempotent recompute means a missed day can be re-derived later. No change. | — |
| 6 | Does the final-validation task (TASK-004) cover **every** PLAN.md acceptance criterion 1:1 with a concrete, non-circular check? | — | reject (no defect) | Verified each of the 9 PLAN acceptance criteria maps to a named `uv run pytest … -k …` selector or a `grep` boundary check in TASK-004 (check-in upsert-by-date; strength `iso_week` edges; one-per-week; no body-weight; affected-date set; recompute spy + noop; saved flags incl. absent→false; no-readiness; end-to-end idempotency; plus the explicit ruff/pytest gate). No circular "all met". No change. | — |
| 7 | Are the task dependencies sane and each task ≈ one commit? | — | reject (no defect) | TASK-001 (checkin service) → TASK-002 (strength service, depends on 001 for the shared test fixture/service pattern) → TASK-003 (route wiring + recompute seam, depends on 001+002) → TASK-004 (validation). Each is one focused service/edit + its tests = one commit. Coherent. No change. | — |
