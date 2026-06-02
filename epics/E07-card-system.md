# E7 — Card System (`CARD_META`)

| | |
|---|---|
| **Status** | 🔵 ready for dev |
| **Phases** | 3 |
| **Depends on** | E1 |
| **Unblocks** | E9, E10, E11 |
| **Primary refs** | [`CARDS.md`](../docs/architecture/CARDS.md) (all) · [`MODELS.md`](../docs/architecture/MODELS.md) design rules 1–2 · [`LLM.md`](../docs/architecture/LLM.md) §3, §4 |

---

## 1. Summary & goal

Encode **`CARD_META`** — the single source of truth for every prescribable workout — and the code that
uses it three ways at once ([`CARDS.md`](../docs/architecture/CARDS.md) intro): **derive-don't-emit**
(expand slim LLM picks into full sessions), **validation** (police picks), and **prompt rendering** (the
pool the constitution shows the model is generated from here). Change a card once and the schema, prompt,
and validator all move together.

## 2. Requirements

- **R1** — `CARD_META` holds **all 20 cards** with their fixed attributes: `intensity`, `is_hard`,
  `day_type`, `zone`, `hr_cap`, `cadence`, `impact`, dose band (min low/high), `flags`, `serves`
  ([`CARDS.md`](../docs/architecture/CARDS.md) §1A–§1E).
- **R2** — The **two independent axes** are modelled separately: `is_hard` (training load → hard-day
  budget & spacing) vs `day_type` (fuel demand → carb-cycling). `is_hard` ≠ `day_type` (a long run is
  `is_hard=false` but `day_type=hard`) ([`CARDS.md`](../docs/architecture/CARDS.md) §0).
- **R3** — **Enums** per [`MODELS.md`](../docs/architecture/MODELS.md): `WorkoutCard`, `Zone`,
  `Intensity`, `DayType`, `Tier`, `Weekday`, `NarrativeType` (and `RecordType` if not already in E5).
- **R4** — **Derive-don't-emit**: expand `SessionPick`→`SessionBlock` and `PlannedPick`→`PlannedSession`,
  filling `intensity`/`zoneTarget`/`isHardDay`/`hrCapBpm`/`cadenceSpm`/`flags` from `CARD_META`; run cards
  get the cadence cue from `profile.yaml`; `tier` implied by `core[]` vs `extras[]`
  ([`MODELS.md`](../docs/architecture/MODELS.md) SessionBlock/PlannedSession; [`LLM.md`](../docs/architecture/LLM.md) §3).
- **R5** — **Pure validators** `validate_weekly(out, ctx)` / `validate_daily(out, ctx) → Violation[]`
  (`{rule, message, severity}`), fully unit-testable **without the LLM**, enforcing the invariants in
  [`CARDS.md`](../docs/architecture/CARDS.md) §4 and [`LLM.md`](../docs/architecture/LLM.md) §4.
- **R6** — The `dayType` **fuel floor**: a card with `is_hard=true` or `long_run` floors `dayType` at
  `hard` — the validator enforces it; the LLM may fuel up but never under-fuel
  ([`CARDS.md`](../docs/architecture/CARDS.md) §0, §4).
- **R7** — **No medical/NSAID denylist** — §2 is LLM context, not a code-enforced layer
  ([`LLM.md`](../docs/architecture/LLM.md) §4).

## 3. What to implement (by phase)

### E7·P1 — CARD_META table & enums
- The canonical `CARD_META` keyed by `card` with all attributes (R1/R2), plus the **flags vocabulary** and
  the **AMBER/RED auto-regulation downgrade map** ([`CARDS.md`](../docs/architecture/CARDS.md) §2, §3).
- All enums (R3).

### E7·P2 — Derive-don't-emit expansion
- `SessionPick`→`SessionBlock` and `PlannedPick`→`PlannedSession` expanders filling card-derived fields
  from `CARD_META`; cadence cue from `profile.yaml cadence_current_spm`; `tier` from array membership.
- Code-completed shapes that "can't be wrong by construction."

### E7·P3 — constraints.py — pure validators
- `validate_weekly`: hard-day count ≤ budget, spacing (no adjacent hard days, no hard run after boxing),
  strength count == budget, `core` 2–3 / `extras` 1–2, ≤1 long run, threshold↔VO₂ match, deload ⇒ ≤1 hard.
- `validate_daily`: card ∈ week plan ∪ allowed low-impact subs, RED ⇒ `day_type=rest` card only, AMBER ⇒
  no full Z5/`vo2` dose, `knee_pain>3` ⇒ no `impact` card, dose-in-band, `alternatives` ≤ 2, **`dayType` ≥
  fuel floor**.
- Returns `Violation[]`; no LLM, no medical denylist.

## 4. Acceptance criteria

- [ ] `CARD_META` contains all 20 cards with attributes matching [`CARDS.md`](../docs/architecture/CARDS.md)
      §1 exactly (spot-checked: `long_run` is `is_hard=false`/`day_type=hard`; `vo2` impact `high`).
- [ ] Expanding a `SessionPick {card, dose}` yields a full `SessionBlock` whose derived fields equal
      `CARD_META[card]` (and run cards carry the cadence cue).
- [ ] `validate_weekly`/`validate_daily` flag each invariant violation with a stable `rule` key and pass a
      clean plan/session.
- [ ] The `dayType` fuel-floor rule rejects a `rest`/`moderate` dayType on a hard/long card and accepts
      `hard`.
- [ ] Validators are pure (no DB/LLM) and fully covered by unit tests, including the
      [`CARDS.md`](../docs/architecture/CARDS.md) §3 downgrade substitutes for the card-in-plan check.

## 5. Expected outcome

One data table powering derive + validate + prompt — so both briefs (E10/E11) emit only genuine picks and
every card-derived field/number is filled and policed in code.

## 6. Validation

- `CARD_META` completeness test (count, attribute presence).
- Expansion unit tests (each derived field; cadence cue; tier).
- Validator unit tests for every weekly/daily invariant + the fuel floor + downgrade subs.

## 7. Out of scope

Wiring validators as PydanticAI `output_validator`s with `ModelRetry` (E9·P2) — here they are **pure
functions**. Budget/readiness inputs they read come from E8.
