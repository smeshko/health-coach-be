# Coach App — Backend Architecture

> Personal, single-user workout & nutrition coaching backend. It ingests Apple Health data
> from an iOS app, and on request produces a **weekly plan** and a **daily session
> suggestion** that obey [`HEALTH-CONSITTUTION.md`](../../HEALTH-CONSITTUTION.md).
>
> Visual companion: open [`arch.html`](./arch.html) in a browser — paginated, with inline commenting.

---

## 0. Overview

A pull-model HTTP API. The iOS app syncs HealthKit data, then requests briefs. Briefs are
generated inline on request and cached.

```
                         POST /sync                ┌──────────── Backend (1 process) ────────────┐
   ┌───────────┐   HealthKit + daily check-in      │  FastAPI                                     │
   │  iOS app   │ ────────────────────────────────▶ │   /sync   → idempotent upsert → SQLite (WAL) │
   │ (HealthKit)│   POST /brief/daily | /brief/weekly│   /brief  → get-or-generate ─┐               │
   │            │ ◀──────────────────────────────── │                              ▼               │
   └───────────┘   tuned session / weekly plan       │              Workflow engine                 │
                                                      │              Node → Router → AgentNode ──────┼─▶ Claude
                                                      └──────────────────────────────────────────────┘
        build inputs (read-only): baseline.db (ex health.db) · HEALTH-CONSITTUTION.md · medical-docs/
        runtime store (read-write): app.db (WAL)
```

**Endpoints (the entire surface):**

| Endpoint | Purpose |
|---|---|
| `POST /sync` | Upsert HealthKit samples (activity, sleep, HRV/RHR **and dietary-intake** records) + daily check-in (+ optional weekly strength test). Idempotent by HealthKit `uuid`; check-in upsertable by date. |
| `POST /brief/daily` | Get-or-generate today's tuned session (+ alternatives, skip-OK, macro focus + yesterday's intake-vs-target). |
| `POST /brief/weekly` | Get-or-generate this week's plan (core + extras, budgets, **week nutrition**, rationale). Runs the constants recompute when they are stale. |

**Properties:** single user · pull model · single synchronous process · SQLite file · brief
generation 3–8 s (app shows a spinner) · period keys in `Europe/Sofia`.

---

## 1. Components

| Component | Technology | Role |
|---|---|---|
| Runtime | Python 3.13, `uv` | — |
| API | FastAPI, `uvicorn` | The three endpoints; one synchronous process, no background workers or scheduler. |
| Persistence | SQLite (WAL), SQLAlchemy, Alembic | Runtime ingest + coaching state in `app.db` (Alembic-managed). `baseline.db` is a read-only build input, never opened at runtime (§3). |
| Orchestration | Workflow engine | DAG of nodes over a shared Pydantic `TaskContext`; node types `Node` / `RouterNode` / `AgentNode`. |
| LLM | Claude (Anthropic) via PydanticAI | Structured outputs; the constitution is a Jinja2 system prompt rendered from `profile.yaml` constants (caching off — §LLM). |
| Observability | Langfuse | Trace every LLM call (prompt, structured output, retries, cost) — invaluable for tuning the coach against its own briefs each month. |

> **Stack note — what we keep vs drop from the GenAI Launchpad.** This backend is built on Datalumina's
> Launchpad boilerplate but uses only its **FastAPI app, the `core/` workflow primitives
> (`Node`/`RouterNode`/`AgentNode`/`TaskContext`), PydanticAI, Jinja2, and Alembic**. The Launchpad's
> **Postgres/pgvector, Celery, Redis, Supabase, streaming, and `vecs`/RAG** are *not* used — single-user
> scale needs none of it, so the `database/` layer is rewritten for SQLite and those deps are dropped.

**Deployment:** one `uvicorn` process + one `app.db` file; optional Docker (a single `api`
container). **Backup:** `litestream` streams `app.db`'s WAL to object storage continuously, so the one
durable file survives disk loss. **Access:** one long-lived API token over HTTPS, on a private
network / Tailscale.

---

## 2. Computation & judgment

The system separates deterministic computation from LLM judgment; the node model expresses the
boundary. The LLM performs no arithmetic — it receives pre-computed numbers and flags and
chooses within them.

