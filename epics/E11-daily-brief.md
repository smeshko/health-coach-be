# E11 — Daily Brief (`POST /brief/daily`)

| | |
|---|---|
| **Status** | 🔵 ready for dev |
| **Phases** | 3 |
| **Depends on** | E9, E8, E6, E10 (and E2, E3, E7 transitively) |
| **Unblocks** | E12 |
| **Primary refs** | [`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §5 (DAILY_ADJUSTER) · [`MODELS.md`](../docs/architecture/MODELS.md) "POST /brief/daily" · [`LLM.md`](../docs/architecture/LLM.md) §1, §1.1 |

---

## 1. Summary & goal

Ship the **`DAILY_ADJUSTER`** workflow and the **`POST /brief/daily`** endpoint: compute **readiness**,
apply the **safety gate** (which may short-circuit to REST **before** the LLM), then have the model **tune
today's session** (card + dose + alternatives + skip-OK + the guarded `dayType` lever) and write the
coach prose. Get-or-generate by date; a tripped gate yields a **code-written** REST brief with **no** LLM
call ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §4, §5;
[`LLM.md`](../docs/architecture/LLM.md) §1).

## 2. Requirements

- **R1** — The node graph ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §5):
  `ComputeReadinessNode` → `SafetyGateRouter` (any flag ⇒ `RestDayNode` + `stop_workflow()`) →
  `TuneSessionNode` (AgentNode) → `DeriveSessionNode` → `ValidateSessionNode` (ModelRetry ≤2) →
  `PersistSuggestionNode`.
- **R2** — `TuneSessionNode` emits **`DailyBriefLLMOutput`** — `session` + `alternatives` (≤2) + `skipOk` +
  **`dayType`** + `narrative`; absent entirely when the gate fired
  ([`LLM.md`](../docs/architecture/LLM.md) §1; [`MODELS.md`](../docs/architecture/MODELS.md) DailyBriefLLMOutput).
- **R3** — **`dayType` is the one nutrition lever** — LLM-picked, **guarded**: defaults to the card's
  `day_type`, floored at `hard` for a hard/long session; code computes every macro gram from it
  ([`LLM.md`](../docs/architecture/LLM.md) §1.1; [`CARDS.md`](../docs/architecture/CARDS.md) §0;
  [`MODELS.md`](../docs/architecture/MODELS.md) MacroFocus).
- **R4** — `DeriveSessionNode` expands picks → `SessionBlock` via `CARD_META` (E7) and computes
  `MacroFocus` from the chosen `dayType` + live weight (E8); the daily brief also ships **yesterday's
  `IntakeSummary`** (code-derived from `daily_metrics`) ([`MODELS.md`](../docs/architecture/MODELS.md) SessionBlock/MacroFocus/IntakeSummary).
- **R5** — `ValidateSessionNode`: band gating, card-in-plan (∪ allowed low-impact subs), dose-in-band,
  `dayType` fuel-floor; ModelRetry ≤2 ([`LLM.md`](../docs/architecture/LLM.md) §4; [`CARDS.md`](../docs/architecture/CARDS.md) §4).
- **R6** — **Get-or-generate** keyed by `date`; `UNIQUE(date)`; `?refresh=true`; persist `suggestions`
  (+ snapshot `readiness_score`/`band` back to `daily_metrics`). The safety-gate REST path is **not** an
  error ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §4; [`DB.md`](../docs/architecture/DB.md) §4, §6; [`LLM.md`](../docs/architecture/LLM.md) §5).
- **R7** — Response is **`{ data, narrative }`**; readiness/penalties and the gate are code; narrative is
  code-written when gated ([`MODELS.md`](../docs/architecture/MODELS.md) DailyBrief).

## 3. What to implement (by phase)

### E11·P1 — TuneSessionNode (daily agent)
- Specialise E9's harness with `OutputType = DailyBriefLLMOutput`, the daily user-context (readiness+band,
  gate result, the week's plan, flags), and the **daily** `output_validator` (E7) incl. the fuel-floor.
- Narrative types: `summary` | `session` | `nutrition` | `caution`.

### E11·P2 — DAILY_ADJUSTER workflow assembly
- Wire readiness (E8·P1) → `SafetyGateRouter` (E8·P2; on trip → `RestDayNode` code-writes the REST brief
  and stops) → tune → `DeriveSessionNode` (E7 expand + E8 MacroFocus + yesterday IntakeSummary) →
  `ValidateSessionNode` (ModelRetry ≤2) → `PersistSuggestionNode` (+ write readiness/band to
  `daily_metrics`).

### E11·P3 — Endpoint + get-or-generate
- `POST /brief/daily` (authed), `DailyBriefRequest` (default = today, Europe/Sofia).
- Lookup-by-`date`; generate on miss; serve cache on hit; `?refresh=true`.
- Assemble `DailyBrief` incl. `intakeYesterday`, `generatedAt`, `cached`, `constitutionVersion`.

## 4. Acceptance criteria

- [ ] First call for a date runs the graph and returns a `DailyBrief` with code `readiness`/`safetyGate`,
      a code-expanded `SessionBlock`, `alternatives`, `macroFocus` (grams from the picked `dayType`), and
      `intakeYesterday`.
- [ ] A tripped safety gate (e.g. `knee_pain>3`, illness) returns a **code-written** REST/active-recovery
      brief with **no** LLM call and `safetyGate.triggered=true` — and this is a success, not an error.
- [ ] `dayType` defaults to the card's day type and is **floored at `hard`** for a hard/long card; a model
      attempt to under-fuel triggers `ModelRetry`.
- [ ] Second call returns the **cached** brief; `?refresh=true` regenerates; `UNIQUE(date)` holds.
- [ ] `readiness_score`/`band` are written back onto the day's `daily_metrics` row.
- [ ] AMBER reduction is honoured (no full Z5/`vo2` dose) and a card outside the week plan ∪ subs is
      rejected.

## 5. Expected outcome

A working daily adjuster: physiological readiness + deterministic gate + LLM-tuned session + code-computed
macros — the morning brief the app shows, stable for the day.

## 6. Validation

- Workflow tests with a mocked agent: happy path, gate short-circuit (LLM skipped), ModelRetry on band/
  fuel-floor/card-in-plan violations, cache hit/refresh.
- Endpoint tests: auth, default date, `?refresh=true`, response shape incl. `intakeYesterday`.

## 7. Out of scope

The weekly planner (E10), Langfuse/deploy (E12). Computations/validators/derivation/LLM-harness come from
E6/E7/E8/E9.
