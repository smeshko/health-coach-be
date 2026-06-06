# Adaptive Training & Nutrition Schematic

> **What this is.** The rulebook ("constitution") an iOS app + LLM brain reads to (a) build a
> weekly plan every Monday and (b) adjust a daily suggestion every morning, using live Apple
> Health data. It is **dynamic, not strict**: it defines a *pool* of workouts, *budgets*, and
> *decision rules* — the brain picks and tunes within them. Not a fixed day-by-day calendar.
>
> Everything numeric here was derived from `health.db` (2024–2026) and `medical-docs/`.
> Re-derive the personalized constants monthly (see §10).
>
> **This file is a Jinja2 template.** Every numeric constant below is written as `{{ … }}` and
> **injected at render time from `profile.yaml`**, which is the **single source of truth** for
> constants (§10 writes `profile.yaml`, never this prose). The placeholder names map to the
> `profile.yaml` keys in [`docs/architecture/DB.md` §5](docs/architecture/DB.md). What the LLM (and
> a human reading the rendered file) sees is the resolved numbers; the template guarantees they
> can never drift from `profile.yaml`. Live/derived values (current weight, VO₂max, sleep avg)
> are **not** constants — they are fed as computed context, not rendered here.

---

## Table of contents
1. [Athlete profile & goals](#1-athlete-profile--goals)
2. [Medical constraints (read first — context the brain weighs)](#2-medical-constraints)
3. [Training zones & personal thresholds](#3-training-zones--personal-thresholds)
4. [The workout pool (the menu)](#4-the-workout-pool)
5. [Weekly planner — the Monday loop](#5-weekly-planner--the-monday-loop)
6. [Daily adjuster — the morning loop](#6-daily-adjuster--the-morning-loop)
7. [Nutrition framework (macros & calories)](#7-nutrition-framework)
8. [Safety, flares & auto-regulation](#8-safety-flares--auto-regulation)
9. [Progression rules](#9-progression-rules)
10. [Monthly recompute & metrics to watch](#10-monthly-recompute)
11. [Data contract (what the app must feed the brain)](#11-data-contract)

---

## 1. Athlete profile & goals

> Constants are `{{ … }}` placeholders rendered from `profile.yaml` (the single source). Live values
> (current weight, VO₂max, sleep, steps) are fed as computed context, shown here as a snapshot only.

| Field | Value | Source / note |
|---|---|---|
| Age / sex | `{{ athlete.age }}` / `{{ athlete.sex }}` | `profile.yaml` |
| Height | `{{ athlete.height_cm }}` cm | `profile.yaml` |
| Weight (current) | live → latest HealthKit `body_mass` | synced from HealthKit (e.g. a connected scale), not a constant |
| Weight goal | `{{ athlete.goal_weight_kg }}` kg | `profile.yaml` |
| Max HR | **`{{ thresholds.max_hr }}` bpm** | `profile.yaml`; from observed boxing peaks |
| Resting HR baseline | **`{{ thresholds.rhr_baseline }}` bpm** | `profile.yaml` monthly anchor; readiness uses the live 30-day mean |
| HRV (SDNN) baseline | **`{{ thresholds.hrv_baseline_ms }}` ms** | `profile.yaml` (informational); readiness uses the live 30-day mean |
| VO₂max | **~42.5** (was ~37 a year ago) | *live/derived snapshot* — climbing; "good" for age |
| Sleep | **~5.7 h/night avg** (3.3–7.9) | *live/derived snapshot* — ⚠️ chronic short sleep = #1 recovery limiter |
| Daily steps | ~10k (≈6k–15k) | *live/derived snapshot* — solidly active NEAT; raw multi-source sums over-count ~2× (Watch + phone) |
| Active energy | ~550 kcal rest / ~1,500 kcal boxing day | *live/derived snapshot* — from activity_summary |

**Goals, ranked (recomp — both slowly):**
1. **Body recomposition → `{{ athlete.goal_weight_kg }}` kg** via a *modest* deficit + high protein (not aggressive — protect muscle, sleep, and gut).
2. **Improve running** — general improvement, build aerobic base + speed, progress long run toward half-marathon distance over time (no fixed race date).
3. **Gain upper-body muscle** — via calisthenics (no gym; access to a calisthenics park + functional training).

**Capacity:** 4–5 sessions/week sustainable. Pattern = **2–3 high-priority "core" + 1–2 optional "extras"**.

### Three problems the data says this program must fix
1. **No true-easy running.** Even slow ~6:30/km runs sit at avg HR 155–166 (Z3). → *Enforce an easy-HR cap so easy days are actually easy* (polarize). This is the single highest-leverage change.
2. **Low cadence (~150–162 spm).** Overstriding → exactly what punishes knees + flat feet. → *Cue 170+ spm.*
3. **Intensity is unmanaged.** Boxing is a Z3–5 bomb but isn't being counted as a hard day. → *Budget hard days; space them.*

---

## 2. Medical constraints
**(read first — the brain should weigh these over training/nutrition optimization in any conflict)**

> **Scope:** this is **context for the brain**, not a code-enforced compliance layer. This is a
> workout-and-nutrition app, not a medical device. The conditions below exist so the LLM makes
> *better-informed* suggestions (e.g. lactose-safe protein, no large fat boluses, NSAID-free knee
> care). The only constraints enforced deterministically in code are the **training auto-regulation
> gates** in §6.2 (GI symptoms / illness / knee / sleep / HRV-RHR) — everything else here is
> guidance the brain applies through the system prompt.

Conditions (MBAL-Varna, UC currently **in remission**, CRP 1.4, normal labs):
- **Ulcerative proctitis E1S1 / K51.2** (rectum-limited, mild, remission since late 2024)
- **Chronic antral gastritis + erosive duodenitis** (upper-GI)
- **Reflux esophagitis (GERD)**
- **Biliary dyskinesia** (kinked gallbladder, no stones)
- **Dolichosigma** (elongated sigmoid → constipation-prone) + **hemorrhoids**
- **Lactose intolerance**
- **Bilateral kidney microliths** (small stones, no obstruction)
- Family history: **Hashimoto's** (mother) → periodic TSH check advisable
- Maintenance meds: Salofalk (mesalazine/5-ASA) granules, butyrate suppositories, probiotic; Budenofalk (budesonide) foam as-needed for flares.

### Hard rules these impose
| Constraint | Rule for the app |
|---|---|
| 🚫 **No NSAIDs** (ibuprofen/diclofenac/etc.) | Triple-contraindicated (UC + gastritis/duodenitis + kidney stones). For knee pain use load management, ice, topical, paracetamol if needed, physio. **Never suggest NSAIDs.** |
| **Lactose intolerance** | Avoid high-lactose dairy (milk, fresh/soft cheese, milk-chocolate, whey *concentrate*). OK: lactose-free milk, fermented/aged dairy (Greek yogurt, kefir, hard cheese), **whey isolate or plant protein** for powder. |
| **GERD + gastritis + duodenitis** | No large/late meals (finish ≥3 h before lying down or hard training); limit coffee, very spicy, big acidic-tomato loads, carbonated drinks, alcohol, peppermint, fried food. Don't train hard on a full stomach or with active reflux. |
| **Biliary dyskinesia** | Moderate fat *per meal*, spread across the day; avoid large greasy/fried boluses (also helps reflux). |
| **Dolichosigma + hemorrhoids + UC** | Adequate **soluble-fiber-forward** intake + excellent hydration to prevent constipation/straining; reduce insoluble/high-residue around hard sessions and during flares. |
| **Kidney microliths** | High hydration (target below), citrate (lemon water), **moderate sodium**, calcium *with* meals (binds oxalate), don't megadose protein or vitamin C, moderate high-oxalate foods (spinach/beets/nuts/black tea). |
| **UC flare = systemic event** | On flare signs (see §8): deload training, go low-residue, hydrate + electrolytes. Persistent/bloody → see doctor. |

> **Exercise is good for UC in remission** — moderate training is anti-inflammatory. The watch-outs are
> (1) very long/very hard endurance can transiently irritate the gut (fuel/hydrate smart around boxing + long runs),
> and (2) recovery debt (sleep, under-fueling) can nudge a flare. The program is built to respect both.

---

## 3. Training zones & personal thresholds

**HR zones** (Max `{{ thresholds.max_hr }}`, RHR `{{ thresholds.rhr_baseline }}`). Primary anchor =
**% of max HR**; the easy cap = **Maffetone 180−age = `{{ thresholds.easy_hr_cap }}`**. The bpm bounds
below are rendered from `profile.yaml`'s `zones` (computed by `compute_zones.py`).

| Zone | % HRmax | bpm | Feel / RPE | Use |
|---|---|---|---|---|
| **Z1** Recovery | 50–65% | `{{ zones.z1[0] }}`–`{{ zones.z1[1] }}` | RPE 1–2, full convo | warm-up, cooldown, recovery walks/spins |
| **Z2** Easy / Aerobic | 65–78% | `{{ zones.z2[0] }}`–`{{ zones.z2[1] }}` | RPE 3–4, full sentences | **most running lives here**; long runs |
| **Z3** Tempo | 78–87% | `{{ zones.z3[0] }}`–`{{ zones.z3[1] }}` | RPE 5–6, short phrases | tempo, "comfortably hard", much of boxing |
| **Z4** Threshold | 87–92% | `{{ zones.z4[0] }}`–`{{ zones.z4[1] }}` | RPE 7–8, words only | threshold intervals, hard boxing rounds |
| **Z5** VO₂ / Anaerobic | 92–100% | `{{ zones.z5[0] }}`–`{{ zones.z5[1] }}` | RPE 9–10, no talking | VO₂ intervals, sprints, max boxing flurries |

### The non-negotiables
- **EASY-RUN HR CAP = `{{ thresholds.easy_hr_cap }}` bpm.** On *short* easy runs keep average HR ≤ the cap (ideal `{{ thresholds.easy_hr_cap - 8 }}`–`{{ thresholds.easy_hr_cap }}`); if HR drifts above, **slow down or walk** — run/walk is expected and fine early. (Long runs are effort-based with allowed late drift — see the Long-run card.) This will feel humiliatingly slow at first; it is the point.
- **CADENCE TARGET = `{{ thresholds.cadence_target_spm }}` spm.** Current ~155 spm. Cue toward the target, raising **~+5 spm per ~2–3 weeks** (don't jump straight there). The app feeds the *current* week's cue (a deterministic ramp from 155 toward the target, +5 every 2–3 weeks); higher cadence shortens stride → less overstride → less knee/foot load. App can use a metronome/cue.
- **POLARIZATION = 80/20.** ~80% of *running* time in Z1–Z2, ~20% in Z4–Z5. Minimize Z3 "junk" running. (Boxing is intentionally Z3–5 — it's a *hard* day, not easy filler.)
- **WEEKLY VOLUME RAMP ≤ 10%.** Never increase running distance >10% week-over-week (knee/foot protection).

---

## 4. The workout pool

The brain composes weeks and days from these cards. Each: **goal served · intensity · typical dose ·
frequency cap · flags**. Categories match the user's four buckets + a supporting prehab bucket.

### 4A. RUNNING
| Card | Zone | Dose | Serves | Notes / flags |
|---|---|---|---|---|
| **Easy run** | Z2 (cap `{{ thresholds.easy_hr_cap }}`) | 25–50 min | aerobic base, fat ox., recovery | the bread-and-butter; cadence cue (§3); run/walk OK |
| **Long run** | Z2 *by effort* (start ≤`{{ thresholds.easy_hr_cap }}`; allow drift to ~155 in the final third) | start ~60–70 min / ~8–10 km, build | endurance, durability (time on feet), HM progression | run by easy *effort*, not a hard HR ceiling — accept cardiac drift late, don't slow to a crawl; cadence cue (§3); progress +~1 km/wk *or* ≤10%/wk; the week's marquee easy session |
| **Progression / quality long run** | Z2→Z3/Z4 | easy first 75–85%, then 15–25% at moderate/HM effort *or* an embedded tempo block | running on tired legs; HM-specific stamina | **counts as a QUALITY/hard day** (consumes a hard-day slot); periodized *upgrade* — only once base is built / nearing a HM, not in base phase |
| **Active recovery** (walk / easy spin / row / mobility) | Z1 | 20–40 min | blood flow, gentle recovery — *no impact* | replaces the old "recovery jog": a Z1 jog ≈ walking pace for him and just adds pounding; ~10k daily steps already supply his Z1. Running = two flavors only: easy (Z2) & quality (Z4/5). A true recovery *jog* re-earns a slot only at HM-peak mileage. |
| **Threshold / tempo** | Z4 (Z3→Z4) | 2–4 × 6–10 min @ ~167–175, or 20 min steady | lactate threshold, "comfortably hard" stamina | **quality day**; needs ≥1 easy/rest day on each side |
| **VO₂ intervals** | Z5 | 4–6 × 3 min / 5–8 × 2 min, equal jog | top-end aerobic power, VO₂max | **quality day**; high knee load → only with green knee |
| **Strides / sprints** | Z5 (brief) | 6–8 × 15–20 s relaxed fast + 5–10 × short hill sprints | running economy, neuromuscular, fast w/ low injury risk | low systemic cost; great cadence teacher; add to end of easy run |

### 4B. CARDIO
| Card | Zone | Dose | Serves | Notes / flags |
|---|---|---|---|---|
| **HIIT** (circuit/bike/row) | Z4–Z5 | 15–25 min (e.g. 30/30 or 40/20) | conditioning, fat loss, time-efficient | **quality day**; prefer low-impact modes when knee is iffy |
| **Jump rope** | Z3–Z4 | 8–20 min (intervals) | conditioning, calf/foot stiffness, cadence/coordination | **impact** — caps at knee-amber; builds foot resilience in small doses |
| **Steady cardio** (bike/row/incline walk/elliptical) | Z2 | 30–50 min | low-impact aerobic base when running is restricted | knee/flat-foot safe substitute for easy runs |

### 4C. STRENGTH — calisthenics + functional (no gym; park bars + bodyweight + optional band/backpack)
| Card | "Light/Hard" | Dose | Serves | Notes |
|---|---|---|---|---|
| **Upper PUSH** | hard | 30–45 min | **upper-body muscle** (chest/shoulder/triceps) | push-up progressions → dips (park) → pike/HSPU; 3–4 sets near failure, slow tempo |
| **Upper PULL** | hard | 30–45 min | **upper-body muscle** (back/biceps) + posture | pull-up/chin progressions (negatives→band→full→archer→backpack-weighted) + inverted rows |
| **Lower + posterior** | hard | 25–35 min | running support, knee stability | squats, split squats, step-ups, single-leg RDL, Nordic-ish hamstring, calf raises |
| **Full-body functional** | light/hard | 20–35 min | GPP, carryover, time-crunch option | mixed circuit; "light" = technique/pump, "hard" = near-failure + tempo |
| **Progression knob** | — | — | drive hypertrophy without a gym | reps → tempo (3–4 s eccentric) → harder leverage → added load (weighted vest/backpack) → unilateral |

### 4D. BOXING (class)
| Card | Zone | Dose | Serves | Notes / flags |
|---|---|---|---|---|
| **Boxing class** | Z3–Z4–Z5 | ~60–90 min | conditioning, fat loss, fun adherence, upper-body endurance | **counts as a QUALITY/hard day** (avg HR ~150, peaks 185–192). Big recovery cost. |
| **Boxing — technique-only** | Z2–Z3 | 45–60 min | skill on a tired/amber day | the auto-regulated downgrade: skip the hard conditioning rounds, keep footwork/pads light |

### 4E. MOBILITY / PREHAB (supporting — woven in, low cost, near-daily ok)
| Card | Dose | Serves | Notes |
|---|---|---|---|
| **Foot/arch prehab** (flat feet) | 5–10 min, 3–4×/wk | arch/intrinsic strength, ↓ injury | short-foot/doming, calf raises (incl. barefoot), tibialis raises, toe yoga, single-leg balance, towel scrunch |
| **Glute/hip activation** (knee) | 5–10 min | knee tracking, ↓ knee pain | bridges/hip thrusts, banded monster-walks, clamshells, single-leg balance |
| **Mobility / yoga / stretch** | 10–30 min | recovery, range, stress/sleep | the **red-day** default; also good pre-bed for sleep |

---

## 5. Weekly planner — the Monday loop

**Trigger:** every Monday. **Input:** last 1–4 weeks of data (see §11 data contract). **Output:** a tiered week
(2–3 core + 1–2 extras) drawn from the pool, plus weekly targets, **the week's nutrition (protein/fat/hydration
targets + the carb-cycling day-type pattern that follows the planned sessions + last week's intake adherence)**,
and rationale. Nutrition is a first-class half of the weekly brief, not an afterthought — see §7.

### 5.1 Budgets & spacing rules (the skeleton)
- **Hard-day budget:** **2 hard/quality days** to start; allow **3** only when 7-day avg sleep ≥6.5 h *and* HRV is at/above baseline *and* no GI symptoms. **Boxing = 1 hard day.** A threshold/VO₂/HIIT session = 1 hard day.
- **Spacing:** never two hard days back-to-back; ≥1 easy or rest day between hard days. **No hard running the day after boxing.**
- **Easy:run ratio:** keep ~80% of running easy (Z1–2).
- **Strength:** **2 sessions/week** (1 push-emphasis, 1 pull-emphasis, or 2 full-body upper-focused) — this is what actually drives the upper-body-muscle goal, so it's protected as core.
- **Long run:** 1×/week, progressed ≤10%/wk; it's a *core* on its week.
- **Prehab:** foot + glute work attached to ≥3 days (tiny doses, not a "session").
- **Deload:** every **4th week**, cut volume ~40% and drop to 1 hard day (also auto-triggered by §8).

### 5.2 Default core/extra template (4–5 days, in-remission, normal recovery)
> The brain assigns *types*, not rigid weekdays; the suggested day for each session is just a hint the daily loop can shuffle.

**CORE (high priority — 3):**
1. **Boxing class** (quality / Z3–5) — **classes run every day, twice a day, so availability is never a constraint**; place it purely by spacing and recovery (the user attends whichever session fits). The `suggestedDay` is a recovery-spacing hint, not a timetable lookup.
2. **One quality run** — alternate weekly: *Threshold* ↔ *VO₂ intervals* (+ strides). Placed ≥2 days from boxing.
3. **Strength — Upper (PULL-emphasis)** + foot/glute prehab.

**EXTRAS (optional — pick 1–2 by feel/readiness):**
4. **Easy or Long run** (Z2; easy cap `{{ thresholds.easy_hr_cap }}` / long run by effort) — the aerobic-base builder; becomes core on long-run-focus weeks.
5. **Strength — Upper (PUSH-emphasis)** or **Full-body functional**.
6. **Jump rope / HIIT / steady low-impact cardio / mobility** — flex slot.

Example sequencing (illustrative, brain adapts): `Mon strength-pull · Tue boxing · Wed easy run + foot prehab · Thu rest/mobility · Fri quality run (threshold/VO₂) · Sat strength-push (opt) · Sun long run (opt)`.

### 5.3 How last week's data reshapes the plan
| Signal from last week | Planner response |
|---|---|
| 7-day sleep <6 h avg | hold hard days at 2 (or 1); bias extras toward easy/mobility |
| Hit 0–1 strength sessions | promote a 2nd strength to core this week (muscle goal is lagging) |
| Running was all Z3 (no true easy) | add explicit easy-cap runs; cut a quality session if needed |
| Long run ≥ planned & felt good | progress long run +~1 km / ~10% |
| Weight trend flat 2–3 wks **and** intake on-target (logged calories ≈ plan) | nudge nutrition (slightly larger deficit on rest days) — *not* more training |
| Logged intake consistently **over** target (HealthKit dietary data) | the deficit isn't landing — surface it in the nutrition narrative; tighten rest-day carbs before touching training |
| Logged intake consistently **under** target / low protein | flag under-fuelling (gut + recovery risk); nudge protein and fuel around hard days |
| Any GI symptoms logged | this is a **deload week**: 1 hard day max, more mobility/easy, low-residue nutrition |
| Missed >half of sessions | rebuild momentum: fewer, easier, "minimum viable" week — protect consistency |

---

## 6. Daily adjuster — the morning loop

**Trigger:** every morning. **Input:** yesterday's load + last night's sleep + this-morning HRV/RHR +
the daily check-in flags (GI symptoms / illness / knee pain) + yesterday's logged nutrition intake +
the week's plan. **Output:** today's recommended session (tuned), alternatives, skip-OK flag, and the
day's macro focus.

### 6.1 Readiness score (0–100)
Start at 100; subtract penalties, then **clamp to [0, 100]**. Readiness is **objective-only** — it
reads only physiological signals (sleep, HRV, RHR, yesterday's load). The daily check-in carries no
subjective self-report; its inputs feed the safety gate (§6.2), not the score. Use **personal rolling
baselines** (30-day HRV mean, RHR mean), not population norms.

| Factor | Penalty |
|---|---|
| Sleep last night <7 h | −5 per hour below 7 (so 5 h → −10), min cap handled by safety gate |
| Sleep <5 h | additional −10 |
| Morning HRV vs baseline: 1 SD below | −15 · (>1 SD below → −25) |
| Morning RHR vs baseline: +5–7 bpm | −10 · (>+7 bpm → −20) |
| Yesterday was a hard/quality day | −15 (−25 if it was boxing *and* sleep <6 h) |

**Bands:**
- **GREEN ≥75** — ready. Do today's planned core (or upgrade to an optional extra if behind on the week).
- **AMBER 50–74** — compromised. *Keep the session but reduce*: hard→easy, shorten 20–40%, drop top zone (threshold→tempo, boxing→technique-only, long run→medium). Or swap to low-impact.
- **RED <50** — don't push. Active recovery only: walk, mobility/yoga, foot/glute prehab — or full rest.

### 6.2 Safety gate (checked *before* the score — any TRUE overrides to REST/active-recovery)
- **GI symptoms** (`giSymptoms` — a single yes/no the app collects, meaning *any* flare sign is present: blood in stool, >4 loose stools, urgency, or notable abdominal pain) → **no hard training**; easy/mobility only + nutrition deload (§7.5); persistent/bloody → see doctor.
- **Sleep <4 h** → rest or Z1 active recovery only.
- **Illness / fever** → rest.
- **Knee pain >3/10 or swelling** → **no running / jumping / plyo**; substitute pull-focused calisthenics, boxing-technique (light footwork), or low-impact cardio (bike/row/swim/elliptical) + glute prehab.
- **Resting HR >+12 bpm over baseline** or HRV crash >40% → treat as red regardless of score.

### 6.3 Daily decision tree
```
1. Safety gate any TRUE?  ── yes ─▶ REST or active-recovery card + adjusted nutrition. STOP.
                          └─ no ─▶ continue
2. Compute readiness band.
3. Pick today's session from the WEEK PLAN, respecting:
     • spacing (no hard day after a hard day / after boxing)
     • what's already done this week vs weekly targets
     • knee/flat-foot flags (impact gating)
     • equipment (park/bodyweight only)
4. Apply band modifier:
     GREEN → as planned (option to pull in an extra if week is behind)
     AMBER → reduce/downgrade per §6.1 (or swap to low-impact)
     RED   → active-recovery/rest card
5. Attach cadence target (runs), HR caps, and **pick the day's carb `dayType`** (within the guardrail) → code computes the macro focus (§7). **Weigh yesterday's logged intake (`intakeSummary` in the context — null if nothing was logged): if protein missed target or calories ran notably low/high, nudge the `dayType` accordingly (e.g. low-fuel + a rest/easy day → don't push the deficit further) and call it out briefly in a `nutrition` narrative section.** Speak to it qualitatively (e.g. "protein ran a little low yesterday") rather than quoting an exact percentage — the authoritative adherence figure is the one shown in `intakeYesterday`.
6. Emit suggestion + 1–2 alternatives + a skip-OK flag.
```

---

## 7. Nutrition framework

Macros & calories only (no fixed meals). All targets **parameterized by live weight `W` (kg)**;
the daily loop sets the *day type* from the planned session's intensity (carb-cycling). The medical
constraints in §2 are filters the brain applies to *every* recommendation. All nutrition constants
(`activity_factor`, `deficit_pct`, protein/fat g/kg, carb multipliers, hydration, fiber) live in
`profile.yaml`'s `nutrition` block and are rendered here as `{{ … }}` placeholders.

> **Nutrition is tracked, not just prescribed.** The user logs food in a third-party app that writes
> to HealthKit; the backend ingests **dietary energy, protein, carbs, fat, fiber, sodium, and water**
> (§11). So every brief sees **actual intake vs target** — the weekly loop adapts the plan from it
> (§5.3) and the daily loop reports yesterday's adherence. **Body weight is also from HealthKit**
> (`body_mass`, e.g. a connected scale) — the live `W` for the calorie/macro maths.

### 7.1 Calorie target (recomp = modest deficit)
```
BMR  = 10·W + 6.25·{{ athlete.height_cm }} − 5·{{ athlete.age }} + 5     # Mifflin-St Jeor (male)
TDEE = BMR · {{ nutrition.activity_factor }}                            # moderate NEAT: ~10k deduped steps + training
Target_avg = TDEE · (1 − {{ nutrition.deficit_pct }})                   # modest deficit for slow recomp
```
**Worked example at W=81 kg:** BMR ≈ 1,733 · 1.50 ≈ **TDEE ~2,600** → **avg target ~2,290 kcal/day**.
Expected loss ≈ 0.2–0.4 kg/wk. *(Computed in code from live `W`; never let the deficit exceed ~20%.)*

### 7.2 Macro rules (constant protein, gallbladder-aware fat, periodized carbs)
- **Protein: `{{ nutrition.protein_g_per_kg }}` g/kg/day** (range 1.6–2.0; **kidney-stone cap ~2.0** — don't megadose). ≈ **146 g** at 81 kg. Spread across 3–4 feedings; lactose-safe sources (poultry, fish, eggs, lean meat, legumes, Greek yogurt/kefir, hard cheese, **whey isolate or plant powder**).
- **Fat: `{{ nutrition.fat_g_per_kg_low }}`–`{{ nutrition.fat_g_per_kg_high }}` g/kg/day**, **spread across meals, no large single high-fat bolus** (gallbladder + reflux). ≈ **65–80 g**. Favor olive oil (fits Med/Italian), oily fish/omega-3 (anti-inflammatory for UC + joints).
- **Carbs: the adjustable lever**, set by day type below. Fill remaining calories.

### 7.3 Day-type carb cycling (this is what the morning loop tunes)
| Day type (planned session) | Carbs | Calories | Rationale |
|---|---|---|---|
| **Hard / long** (boxing, threshold, VO₂, long run, HIIT) | `{{ nutrition.carbs_g_per_kg.hard_low }}`–`{{ nutrition.carbs_g_per_kg.hard_high }}` g/kg (~325–405 g) | ~maintenance (~2,600) | fuel performance + recovery; don't under-fuel a flare-risk gut |
| **Moderate** (easy run, strength) | ~`{{ nutrition.carbs_g_per_kg.moderate }}` g/kg (~245 g) | ~avg target (~2,290) | steady |
| **Rest / recovery** | `{{ nutrition.carbs_g_per_kg.rest_low }}`–`{{ nutrition.carbs_g_per_kg.rest_high }}` g/kg (~165–200 g) | larger deficit (~2,080) | protein + fat hold; deficit comes from carbs |

> The `dayType` is the brain's **one nutrition lever** (the only nutrition choice it makes; code computes
> every gram from it). It **defaults** to the planned card's intensity, but the daily loop may adjust it —
> e.g. drop an easy/rest day to `rest` carbs to push the deficit when weight stalls (§5.3), or hold `hard`
> the day *before* a key session. **Guardrail:** it may never *under-fuel* a hard/long training day — a
> hard or long session floors `dayType` at `hard`. See [`CARDS.md`](docs/architecture/CARDS.md) /
> [`LLM.md`](docs/architecture/LLM.md).

Protein stays ~constant every day. The week nets out to the §7.1 average → slow recomp.

### 7.4 Standing medical nutrition filters (apply always)
- **Hydration: `{{ nutrition.hydration_l_low }}`–`{{ nutrition.hydration_l_high }}` L/day baseline + replace boxing/long-run sweat** (kidney stones). Add **citrate (lemon water)**; electrolytes around heavy-sweat sessions.
- **Sodium: moderate** (stones) but **replace around big sweat losses** — don't zero it out on boxing days.
- **Calcium *with* meals** (binds oxalate) — from lactose-free/fermented dairy or fortified alternatives.
- **Fiber: `{{ nutrition.fiber_g_low }}`–`{{ nutrition.fiber_g_high }}` g/day, soluble-forward** (oats, psyllium, cooked/peeled veg & fruit, legumes well-cooked) for dolichosigma/hemorrhoids; ease off insoluble/raw around hard sessions. *(Logged fiber/sodium from HealthKit let the brain check this against actual intake.)*
- **Moderate** high-oxalate foods (spinach/beets/nuts/black tea), coffee, alcohol, very spicy/fried, big acidic-tomato loads (GERD/gastritis).
- **Lactose:** lactose-free milk + fermented/aged dairy OK; avoid milk/fresh soft cheese/whey concentrate.

### 7.5 Fueling timing (GERD + gut-comfort aware)
- **Pre-boxing / pre-threshold (≤3 h):** moderate carb + some protein, **low fat, low fiber**; finish ≥2 h before to avoid reflux. Hydrate + electrolytes.
- **Pre easy/long AM run:** small carb (banana/toast) is better than fully fasted (gastritis = don't train hard on an empty acidic stomach); keep fat/fiber minimal.
- **Post (within ~1–2 h):** protein (~30–40 g, lactose-safe) + carbs to refill; this is the muscle-gain + recovery window.
- **GI-flare nutrition deload:** drop to low-residue/low-FODMAP-leaning (white rice, peeled cooked veg, lean protein, ripe banana), cut raw veg/legume skins/high-fiber temporarily, hydrate + electrolytes, keep protein up.

---

## 8. Safety, flares & auto-regulation

### 8.1 UC / GI flare protocol (auto-deload)
**Detect** (app prompts a quick daily GI check): blood, >4 loose stools/day, urgency, abdominal pain, or a clear uptick vs baseline.
**Respond:**
1. Training → **easy/mobility only** until 48 h symptom-free; no hard/long sessions.
2. Nutrition → §7.5 flare deload + hydration/electrolytes.
3. Sleep → prioritize (extend, no early hard sessions).
4. **Escalate to doctor** if blood, fever, or symptoms persist >3–5 days (Budenofalk foam is the user's as-needed med, but med decisions are the doctor's — the app only flags).

### 8.2 Knee-pain protocol (NSAID-free)
- Pain **1–3/10:** keep training; cut impact volume, ensure cadence 170+, add glute/calf/foot prehab, prefer softer/even surfaces, avoid steep downhill.
- Pain **>3/10 or swelling:** **no impact** — swap to pull-focused calisthenics, boxing-technique, bike/row/swim/elliptical + glute work.
- Persists **>2 weeks:** refer to physio. **Pain relief = ice / topical / paracetamol / load management — never NSAIDs** (§2).
- Footwear: supportive/stability shoes or orthotics for flat feet; replace worn shoes.

### 8.3 Flat-feet management (ongoing)
Foot/arch prehab ≥3×/wk (§4E), gradual barefoot-strength dosing, cadence 170+, ≤10%/wk volume ramps, build calf/foot capacity before adding running volume or plyometrics/jump rope.

### 8.4 Under-recovery / overtraining guardrails
Trigger a **forced deload** (or extra rest days) when **any two** hold for ~5–7 days: 7-day sleep <5.5 h, HRV >1 SD below baseline, RHR >+7 bpm, persistent soreness, motivation crash, or stalled/declining performance. Given chronic 5.7 h sleep, the app should **actively nudge sleep** (target ≥7 h) as a first-class recovery intervention — it gates everything else.

### 8.5 Refer-to-doctor triggers (app flags, doesn't diagnose)
Rectal bleeding, fever with GI symptoms, flank pain / blood in urine (stones), chest pain or HR anomalies, joint swelling, or any flare not resolving in days.

---

## 9. Progression rules
- **Running volume:** ≤10%/wk increase; long run +~1 km/wk on build weeks; deload every 4th week.
- **Easy-pace efficiency (the real KPI):** track **pace at HR `{{ thresholds.easy_hr_cap }}`** — as it gets faster at the same HR, aerobic base is improving. This, not weekly mileage, is the headline running metric.
- **Cadence:** +5 spm every 2–3 weeks until `{{ thresholds.cadence_target_spm }}` sustained on easy runs.
- **Quality runs:** alternate threshold ↔ VO₂ weekly; progress by adding 1 rep/interval or extending interval length, not by going harder than the zone.
- **Calisthenics (upper-body muscle):** progressive overload ladder — reps → tempo (slow eccentric) → harder leverage (e.g., incline→full→archer push-ups; band→full→archer→weighted pull-ups) → added load (weighted backpack/vest) → unilateral. Aim for sets taken near failure, 10–20 weekly hard sets per major upper-body movement pattern split across the 2 strength days.
- **Boxing:** keep as-is (class-driven); it's the conditioning + adherence anchor.

## 10. Monthly recompute
Re-derive from the rolling data and update §1/§3/§7 constants:
- Max HR (if a higher peak appears), RHR & HRV 30-day baselines → recompute zones & readiness baselines.
- Body weight trend → recompute TDEE & calorie target.
- VO₂max, pace@`{{ thresholds.easy_hr_cap }}`, pull-up/push-up max reps, weekly easy-ratio actual.
- Sleep 30-day avg → set the month's hard-day budget ceiling.
- Periodic reminder: TSH check (Hashimoto family history) and UC follow-up colonoscopy per gastroenterologist.

## 11. Data contract
*What the app must feed the brain — field list only; define the actual data structures in the app.*

**Profile constants (in `profile.yaml`, set once, refreshed monthly by §10):** age, height, sex, max HR,
RHR baseline, HRV baseline, goal weight, easy-HR cap, cadence target, zones, and the `nutrition` block
(activity factor, deficit %, protein/fat g/kg, carb multipliers, hydration, fiber). *(Current weight is
**not** a constant — it is the live, latest HealthKit `body_mass`.)*

**Daily inputs the app collects/feeds the brain (via `POST /sync`):**
- *From HealthKit (automatic):* sleep hours; morning HRV (SDNN); morning RHR; yesterday's workout (type,
  duration, avg/max HR, minutes per zone); yesterday's active energy; yesterday's steps; **body weight
  (`body_mass`)**; **yesterday's logged nutrition intake — dietary energy, protein, carbs, fat, fiber,
  sodium, water.**
- *Daily check-in (a few taps, objective only):* `giSymptoms` (yes/no — any flare sign, §6.2); `illness`
  (yes/no); knee pain (0–10, 0 = none).
- *No subjective self-report* (energy/soreness/motivation were dropped — readiness is objective, §6.1).

**Weekly aggregates (for the Monday loop):** 7-day & 28-day — sleep avg, HRV avg, RHR avg, total run km,
easy-vs-hard run ratio, sessions by category, strength session count, long-run distance, weight trend,
GI-symptom days, **and nutrition-intake adherence (avg calories & protein vs target, days on/over/under)**.

**Brain outputs:**
- every Monday → a tiered weekly plan (core + optional extras, budgets, rationale) **plus the week's
  nutrition (protein/fat/hydration targets + the carb-cycling day-type pattern + last week's intake
  adherence)**;
- every morning → today's tuned session + alternatives + a skip-OK flag + the day's macro focus (with
  yesterday's intake-vs-target).

---

### One-line summary
Polarize the running (true-easy cap `{{ thresholds.easy_hr_cap }}` + cadence `{{ thresholds.cadence_target_spm }}`), budget 2 hard days/week around boxing,
lock in 2 calisthenics days for upper-body muscle, drive a slow recomp with constant high protein +
carb-cycling — and let sleep, HRV, and gut symptoms gate how hard any given day actually goes.