```
        DETERMINISTIC (code)                         JUDGMENT (LLM)
        Node + services/                             AgentNode → Claude
   ┌──────────────────────────┐                 ┌──────────────────────────┐
   │ HR zones (§3)            │                 │ pick sessions from pool  │
   │ readiness score (§6.1)   │   pre-computed  │ sequence the week        │
   │ rolling aggregates       │ ──numbers────▶  │ tune today's session     │
   │ baselines (HRV/RHR 30d)  │   + flags       │ write rationale          │
   │ macros/TDEE (§7)         │                 │ within budgets & flags   │
   │ volume ramp (§9)         │                 └──────────────────────────┘
   └──────────────────────────┘
              │
              ▼
   ┌──────────────────────────┐   The training-readiness SAFETY GATE (§6.2) is a RouterNode that
   │  SafetyGateRouter        │   short-circuits to REST/active-recovery before the LLM is
   │  any flag TRUE → REST    │   consulted. It enforces auto-regulation only (GI symptoms /
   └──────────────────────────┘   illness / knee / sleep / HRV-RHR). The §2 medical conditions
                                   are LLM *context* (system prompt), not a code-enforced layer —
                                   this is a fitness app, not a medical device.
```

---

## 3. Data model (SQLite)

> Full column-level schema in [`DB.md`](./DB.md) (visual: [`db.html`](./db.html)). This section is the summary.

**Two databases, split by lifecycle:**

| File | Role | Lifecycle | Schema owner |
|---|---|---|---|
| `baseline.db` (renamed from `health.db`) | Read-only historical corpus — 3.5M records, 925 workouts, 2019→2026 — used only to derive constants and seed the runtime window. | Regenerated wholesale by `build_db.py` (`DROP TABLE … ` then re-parse `export.xml`). **Never opened at runtime.** | `build_db.py` (raw ETL dump: no PKs, no `uuid`, TEXT timestamps as Apple emits them). |
| `app.db` | Runtime ingest + coaching state — everything the three endpoints read and write. | Created and migrated by Alembic; never dropped. WAL; small (KB→MB); backed up. | Alembic. |

Durable user state must not live in `baseline.db`: a baseline refresh drops every table.
The runtime never reads `baseline.db`; it derives from `app.db` only.

**`app.db` — ingest (synced via `/sync`):**

| Table | Holds |
|---|---|
| `records` | every whitelisted HealthKit sample — HR, sleep, HRV, RHR, steps, energy, METs, running dynamics, **and dietary intake (energy, protein, carbs, fat, fiber, sodium, water)**. `uuid` column (unique) keys idempotent sync. |
| `workouts` | sessions: type, duration, distance, energy. `effort_score` column carries RPE 1–10 from `WorkoutEffortScore`. |
| `workout_statistics` | per-workout avg/max (HR, speed, power, cadence). |
| `activity_summary` | daily move / exercise / stand. |

> These columns (`records.uuid`, `workouts.effort_score`) are **new** in `app.db` — they do not
> exist in today's `baseline.db`, which is why sync targets a purpose-built schema rather than the
> ETL dump.

**`app.db` — derived (materialized cache):**

| Table | Holds |
|---|---|
| `daily_metrics` | one row/day — sleep, HRV, RHR, **30-day HRV mean+SD / RHR mean**, zone-minutes, **nutrition intake (kcal/protein/carbs/fat/fiber/sodium/water)**, readiness, band. Recomputed on sync; the 7/28-day rollups (training **and** nutrition-adherence) are windowed sums over it. |

**`app.db` — coaching state:**

| Table | Holds |
|---|---|
| `checkins` | by date, upsertable — `giSymptoms` (bool), `illness` (bool), knee pain (0–10). Objective-only: no subjective self-report, and no body weight (weight is HealthKit `body_mass`). |
| `strength_tests` | weekly — max push-ups, max pull-ups (§9/§10 KPI, trend-smoothed). |
| `plans` | by ISO week — generated weekly plan + rationale + `inputs_snapshot`; cache key. |
| `suggestions` | by date — generated daily session + alternatives + readiness/gate; cache key. |

