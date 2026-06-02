# Coach App — The Workout Pool (`CARD_META`)

> The machine-readable form of [`HEALTH-CONSITTUTION.md`](../../HEALTH-CONSITTUTION.md) §4. Every workout
> the brain can prescribe is a **card**; this file is the **single source of truth** (`CARD_META`) for
> each card's fixed attributes. It powers three things at once:
>
> 1. **Derive-don't-emit** ([`MODELS.md`](./MODELS.md)) — the LLM emits only `{card, dose, suggestedDay}`;
>    code fills `intensity` / `zoneTarget` / `isHardDay` / `hrCapBpm` / `cadenceSpm` / `flags` / `dayType`
>    from this table, so those fields can't be wrong.
> 2. **Validation** ([`LLM.md`](./LLM.md) §4) — the validator checks picks against this table (card in pool,
>    dose in band, hard-day count, impact gating).
> 3. **Prompt rendering** — the pool the constitution shows the model is generated from here.
>
> Visual companion: open [`cards.html`](./cards.html). The **`.md` is the source of truth**; the `.html`
> is generated from it.

---

## 0. Two independent axes — read this first

A card carries **two** "hardness" flags that are *not* the same thing:

| Axis | Column | Drives | Example of the difference |
|---|---|---|---|
| **Training load** | `is_hard` | the **hard-day budget** & spacing (§5.1, §6.2) — max 2–3/wk, never back-to-back | a **long run** is `is_hard = false` (it's the marquee *easy* session, spacing-wise)… |
| **Fuel demand** | `day_type` | **nutrition** carb-cycling (§7.3) — hard / moderate / rest | …but `day_type = hard` (you still carb-load to fuel it). |

So `is_hard` ≠ `day_type`. Code reads `is_hard` for budgeting/spacing and `day_type` for `MacroFocus`.

**`day_type` → carb level** (§7.3): `hard` ≈ 4–5 g/kg · `moderate` ≈ 3 g/kg · `rest` ≈ 2–2.5 g/kg.
Protein and fat are constant; carbs and total calories move with `day_type`.

> **`day_type` here is the DEFAULT + the fuel FLOOR, not a fixed value.** The daily LLM picks the actual
> `dayType` as its one nutrition lever ([`LLM.md` §3](./LLM.md)) — it may decouple fuel from training (e.g.
> drop an easy day to `rest` carbs for a deficit push, or hold `hard` the day before a key session). The
> **guardrail** (validator): a card with `is_hard = true` *or* `long_run` floors `dayType` at `hard` — the
> LLM can fuel *up* but never *under-fuel* a hard/long session. Macro grams are always code-computed.

---

## 1. `CARD_META` — the canonical table

Grouped by category for reading; it is one logical table keyed by `card`. `hr_cap` / `cadence` reference
`profile.yaml` (`easy_hr_cap`, `cadence_current_spm`). "—" = not applicable (`null`).

### 1A. Running

| `card` | intensity | `is_hard` | `day_type` | zone | `hr_cap` | cadence | impact | dose (min) | flags | serves |
|---|---|---|---|---|---|---|---|---|---|---|
| `easy_run` | easy | false | moderate | z2 | `easy_hr_cap` | cue | yes | 25–50 | `impact` | aerobic base, fat ox., recovery |
| `long_run` | easy | false | **hard** | z2 *(by effort)* | `easy_hr_cap` start, drift OK | cue | yes | 60–90+ | `impact`, `long`, `effort_based` | endurance, durability, HM progression |
| `progression_run` | quality | **true** | hard | z2→z4 | — | cue | yes | 50–80 | `quality_day`, `impact`, `needs_green_knee` | running on tired legs; HM stamina *(periodized upgrade)* |
| `threshold` | quality | **true** | hard | z4 | — | cue | yes | 30–50 | `quality_day`, `impact` | lactate threshold, "comfortably hard" |
| `vo2` | quality | **true** | hard | z5 | — | cue | **high** | 25–45 | `quality_day`, `impact`, `needs_green_knee` | top-end aerobic power, VO₂max |
| `strides` | easy | false | moderate | z5 *(brief)* | — | cue | yes | 5–12 | `impact`, `append_to_easy` | running economy, neuromuscular, cadence |
| `active_recovery` | recovery | false | rest | z1 | — | — | **no** | 20–40 | `low_impact` | blood flow, gentle recovery (walk/spin/row/mobility) |

### 1B. Cardio

| `card` | intensity | `is_hard` | `day_type` | zone | `hr_cap` | cadence | impact | dose (min) | flags | serves |
|---|---|---|---|---|---|---|---|---|---|---|
| `hiit` | quality | **true** | hard | z4–z5 | — | — | conditional | 15–25 | `quality_day`, `prefer_low_impact` | conditioning, fat loss, time-efficient |
| `jump_rope` | quality | false | moderate | z3–z4 | — | cue | yes | 8–20 | `impact`, `knee_amber_cap` | conditioning, calf/foot stiffness, cadence |
| `steady_cardio` | easy | false | moderate | z2 | — | — | **no** | 30–50 | `low_impact` | low-impact aerobic base (bike/row/elliptical/incline walk) |

### 1C. Strength — calisthenics + functional (park bars + bodyweight)

| `card` | intensity | `is_hard` | `day_type` | zone | `hr_cap` | cadence | impact | dose (min) | flags | serves |
|---|---|---|---|---|---|---|---|---|---|---|
| `strength_push` | quality | false | moderate | — | — | — | **no** | 30–45 | `strength`, `upper` | upper-body muscle (chest/shoulder/triceps) |
| `strength_pull` | quality | false | moderate | — | — | — | **no** | 30–45 | `strength`, `upper` | upper-body muscle (back/biceps) + posture |
| `strength_lower` | quality | false | moderate | — | — | — | low | 25–35 | `strength`, `lower` | running support, knee stability |
| `strength_full` | quality | false | moderate | — | — | — | low | 20–35 | `strength` | GPP, carryover, time-crunch option |

### 1D. Boxing (class — available every day, twice a day; place by spacing, §5.2)

| `card` | intensity | `is_hard` | `day_type` | zone | `hr_cap` | cadence | impact | dose (min) | flags | serves |
|---|---|---|---|---|---|---|---|---|---|---|
| `boxing` | quality | **true** | hard | z3–z5 | — | — | low | 60–90 | `quality_day`, `big_recovery_cost` | conditioning, fat loss, adherence, upper-body endurance |
| `boxing_technique` | easy | false | moderate | z2–z3 | — | — | low | 45–60 | `auto_reg_downgrade` | skill on a tired/amber day (footwork/pads light) |

### 1E. Mobility / prehab (supporting — tiny doses, near-daily OK)

| `card` | intensity | `is_hard` | `day_type` | zone | `hr_cap` | cadence | impact | dose (min) | flags | serves |
|---|---|---|---|---|---|---|---|---|---|---|
| `foot_prehab` | recovery | false | rest | — | — | — | **no** | 5–10 | `prehab:foot` | arch/intrinsic strength (flat feet), ↓ injury |
| `glute_prehab` | recovery | false | rest | — | — | — | **no** | 5–10 | `prehab:glute` | knee tracking, ↓ knee pain |
| `mobility` | recovery | false | rest | — | — | — | **no** | 10–30 | `red_day_default` | recovery, range, stress/sleep (pre-bed OK) |
| `rest` | recovery | false | rest | — | — | — | **no** | 0 | — | full rest (the gate/RED default) |

---

## 2. Flags vocabulary

Machine keys filled by code (never emitted by the LLM). The app reads them; the validator enforces them.

| Flag | Meaning |
|---|---|
| `impact` | high ground-impact — subject to the knee gate (§6.2 `knee_pain > 3` → blocked) and flat-foot dosing (§8.3). |
| `needs_green_knee` | only when knee is green (0–~1); the highest-impact cards. |
| `quality_day` | consumes a hard-day budget slot (mirrors `is_hard = true`). |
| `prehab:foot` / `prehab:glute` | tiny prehab to attach to a session (§4E, §5.1 — woven into ≥3 days). |
| `low_impact` | safe knee/flat-foot substitute for impact cards. |
| `prefer_low_impact` | pick the low-impact mode (bike/row) when the knee is iffy. |
| `knee_amber_cap` | allowed up to knee-amber only; small doses (jump rope). |
| `append_to_easy` | not a standalone session — added to the end of an easy run. |
| `effort_based` | run by easy *effort*, not a hard HR ceiling; accept late cardiac drift (long run). |
| `auto_reg_downgrade` | this *is* the reduced version of a harder card (boxing → technique). |
| `big_recovery_cost` | high recovery debt; respect spacing, no hard running the day after. |
| `long` · `strength` · `upper` · `lower` | descriptive grouping. |

---

## 3. Auto-regulation downgrades (AMBER / RED)

The daily adjuster (§6) reduces a planned card by readiness band. AMBER reduction is **LLM judgment within
the rule** ([`LLM.md` §3](./LLM.md)) — shorten the dose 20–40%, drop the top zone, or swap per this map.
RED and the safety gate are **deterministic**.

| Planned card | AMBER (compromised) → | RED / safety-gate → |
|---|---|---|
| `vo2`, `threshold`, `progression_run` | `easy_run` or `steady_cardio` (drop top zone, −20–40%) | `active_recovery` / `mobility` / `rest` |
| `hiit` | `steady_cardio` (or low-impact circuit, shorter) | `active_recovery` / `mobility` |
| `boxing` | `boxing_technique` | `rest` / `mobility` |
| `long_run` | shorter `easy_run` (medium) | `active_recovery` / `rest` |
| `easy_run` | `steady_cardio` if knee-amber; else shorten | `active_recovery` / `mobility` |
| `jump_rope` | drop (knee-amber cap) → `steady_cardio` | `rest` |
| `strength_*` | "light" version (technique/pump, fewer sets) | `mobility` / `rest` |
| any `impact` card with `knee_pain > 3` | n/a — **safety gate** forces a low-impact/pull substitute | per gate |

---

## 4. Invariants the validator checks against this table

- The chosen `card` ∈ `CARD_META`.
- `durationMin[Low|High]` sits inside the card's **dose band** (§1).
- Weekly: `count(is_hard) ≤ budgets.hardDays`; no two `is_hard` cards on adjacent `suggestedDay`s;
  no `is_hard` **run** the day after `boxing`; `strength_*` count `== budgets.strengthSessions`;
  `core` 2–3 · `extras` 1–2 · ≤1 `long_run`.
- Daily: RED ⇒ a `day_type = rest` card only; AMBER ⇒ no full `vo2`/`z5` dose; `knee_pain > 3` ⇒ no
  `impact` card; the chosen card ∈ the week plan ∪ its allowed low-impact substitutes (§3); the chosen
  **`dayType` ≥ the card's fuel floor** (a `is_hard`/`long_run` card ⇒ `dayType == hard`).

> Keeping these as data here (not prose in four documents) is the point: change a card once, and the
> schema, the prompt, and the validator all move together.

---

*The **`.md` is the source of truth**; `cards.html` is generated from it (regenerate on change), in the
same paginated/commentable style as the other docs.*
