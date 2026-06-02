# E10 — Weekly Brief (`POST /brief/weekly`)

| | |
|---|---|
| **Status** | 🔵 ready for dev |
| **Phases** | 3 |
| **Depends on** | E9, E8, E6 (and E2, E3, E7 transitively) |
| **Unblocks** | E11 (daily reads the week plan), E12 |
| **Primary refs** | [`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §5 (WEEKLY_PLANNER) · [`MODELS.md`](../docs/architecture/MODELS.md) "POST /brief/weekly" · [`LLM.md`](../docs/architecture/LLM.md) §1 |

---

## 1. Summary & goal

Ship the **`WEEKLY_PLANNER`** workflow and the **`POST /brief/weekly`** endpoint: a get-or-generate
tiered week of card **picks**, expanded and validated into a full plan with **first-class nutrition**. The
first request of an ISO week runs the workflow (and the §10 constants recompute when stale); later
requests serve the cache; `?refresh=true` regenerates
([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §4, §5).

## 2. Requirements

- **R1** — The full node graph ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §5):
  `LoadAggregatesNode` → `RecomputeConstants` (when stale) → `ComputeBudgetsNode` → `GeneratePlanNode`
  (AgentNode) → `DeriveSessionsNode` → `ComputeTargetsNode` → `ComputeNutritionNode` → `ValidatePlanNode`
  (ModelRetry ≤2) → `PersistPlanNode`.
- **R2** — `GeneratePlanNode` emits **`WeeklyPlanLLMOutput`** — slim `PlannedPick`s in `core` (2–3) /
  `extras` (1–2) + `narrative` — within the budgets ([`LLM.md`](../docs/architecture/LLM.md) §1;
  [`MODELS.md`](../docs/architecture/MODELS.md) WeeklyPlanLLMOutput).
- **R3** — Code derives everything else: `DeriveSessions` expands picks → `PlannedSession` via `CARD_META`
  (E7); `ComputeTargets` derives `WeeklyTargets` (sums/ratios incl. `cadenceSpm` from `profile.yaml`);
  `ComputeNutrition` builds `WeeklyNutrition` (constant targets + `dayTypePattern` from picks + `lastWeek`
  adherence) ([`MODELS.md`](../docs/architecture/MODELS.md) WeeklyTargets/WeeklyNutrition; [`LLM.md`](../docs/architecture/LLM.md) §1).
- **R4** — `RecomputeConstants` runs the §10 helpers (E8·P5) **and rewrites `profile.yaml`** when the
  constants are stale; `data.constantsRecomputed` reflects whether it ran
  ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §5, §10; [`DB.md`](../docs/architecture/DB.md) §6).
- **R5** — **Get-or-generate** keyed by `iso_week`; `UNIQUE(iso_week)` enforces one plan/week;
  `?refresh=true` deletes + regenerates; persist `payload`/`rationale`/`inputs_snapshot`/`model`/
  `constitution_version` ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §4; [`DB.md`](../docs/architecture/DB.md) §4).
- **R6** — Response is **`{ data, narrative }`** ([`MODELS.md`](../docs/architecture/MODELS.md) WeeklyPlan).

## 3. What to implement (by phase)

### E10·P1 — GeneratePlanNode (weekly agent)
- Specialise E9's harness with `OutputType = WeeklyPlanLLMOutput`, the weekly user-context payload (7/28d
  rollups, adherence, budgets, recomputed constants), and the **weekly** `output_validator` (E7).
- Narrative section types: `plan` | `session` | `nutrition`.

### E10·P2 — WEEKLY_PLANNER workflow assembly
- Wire the nodes (R1) over `TaskContext`. `RecomputeConstants` calls the E8·P5 helpers and rewrites
  `profile.yaml` when stale (R4).
- `DeriveSessions`/`ComputeTargets`/`ComputeNutrition` from E7/E8; `ValidatePlanNode` with ModelRetry ≤2.

### E10·P3 — Endpoint + get-or-generate
- `POST /brief/weekly` (authed), `WeeklyBriefRequest` (default = current ISO week, Europe/Sofia).
- Lookup-by-`iso_week`; generate on miss; serve cache on hit; `?refresh=true`.
- Assemble + persist `WeeklyPlan`; set `cached`, `weekStart`, `generatedAt`.

## 4. Acceptance criteria

- [ ] First call for an ISO week runs the full graph and returns a `WeeklyPlan` with `core`/`extras` as
      **code-expanded** `PlannedSession`s, `budgets`, `targets`, and `nutrition` populated.
- [ ] Second call returns the **cached** plan (`cached: true`) with no LLM call; `?refresh=true`
      regenerates and replaces it.
- [ ] `UNIQUE(iso_week)` guarantees exactly one plan per week.
- [ ] A plan violating a budget/spacing rule triggers `ModelRetry`; persistent failure ⇒
      `brief_generation_failed`; a constraint-breaking plan never reaches the cache.
- [ ] When constants are stale, `RecomputeConstants` rewrites `profile.yaml` and `constantsRecomputed` is
      `true`; otherwise it is `false`.
- [ ] `inputs_snapshot` records the aggregates + constants the LLM saw (reproducibility).

## 5. Expected outcome

A working weekly planner: deterministic budgets + LLM picks → fully derived, validated, cached weekly plan
with nutrition — the plan the daily brief tunes against.

## 6. Validation

- Workflow tests with a mocked agent: full-graph happy path, cache hit/refresh, ModelRetry on bad picks,
  stale-constants recompute branch.
- Endpoint tests: auth, default period, `?refresh=true`, response shape.

## 7. Out of scope

The daily brief (E11), Langfuse (E12). The pure computations/validators/derivation come from E6/E7/E8 and
the LLM harness from E9.