**Constants live in `profile.yaml`, not a table** — age/height/maxHR/RHR-baseline/zones etc. are
config (set once, refreshed monthly by §10), so they sit in a human-readable, git-diffable file.
Live weight (latest HealthKit `body_mass` → `daily_metrics.body_weight`) and the rolling baselines (`daily_metrics`) stay in the DB.

**Bootstrap (one-time, at deploy):** a build step (a) freezes the derived constants into
`profile.yaml`, and (b) copies the **trailing ~90 days** of relevant samples from `baseline.db`
into `app.db`'s ingest tables — so the first `/brief/weekly` has valid 7/28-day rollups and
30-day HRV/RHR baselines on day one. After that, `app.db` grows its own history from `/sync`
forward and `baseline.db` is no longer consulted.

**Input provenance:**

| Source | What | Manual? |
|---|---|---|
| HealthKit | HR/zones, METs, sleep, HRV, RHR, steps, workouts + effort score, **body weight (`body_mass`)**, **dietary intake (logged in a 3rd-party app that writes to HealthKit)** | automatic |
| Server-derived | planned-vs-actual training adherence, executed intensity, **nutrition-intake adherence (consumed vs target)** | automatic |
| Daily check-in | `giSymptoms` (bool), `illness` (bool), knee pain (0–10) | a few taps |
| Weekly test | max push-ups / pull-ups | two numbers/wk |

Training adherence is derived from HealthKit workouts against the stored plan; nutrition adherence is
derived from the ingested dietary records against `MacroFocus`; body weight is the latest HealthKit
`body_mass`; only symptom/illness/knee flags arrive on the daily check-in.

---

## 4. Request flows

**App-open sequence** (sync precedes brief — readiness and the safety gate read the just-synced
data):

```
1. user fills the daily check-in (GI symptoms / illness / knee)
2. POST /sync           push HealthKit + check-in [+ weekly test]
3. POST /brief/daily    generated off the data just synced
4. if new ISO week → POST /brief/weekly
```

**Get-or-generate** (keyed by period):

```
POST /brief/daily:   s = lookup(date = today)
                     return s if exists else run DAILY_ADJUSTER → persist → return
POST /brief/weekly:  p = lookup(week = current_iso_week)
                     return p if exists else run WEEKLY_PLANNER → persist → return
```

The first request for a day/week generates (one LLM call); subsequent requests serve the cache.
A unique constraint on `(brief_type, period_key)` enforces one brief per period. `?refresh=true`
forces a regeneration. The daily brief, generated off this-morning HRV, is stable for the day.

**Period key & timezone:** the period key (`date`, `iso_week`) is derived via the **`Europe/Sofia` tz
database** (so it tracks DST — EET `+0200` in winter, EEST `+0300` in summer — and travel correctly).
Timestamps are stored with **the actual UTC offset HealthKit emits per sample** (which varies), *not* a
hard-coded `+0300`. Don't assume a fixed offset anywhere — always resolve "today"/"this week" through
the tz database.

---

## 5. Workflows

Two workflows in the node/router/agent model, invoked synchronously from their endpoints. Each
node passes a shared Pydantic `TaskContext`; a node may `stop_workflow()`.

```
WEEKLY_PLANNER  (POST /brief/weekly, first request of an ISO week)
  LoadAggregatesNode   (Node)       7/28-day rollups + training & nutrition adherence (§5.3)
  RecomputeConstants   (Node)       when profile constants are stale → writes profile.yaml (§10)
  ComputeBudgetsNode   (Node)       hard-day budget, strength=2, long-run cap, cadence cue   (§5.1)
  GeneratePlanNode     (AgentNode)  Claude → core/extras as PURE CARD PICKS (+ dose, day)    (structured OutputType)
  DeriveSessionsNode   (Node)       fill intensity/zone/isHardDay/flags/dayType from CARD_META
  ComputeTargetsNode   (Node)       derive totalRunKm/easyRatio/etc. from the picks (arithmetic)
  ComputeNutritionNode (Node)       week nutrition: protein/fat/hydration + carb day-type pattern (§7)
  ValidatePlanNode     (Node)       check budgets/spacing/card-in-pool → ModelRetry ≤2 (§LLM.md §4)
  PersistPlanNode      (Node)

DAILY_ADJUSTER  (POST /brief/daily, first request of a date)
  ComputeReadinessNode (Node)       readiness score 0–100, clamped                          (§6.1)
  SafetyGateRouter     (RouterNode) any flag TRUE → SafetyRestNode + stop                    (§6.2)
  TuneSessionNode      (AgentNode)  Claude picks card + dose + alternatives + skipOk + dayType (§6)
  DeriveSessionNode    (Node)       fill derived fields from CARD_META; compute MacroFocus from dayType (§7)
  ValidateSessionNode  (Node)       band gating, card-in-plan, dose-in-band, dayType fuel-floor → ModelRetry ≤2 (§LLM.md §4)
  PersistSuggestionNode(Node)
```

