# E8 — Deterministic Coaching Computations

| | |
|---|---|
| **Status** | 🔵 ready for dev |
| **Phases** | 5 |
| **Depends on** | E6, E3 |
| **Unblocks** | E10, E11 |
| **Primary refs** | [`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §2, §6 · [`LLM.md`](../docs/architecture/LLM.md) §3 · [`MODELS.md`](../docs/architecture/MODELS.md) Readiness/SafetyGate/MacroFocus/WeeklyBudgets/WeeklyTargets |

---

## 1. Summary & goal

Implement the **code side of the code/LLM boundary** — every number and boolean the model is handed and
never asked to compute ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §2;
[`LLM.md`](../docs/architecture/LLM.md) §3). Pure, tested functions for **readiness**, the **safety gate**,
the **macro engine**, **weekly budgets/volume ramp**, and the **monthly recompute helpers**. The LLM
performs no arithmetic — it receives these pre-computed numbers and flags and chooses within them.

## 2. Requirements

- **R1** — **Readiness** (`ComputeReadinessNode`, §6.1): start at 100, subtract **itemised penalties**,
  clamp to [0,100], band it (`green` ≥75 · `amber` 50–74 · `red` <50). **Purely physiological** — reads
  rolling baselines from `daily_metrics`; **no** subjective check-in inputs. Penalty factors:
  `sleep_below_7h`, `sleep_below_5h`, `hrv_below_baseline`, `rhr_above_baseline`, `yesterday_hard_day`
  ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §6.1; [`MODELS.md`](../docs/architecture/MODELS.md) Readiness/ReadinessPenalty).
- **R2** — **Safety-gate booleans** (`SafetyGateRouter`, §6.2): any reason ⇒ `triggered`, with
  `overrideTo` forced card; reasons `gi_flare`, `sleep_below_4h`, `illness`, `knee_pain_high`, `rhr_spike`,
  `hrv_crash`. Auto-regulation only, **not** a medical layer
  ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §6.2; [`MODELS.md`](../docs/architecture/MODELS.md) SafetyGate).
- **R3** — **Macro engine** (§7): BMR/TDEE = BMR × activity factor with deficit %; protein ~constant 1.8
  g/kg; fat 0.8–1.0 g/kg range; carbs + calories by `dayType` (hard/moderate/rest multipliers); hydration
  3.0–3.5 L + sweat. Builds `MacroFocus` (daily) and `WeeklyNutrition` numbers; **all grams code-computed**
  from the chosen `dayType` + **live weight** (`daily_metrics.body_weight`)
  ([`MODELS.md`](../docs/architecture/MODELS.md) MacroFocus/WeeklyNutrition; [`LLM.md`](../docs/architecture/LLM.md) §1.1; [`DB.md`](../docs/architecture/DB.md) §5 nutrition).
- **R4** — **Weekly budgets** (`ComputeBudgetsNode`, §5.1): `hardDays` = 2 (or 3 only when sleep ≥6.5h +
  HRV ≥baseline + no GI); `strengthSessions` protected at 2; `longRunKm` capped ≤10%/wk ramp (§9);
  `deload` every 4th week or auto-triggered ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §5.1, §9; [`MODELS.md`](../docs/architecture/MODELS.md) WeeklyBudgets).
- **R5** — **Monthly recompute helpers** (§10): cadence ramp **+5 toward target every 2–3 wk**;
  **threshold↔VO₂ weekly alternation** (deterministic flip off last week's plan); **strength-test trend
  smoothing**; **re-derive zones** when anchors move (writes via E3)
  ([`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §6, §10; [`LLM.md`](../docs/architecture/LLM.md) §3 settled table; [`MODELS.md`](../docs/architecture/MODELS.md) WeeklyTargets `cadenceSpm`).
- **R6** — Everything here is **pure** (inputs → numbers/flags), unit-testable without the LLM or HTTP
  layer; the nodes in E10/E11 call these.

## 3. What to implement (by phase)

### E8·P1 — Readiness score, penalties & bands
Per R1 — function returning `{score, band, penalties[]}` from `daily_metrics` + yesterday's `hard_day`.

### E8·P2 — Safety-gate booleans
Per R2 — function returning `{triggered, reasons[], overrideTo}` from the check-in + this-morning metrics.

### E8·P3 — Nutrition / macro engine
Per R3 — `MacroFocus(dayType, weight)` and the `WeeklyNutrition` numbers + `dayTypePattern` helper; carb
levels by `day_type` (`hard ≈ 4–5`, `moderate ≈ 3`, `rest ≈ 2–2.5` g/kg).

### E8·P4 — Weekly budgets, volume ramp & deload
Per R4 — `ComputeBudgetsNode` logic: hard-day ceiling (with the 3-day condition), strength=2, ≤10%/wk
long-run ramp from history, deload flag.

### E8·P5 — Monthly recompute helpers
Per R5 — cadence ramp, threshold↔VO₂ alternation, strength-test smoothing, zone re-derivation. (The node
that *orchestrates* these and rewrites `profile.yaml` lives in E10·P2; here they are the helpers.)

## 4. Acceptance criteria

- [ ] Readiness: a worked example (e.g. sleep 6.5h + HRV 1SD low + yesterday hard) yields the exact score,
      band, and itemised penalties; score clamps at 0 and 100.
- [ ] Safety gate: each reason triggers with the correct `overrideTo`; no reason ⇒ `triggered=false`.
- [ ] Macros: TDEE/protein/fat/carbs/hydration match hand-computed values for a given weight on hard /
      moderate / rest days; protein never exceeds 2.0 g/kg and deficit never exceeds 0.20.
- [ ] Budgets: 2 hard days by default, 3 only when the condition holds; strength fixed at 2; long-run cap
      ≤ 110% of the prior week; deload on the 4th week.
- [ ] Recompute helpers: cadence ramps +5 only every 2–3 weeks; threshold/VO₂ alternates off last week;
      strength smoothing trends correctly; zone re-derivation matches `compute_zones`.
- [ ] All functions pure and unit-tested with no LLM/DB-session coupling beyond reading provided inputs.

## 5. Expected outcome

The complete deterministic toolkit the two briefs feed the LLM — readiness/gate/macros/budgets/ramps — so
the model only selects and tunes within trustworthy numbers.

## 6. Validation

Table-driven unit tests per function with worked examples drawn from the constitution's rules; edge cases
(clamping, caps, deload boundary, ramp cadence).

## 7. Out of scope

The LLM call, the workflow node graph, and persisting briefs (E9/E10/E11). E8 is pure computation; E7 owns
`CARD_META`-derived fields and the validators.
