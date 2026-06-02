# Coach App — LLM Design

> How the "brain" works: the two Claude calls behind the briefs in [`ARCHITECTURE.md`](./ARCHITECTURE.md),
> their structured contracts from [`MODELS.md`](./MODELS.md), and the guardrails around them.
>
> The model is a **selector and sequencer**, never a calculator — code computes every number and
> boolean, the LLM only picks and tunes within them, and writes the coach prose.
>
> Visual companion: open [`llm.html`](./llm.html) — paginated, with inline commenting.

---

## 0. The brain

Two Claude calls — one per brief. Each is a single `AgentNode` wrapping a PydanticAI `Agent` that
returns a strict `OutputType`. The model picks cards, sequences the week, tunes today, and writes
the narrative; it performs no arithmetic.

**The call envelope:**

```
        INTO THE CALL                              CLAUDE                     OUT
   ┌────────────────────────────┐                                    ┌──────────────────┐
   │ SYSTEM  constitution        │                                    │ *LLMOutput       │
   │         (Jinja2-rendered)   │ ── system + user ──▶  Opus  ──────▶ │ enums + numbers  │
   │ USER    computed context    │       PydanticAI · structured       │ + narrative[]    │
   │         readiness/budgets…  │       OutputType (tool call)        │                  │
   └────────────────────────────┘                                    └──────────────────┘
   code computes the numbers & booleans → model chooses within them → code merges the pick
   back into the { data, narrative } response
```

**At a glance:**

| Property | Value |
|---|---|
| Calls / day | ~1–2 (daily + Monday weekly) |
| Model | Claude **Opus** (start here; watch cost) |
| Output | strict Pydantic `OutputType` (tool-based structured) |
| Arithmetic | none — fed pre-computed numbers + flags |
| Agents | 2 — weekly planner · daily adjuster |

**Two outputs in one.** Each call returns both halves of the brief together, so the structured pick
and the prose can't drift apart:

| `data` — structured pick | `narrative` — coach prose |
|---|---|
| enums, numbers, booleans | ordered `NarrativeSection[]` |
| drives the UI | rendered for the user to read |
| **never** contains prose | all human-facing text lives here |

---

## 1. The two agents

Each workflow has exactly one `AgentNode`. The two differ only in their context payload and their
`OutputType`.

| | `GeneratePlanNode` | `TuneSessionNode` |
|---|---|---|
| Workflow | `WEEKLY_PLANNER` | `DAILY_ADJUSTER` |
| Trigger | first `/brief/weekly` of an ISO week | first `/brief/daily` of a date |
| OutputType | `WeeklyPlanLLMOutput` | `DailyBriefLLMOutput` |
| Fed by code | 7/28-day rollups · adherence · budgets · recomputed constants | readiness + band · safety-gate result · the week's plan · flags |
| LLM decides | which cards for core (2–3) + extras (1–2) · sequencing · dose | today's card · alternatives · skip-OK · dose · `dayType` (nutrition lever) |
| May be skipped? | no | **yes** — the safety gate short-circuits before it |

Per **derive-don't-emit** (§3), each agent emits only the slim `*Pick` subset; code fills every
card-derived field and every number.

**`GeneratePlanNode` → `WeeklyPlanLLMOutput`:**

```
WeeklyPlanLLMOutput {
  core:      PlannedPick[]       // 2–3 — { card, suggestedDay, dose } only
  extras:    PlannedPick[]       // 1–2 optional
  narrative: NarrativeSection[]  // type: plan | session | nutrition
}
```

Code then expands each pick → `PlannedSession` (via `CARD_META`), derives `WeeklyTargets` and the
`WeeklyNutrition` day-type pattern from the picks, and merges the code-computed `WeeklyBudgets`
(hard-day ceiling, strength = 2, long-run cap) into the `WeeklyPlan` response.

**`TuneSessionNode` → `DailyBriefLLMOutput`:**