Node legend: **Node** = deterministic processing · **RouterNode** = conditional branch /
short-circuit · **AgentNode** = LLM call (Claude, structured output). Per the **derive-don't-emit** rule
([`MODELS.md`](./MODELS.md) / [`LLM.md`](./LLM.md) §3): the AgentNode emits only genuine *picks* (which card,
what dose, which day); every card-determined attribute and every number is filled by a downstream `Node`,
so it cannot be wrong by construction.

> **Two kinds of "rest" — don't conflate them.** `SafetyRestNode` is the *deterministic* safety-gate
> terminal: when `SafetyGateRouter` trips on an objective flag (§6.2), it routes **to** `SafetyRestNode`,
> which code-writes the REST/active-recovery brief (no LLM, no arithmetic) and **then** calls
> `stop_workflow()` — so the `AgentNode` is skipped entirely. `stop_workflow()` lives on that terminal
> precisely because the gated path bypasses the LLM. An LLM-*recommended* rest or easy day is a different
> thing: it's a normal `TuneSessionNode` pick (an easy/recovery `dayType`) that flows through the full
> pipeline (`DeriveSessionNode → ValidateSessionNode → PersistSuggestionNode`) and never touches
> `SafetyRestNode` or `stop_workflow()`.

---

## 6. Data sources & rules

**`../../db/baseline.db`** (renamed from `health.db`) — read-only build input: 3.5M records, 925
workouts, 1,346 activity-summary days, 2019→2026. Used at build time to (a) derive the
constitution's personal constants and (b) seed the trailing ~90 days into `app.db` (§3). Not
opened at runtime; regenerable from `export.xml` via `build_db.py`.

**`HEALTH-CONSITTUTION.md`** — a Jinja2 **template** rendered fresh each call (caching off) with
`profile.yaml` constants. The §2 medical conditions are **context** for the LLM, not a code-enforced
layer (fitness app, not a medical device).

**`../../medical-docs/`** — PDFs backing §2 (biopsy, epikrizas, ambulatory records); source for the
constitution's medical context only.

**Deterministic computations (code):** HR zones (from `profile.yaml` Max/RHR, §3) · readiness score,
clamped (§6.1) · safety-gate booleans (§6.2) · 7/28-day rolling aggregates (training **and** nutrition
intake) · 30-day HRV/RHR baselines · BMR/TDEE/macro grams from the LLM's chosen `dayType` (§7) · ≤10%/wk volume ramp
(§9) · cadence-cue ramp & threshold↔VO₂ alternation (deterministic, fed as constraints) · weekly-target
derivation from the LLM's picks · CARD_META attribute fill (derive-don't-emit) · strength-test trend
smoothing.

**Effort / RPE:** the app reads each workout's `WorkoutEffortScore` (RPE 1–10) from HealthKit and
sends it via `/sync`; the first sync backfills available scores. It is used when present. The
auto-estimated `PhysicalEffort` (METs) is always available as an HR-independent intensity proxy.

---

*The **`.md` files are the source of truth**; the `.html` companions are generated from them for
paginated reading + inline commenting (same visual style). When the `.md` changes, regenerate the
`.html`. Inline comments live in `arch.html` (localStorage) and export to `arch-comments.json` /
`arch-comments.md` in this folder — drop the export here and I'll read and act on it.*