```
DailyBriefLLMOutput {
  session:      SessionPick        // { card, dose } — derived fields filled by code
  alternatives: SessionPick[]      // max 2
  skipOk:       bool
  dayType:      DayType            // the one nutrition lever — guarded (see §1.1)
  narrative:    NarrativeSection[] // summary | session | nutrition | caution
}
```

Absent entirely when the safety gate fired — then the session is the code override and the narrative
is code-written. (`dayType` is the LLM's one nutrition lever — guarded; see §1.1.)

### 1.1 Where the day's nutrition targets come from

The daily brief ships full macro targets as `MacroFocus`, merged in by code. The model picks **one**
nutrition input — `dayType` — and code computes every **gram** from it; the grams themselves are
arithmetic (§2 of the constitution), so the model never emits a number.

```
MacroFocus  — in DailyBrief.data {
  dayType:            DayType  // LLM · the ONE nutrition lever (guarded; defaults to card)
  caloriesKcal:       int      // code · TDEE × day type
  proteinG:           int      // code · ~constant 1.8 g/kg
  carbsG:             int      // code · set by dayType
  fatGLow / fatGHigh: int      // code · 0.8–1.0 g/kg range
  hydrationLLow/High: num      // code · 3.0–3.5 L + sweat
}
```

| LLM — nutrition decisions | Code — nutrition numbers |
|---|---|
| `dayType` — the carb-cycling day type (its **one** lever, guarded) | calories · protein · carbs · fat · hydration |
| the `nutrition` narrative section (fuelling timing, medical-aware food choices) | computed from the chosen `dayType` + live weight (§7) |

> **Decided:** `dayType` is the LLM's **one nutrition lever** — it *picks* the carb day type (genuine
> judgment: decouple fuel from training — deficit push on an easy day, fuel-ahead before a key session).
> It **defaults** to the card's `day_type` and is **guarded**: a hard/long session floors it at `hard`
> (no under-fuelling). Code computes every gram from it. Nutrition is a first-class half of **both**
> briefs — daily ships `MacroFocus` + yesterday's `IntakeSummary`; weekly ships `WeeklyNutrition`
> (targets + carb day-type pattern + last-week intake adherence). Intake is real: dietary HealthKit
> records are ingested (§ DB.md).

---

## 2. Anatomy of a call

The same shape for both agents — only the context payload and the `OutputType` differ.

**What goes in:**

```
SYSTEM  constitution.md.j2  — rendered with profile.yaml constants  [not cached]
        §1 profile · §2 medical (CONTEXT) · §3 zones · §4 pool
        §5 weekly loop · §6 daily loop · §7 nutrition · §8 safety

USER    computed context for THIS period  — JSON
        { readiness, band, safetyGate, budgets | weekPlan,
          aggregates(7/28d, training + nutrition intake), flags(knee, gi), constants }

TOOL    structured OutputType  — forces a typed return
        WeeklyPlanLLMOutput | DailyBriefLLMOutput
```

> **Caching: off.** At ~2 calls/day the 5-min (or 1-hr) prompt-cache TTL almost never hits, so the
> constitution is rendered fresh each call — no cache breakpoints to maintain.

**The constitution as system prompt:**

- Jinja2 renders `HEALTH-CONSITTUTION.md` from `profile.yaml` (the single source) — **maxHR, RHR/HRV
  baselines, zones, cadence cue, and the nutrition constants** (activity factor, deficit %, protein/fat
  g/kg, carb multipliers, hydration). Live weight is fed in the user context, not baked into the prompt.
- `data.constitutionVersion` stamps which snapshot a brief was built against (e.g. `2026-05-01`).
- The **§2 medical block** is rendered as **context** — the brain weighs the conditions (lactose-safe,
  NSAID-free, gallbladder-aware) when it picks and explains. It is *not* a code-enforced layer (this is a
  fitness app, not a medical device); the only code-enforced safety is the §6.2 training auto-regulation gate.

**Model settings:**

| Knob | Setting | Why |
|---|---|---|
| Model | `claude-opus` | start here; revisit tier once cost is observed. |
| Output | tool-based structured | PydanticAI `output_type` — the model must return a valid object. |
| Temperature | low *(open value)* | judgment task; keep picks stable. |
| Caching | `off` | decided — no benefit at this volume. |
| Retries | ≤ 2 | validation-driven (§4). |
| Fallback | `none` | decided — failure surfaces as an error, no synthetic session. |

---

## 3. The code / LLM boundary

The LLM does no arithmetic — everything numeric is computed and fed in.

```
        COMPUTED & FED IN (code)                       CHOSEN WITHIN (Claude)
   ┌────────────────────────────────────┐       ┌──────────────────────────────┐
   │ HR zones · readiness+penalties      │       │ which cards from the pool      │
   │ safety-gate booleans                │       │ sequence (suggestedDay)        │
   │ 7/28-day aggregates (train+nutri)   │       │ how many hard days ≤ ceiling   │
   │ macro numbers (from chosen dayType) │   →   │ AMBER reduction & downgrade    │
   │ hard-day ceiling · strength=2       │       │ dose within each card's band   │
   │ long-run cap (≤10%) · deload        │       │ dayType — guarded nutrition lever │
   │ isHardDay/zone/hrCap/cadence/flags  │       │ alternatives · skipOk          │
   │   (from CARD_META)                  │       │ all narrative prose            │
   │ targets (sums/ratios from the picks)│       └──────────────────────────────┘
   │ threshold↔VO₂ flip · cadence ramp   │
   │ strength-test smoothing             │
   └────────────────────────────────────┘
```

**SETTLED — everything mechanical is code; the LLM emits only genuine picks** (plus the one nutrition
lever). The formerly-open questions resolved as:

| Question | Decision | Why |
|---|---|---|
| Derive `isHardDay`, `zoneTarget`, `hrCapBpm`, `cadence`, `flags` from the card | **code** | functions of the chosen card → derive from `CARD_META` ([`CARDS.md`](./CARDS.md)); can't be wrong; slims both `*LLMOutput` types and the validator (§4). |
| `dayType` (carb-cycling day type) | **LLM — guarded** | the *one* exception to derive-don't-emit: genuine nutrition judgment (decouple fuel from training). Defaults to the card's `day_type`; a hard/long session floors it at `hard`. Code still computes all grams. |
| `totalRunKm` / `easyRunRatio` in targets | **code** | a sum and a ratio — arithmetic; derived from the picks post-hoc. |
| Threshold ↔ VO₂ weekly alternation | **code** | deterministic flip off last week's plan; fed as a fixed constraint. |
| `cadenceSpm` ramp (+5 / 2–3 wk) | **code** | deterministic progression via `profile.yaml cadence_current_spm`. |

So the `*LLMOutput` types are **pure picks** — `{ card, dose }` (+ `suggestedDay` weekly, `skipOk` +
`dayType` daily) + `narrative`. **The LLM keeps the dose** (narrowing a 25–50 min band to "30" is a real
call) **and the `dayType` lever** (its one nutrition choice).

**AMBER reduction stays LLM judgment.** When readiness is amber, the model picks how much to cut (shorten
20–40%, drop the top zone, downgrade via the [`CARDS.md` §3](./CARDS.md) map) — judgment within the band
rule, not a formula.

---

## 4. Output validation

The safety gate guards the **input** (it short-circuits the day to REST). Nothing yet guards the
model's **output** — so a deterministic check sits between each `AgentNode` and its `Persist` node.

```
AgentNode (Claude → *LLMOutput, pure picks)
      │
      ▼
DeriveNode           — fill card-derived fields + numbers from CARD_META / profile.yaml
      │
      ▼
validate(out, ctx)   — pure constraints.py
      ├─ hard violation     → ModelRetry (≤2) → back to Claude
      └─ retries exhausted   → brief_generation_failed
      │ clean
      ▼
PersistNode → plans / suggestions
```

**Two layers, one source of truth:**

- A pure module — `validate_weekly(out, ctx)` / `validate_daily(out, ctx) → Violation[]`
  (`{rule, message, severity}`), fully unit-testable without the LLM.
- Wired as a PydanticAI `@agent.output_validator` (it receives the `RunContext` deps); a **hard**
  violation does `raise ModelRetry(messages)` so the model sees exactly what it broke.
- One `CARD_META` table ([`CARDS.md`](./CARDS.md)) — card → intensity, zone, is_hard, day_type, hr_cap,
  cadence, impact, dose band, flags — powers **all three**: the derive step, validation, and prompt rendering.
- A final belt-and-suspenders re-check before persist: still failing ⇒ error. A constraint-breaking
  brief never reaches the cache.

**Repair vs retry vs reject:**

| | Mechanical fields | Judgment violations |
|---|---|---|
| Action | derive / overwrite in code | `ModelRetry` with the reason |
| Examples | mislabelled `isHardDay`, missing `hrCap` | budget exceeded · bad spacing · wrong card |
| Cost | no LLM round-trip | another Opus call; exhausted → reject → error |

> **Decided:** with derive-don't-emit (§3) the mechanical-mislabel class is gone — those fields aren't
> emitted, so there is nothing to "repair." The validator only ever `ModelRetry`s on genuine **judgment**
> violations (budget, spacing, band gating, card-in-plan, dose-out-of-band).

**What it checks** (the field-consistency rows are gone now that those fields are derived, not emitted):

| Weekly | Daily |
|---|---|
| hard-day count ≤ `budgets.hardDays` | `card` ∈ week plan ∪ allowed low-impact subs |
| spacing: no adjacent hard `suggestedDay`s; no hard run after boxing | RED ⇒ `day_type = rest` card only |
| strength count == `budgets.strengthSessions` | AMBER ⇒ no full Z5 / `vo2` dose |
| core 2–3 · extras 1–2 · ≤ 1 long run | `knee_pain > 3` ⇒ no `impact` card |
| quality run matches the code-decided threshold↔VO₂ pick | dose within the card's band |
| deload week ⇒ ≤ 1 hard day | `alternatives` ≤ 2 |
| | **`dayType` ≥ the card's fuel floor** (hard/long ⇒ `hard`) |

> The validator polices only the real judgment calls: budgets, spacing, card-in-plan, band gating,
> dose-in-band, and the `dayType` fuel-floor. **No medical / NSAID denylist** — §2 is LLM *context*, not a
> code-enforced layer (fitness app, not a medical device). The model applies the medical context from the
> system prompt.

---

## 5. Model, failure & cost

Deliberately minimal for a single-user v1.

| Knob | Setting | Note |
|---|---|---|
| Model | **Opus** | start; watch cost. |
| Caching | **off** | TTL never hits at ~2 calls/day. |
| Fallback | **none** | LLM down → error, no synthetic session. |
| Retries | ≤ 2 | validation-driven. |

**Failure path:**

```
timeout · invalid structure · persistent validation failure
      ↓
Error { code: "brief_generation_failed" | "upstream_timeout", message, detail }
```

- No deterministic fallback session — by design. A failed morning brief surfaces an error; the app
  retries.
- Get-or-generate means a **successful** brief is frozen for the period; `?refresh=true` forces a
  clean regeneration.
- The safety-gate REST path is *not* a failure — it's a code-written brief that never calls the LLM.

**Cost shape.** Single user · ~1 daily call + an occasional weekly call ≈ **30–40 Opus calls/month**.
The constitution (~8–10k tokens) is re-sent each call with no cache discount (caching skipped). If
monthly cost climbs, the first lever is the model tier — the structured contract and validation are
model-agnostic, so a downshift to Sonnet is a one-line change.

**Observability.** **Langfuse** traces every call — prompt, structured output, retries, latency, cost —
which is what makes the monthly tuning loop (re-deriving constants, watching the briefs) tractable.

---

*The **`.md` is the source of truth**; `llm.html` is generated from it (regenerate on change). Inline
comments live in `llm.html` (localStorage) and export to `llm-comments.json` / `llm-comments.md` in this
folder — drop the export here and I'll read and act on it.*
