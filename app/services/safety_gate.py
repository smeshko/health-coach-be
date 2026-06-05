"""Deterministic, auto-regulation-only safety gate (E8·P2; CONSTITUTION §6.2).

A **pure** module: evaluate the **six** §6.2 gate reasons from a day's **objective**
check-in flags (``gi_symptoms``, ``illness``, ``knee_pain``) and this-morning
``daily_metrics`` (``sleep_h``; ``rhr`` vs the rolling ``rhr_30d_mean``; ``hrv_sdnn`` vs
the rolling ``hrv_30d_mean``), collect the firing reason keys in a fixed order, and map
the firing set to a single most-restrictive ``overrideTo`` forced card. There is **no**
subjective check-in input, **no** LLM call, and **no** DB read/write (the query that
loads the rows, the router branch, the REST-brief write, and the
``suggestions.safety_gate_tripped`` snapshot are E10/E11). It imports only stdlib + the
shared ``WorkoutCard`` enum — no FastAPI/HTTP/DB session/LLM.

**Auto-regulation only, not a medical layer** (ARCHITECTURE §6.2: "a fitness app, not a
medical device"). The gate encodes **only** the four §6.2 objective thresholds + the
three check-in flags; it makes no diagnosis, reads no medical PDF, and the §6.2 prose
escalation "persistent/bloody → see doctor" / the "or swelling" knee clause are **not**
code (they are LLM/UX context; there is no swelling check-in field — DECISIONS Decision 6).

Baselines are the **rolling** ``daily_metrics`` values (E6·P2), **never** the monthly
zone-derivation anchors — "one rolling baseline, not two competing ones" (DB.md §5 ¹). A
null rolling baseline (sparse/day-one window, E6·P2's documented path) ⇒ **skip** that
spike/crash reason, never a fabricated trip or a divide-by-zero (DECISIONS Decision 5).

Thresholds are **named constants transcribed verbatim from §6.2** (single source) so a
mis-transcription is caught by a per-reason boundary test at the exact §6.2 edge.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.enums import WorkoutCard

# --- The six MODELS machine reason keys (MODELS § SafetyGate), in fixed listing order ---
GI_FLARE = "gi_flare"
SLEEP_BELOW_4H = "sleep_below_4h"
ILLNESS = "illness"
KNEE_PAIN_HIGH = "knee_pain_high"
RHR_SPIKE = "rhr_spike"
HRV_CRASH = "hrv_crash"

#: The closed set of valid §6.2 reason keys — used to reject unknown reasons and fail
#: CLOSED to the most-restrictive override (review #1).
REASON_KEYS: frozenset[str] = frozenset(
    {GI_FLARE, SLEEP_BELOW_4H, ILLNESS, KNEE_PAIN_HIGH, RHR_SPIKE, HRV_CRASH}
)

# --- Pinned thresholds, transcribed verbatim from CONSTITUTION §6.2 (all STRICT) ---
# §6.2 "Sleep <4 h → rest or Z1 active recovery only"  (strict `< 4`)
SLEEP_FLOOR_H = 4.0
# §6.2 "Knee pain >3/10 or swelling → no running/jumping/plyo"  (strict `> 3`; 0 = none)
KNEE_PAIN_FLOOR = 3
# §6.2 "Resting HR >+12 bpm over baseline → treat as red"  (strict `> +12`)
RHR_SPIKE_BPM = 12.0
# §6.2 "HRV crash >40 % → treat as red"  (strict `> 40 %` below the rolling mean)
HRV_CRASH_FRACTION = 0.40


def gi_flare_reason(gi_symptoms: int | None) -> str | None:
    """§6.2 "GI symptoms → no hard training; easy/mobility only".

    Fires (``GI_FLARE``) when ``gi_symptoms == 1`` (the ``checkins`` 0/1 flag, DB.md §3);
    ``0``/``None`` → ``None`` (absence ≠ a flare — DECISIONS Decision 4).
    """
    return GI_FLARE if gi_symptoms == 1 else None


def sleep_below_4h_reason(sleep_h: float | None) -> str | None:
    """§6.2 "Sleep <4 h → rest or Z1 active recovery only".

    Fires (``SLEEP_BELOW_4H``) when ``sleep_h is not None and sleep_h < SLEEP_FLOOR_H``
    (strict ``< 4``). ``None`` sleep (no reading) → ``None`` (absence ≠ 0 h — DECISIONS
    Decision 4). This is the §6.1 "min cap handled by safety gate" floor — the readiness
    score (E8·P1) keeps subtracting per hour; this gate owns the hard <4 h floor.
    """
    return SLEEP_BELOW_4H if sleep_h is not None and sleep_h < SLEEP_FLOOR_H else None


def illness_reason(illness: int | None) -> str | None:
    """§6.2 "Illness / fever → rest".

    Fires (``ILLNESS``) when ``illness == 1`` (the ``checkins`` 0/1 flag, DB.md §3);
    ``0``/``None`` → ``None`` (DECISIONS Decision 4).
    """
    return ILLNESS if illness == 1 else None


def knee_pain_high_reason(knee_pain: int | None) -> str | None:
    """§6.2 "Knee pain >3/10 → no running/jumping/plyo".

    Fires (``KNEE_PAIN_HIGH``) when ``knee_pain is not None and knee_pain >
    KNEE_PAIN_FLOOR`` (strict ``> 3``; ``knee_pain`` is 0–10, **0 = none** — DB.md §3 /
    MODELS DailyCheckin). ``3`` does **not** fire; ``None`` → ``None``. Swelling has no
    check-in field — it is out of scope (auto-regulation only — DECISIONS Decision 6).
    """
    return KNEE_PAIN_HIGH if knee_pain is not None and knee_pain > KNEE_PAIN_FLOOR else None


def rhr_spike_reason(rhr: float | None, rhr_30d_mean: float | None) -> str | None:
    """§6.2 "Resting HR >+12 bpm over baseline → treat as red regardless of score".

    ``delta = rhr - rhr_30d_mean``; fires (``RHR_SPIKE``) when ``delta > RHR_SPIKE_BPM``
    (strict ``>``; **+12 exactly does not trip**). Returns ``None`` when ``rhr`` or
    ``rhr_30d_mean`` is ``None`` (baseline-null ⇒ skip — DECISIONS Decision 5). The
    baseline is the **rolling** ``rhr_30d_mean`` input, **never** the monthly profile
    anchor (DB.md §5 ¹).
    """
    if rhr is None or rhr_30d_mean is None:
        return None
    delta = rhr - rhr_30d_mean
    return RHR_SPIKE if delta > RHR_SPIKE_BPM else None


def hrv_crash_reason(hrv_sdnn: float | None, hrv_30d_mean: float | None) -> str | None:
    """§6.2 "HRV crash >40 % → treat as red regardless of score".

    A crash is a **drop below** the rolling mean: fires (``HRV_CRASH``) when ``hrv_sdnn <
    hrv_30d_mean * (1 - HRV_CRASH_FRACTION)`` — i.e. HRV is more than 40 % **below** the
    rolling mean (strict ``> 40 %``; mean-only — DECISIONS Decision 2). Returns ``None``
    when ``hrv_sdnn`` or ``hrv_30d_mean`` is ``None``, or ``hrv_30d_mean <= 0``
    (degenerate baseline — no divide-by-zero / no fabricated crash; baseline-null ⇒ skip
    — DECISIONS Decision 5). Uses the rolling ``hrv_30d_mean``, **never** the monthly
    profile anchor (DB.md §5 ¹) and **not** the §6.1 ``hrv_30d_sd`` z-score (that is the
    readiness score's HRV term, E8·P1).
    """
    if hrv_sdnn is None or hrv_30d_mean is None or hrv_30d_mean <= 0:
        return None
    crash_threshold = hrv_30d_mean * (1 - HRV_CRASH_FRACTION)
    return HRV_CRASH if hrv_sdnn < crash_threshold else None


def collect_reasons(
    *,
    gi_symptoms: int | None,
    illness: int | None,
    knee_pain: int | None,
    sleep_h: float | None,
    rhr: float | None,
    rhr_30d_mean: float | None,
    hrv_sdnn: float | None,
    hrv_30d_mean: float | None,
) -> list[str]:
    """Collect the firing reason keys in the **fixed MODELS order** (epic §3 ``reasons[]``).

    Calls the six per-reason predicates in the documented order — ``gi_flare``,
    ``sleep_below_4h``, ``illness``, ``knee_pain_high``, ``rhr_spike``, ``hrv_crash`` —
    and concatenates the non-``None`` results, so the list is stable and reproducible and
    every trip is traceable to a named §6.2 reason. Keyword-only so the call site can
    never pair the wrong rolling baseline with a reading.
    """
    candidates = (
        gi_flare_reason(gi_symptoms),
        sleep_below_4h_reason(sleep_h),
        illness_reason(illness),
        knee_pain_high_reason(knee_pain),
        rhr_spike_reason(rhr, rhr_30d_mean),
        hrv_crash_reason(hrv_sdnn, hrv_30d_mean),
    )
    return [reason for reason in candidates if reason is not None]


def override_for(reasons: Sequence[str]) -> WorkoutCard | None:
    """Map the firing reason set to the single most-restrictive forced card (§6.2).

    ``[]`` → ``None`` (not triggered). Otherwise the **most-restrictive-wins** precedence
    ``rest > active_recovery > mobility`` (DECISIONS Decision 7), with each single-reason
    card matching §6.2 verbatim:

    - ``illness`` (§6.2 → rest) or ``sleep_below_4h`` (§6.2 → "rest or Z1 active
      recovery") present ⇒ ``rest`` (the hardest stop — full rest).
    - else ``knee_pain_high`` (§6.2 → no impact) / ``rhr_spike`` / ``hrv_crash`` (§6.2 →
      "treat as red"; §6.1 RED = active-recovery/rest) ⇒ ``active_recovery`` (matches the
      MODELS ``["knee_pain_high"] → "active_recovery"`` example).
    - else ``gi_flare`` (§6.2 → "no hard training; easy/mobility only") ⇒ ``mobility``
      (the least-restrictive of the three forced cards).

    **Fail closed (review #1):** a non-empty ``reasons`` containing only unrecognized keys
    (schema drift, a typo, or a future reason this map hasn't learned) returns the
    **most-restrictive** ``rest`` — never the least-restrictive ``mobility`` — so an
    unknown trigger can never silently downgrade the override. The ``gi_flare`` branch is
    explicit, not a catch-all.
    """
    if not reasons:
        return None
    if ILLNESS in reasons or SLEEP_BELOW_4H in reasons:
        return WorkoutCard.rest
    if KNEE_PAIN_HIGH in reasons or RHR_SPIKE in reasons or HRV_CRASH in reasons:
        return WorkoutCard.active_recovery
    if GI_FLARE in reasons:
        return WorkoutCard.mobility
    return WorkoutCard.rest


@dataclass(frozen=True)
class SafetyGate:
    """The safety-gate result (MODELS ``SafetyGate``).

    Exactly the three MODELS fields — **not** the readiness score result (E8·P1, a
    separate computation) and **no** medical-diagnosis field (auto-regulation only):

    - ``triggered`` — ``bool``; ``True`` iff any reason fired. Must equal ``bool(reasons)``.
    - ``reasons`` — the firing machine reason keys in the fixed §6.2 / MODELS order
      (a subset of ``gi_flare``/``sleep_below_4h``/``illness``/``knee_pain_high``/
      ``rhr_spike``/``hrv_crash``), stored as an **immutable tuple**.
    - ``overrideTo`` — the single most-restrictive forced ``WorkoutCard``
      (``rest``/``active_recovery``/``mobility``), or ``None`` when not triggered. The
      field is named ``overrideTo`` (camelCase) to match the MODELS wire shape exactly,
      so E11 serializes it correctly by construction.

    ``__post_init__`` **enforces** the documented invariants (review #2): ``reasons`` is
    coerced to a tuple (a ``list`` field on a frozen dataclass is still mutable in place),
    and ``triggered``/``overrideTo`` are checked against ``reasons`` so a direct
    construction can never desync the three fields or leave a stale override. Prefer
    ``evaluate_safety_gate`` to build instances; direct construction must be self-consistent.
    """

    triggered: bool
    reasons: tuple[str, ...] = ()
    overrideTo: WorkoutCard | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reasons, tuple):
            object.__setattr__(self, "reasons", tuple(self.reasons))
        unknown = set(self.reasons) - REASON_KEYS
        if unknown:
            raise ValueError(
                f"SafetyGate.reasons contains unknown §6.2 keys {sorted(unknown)!r}; "
                f"valid keys are {sorted(REASON_KEYS)!r} (review #3)"
            )
        if self.triggered != bool(self.reasons):
            raise ValueError(
                f"SafetyGate.triggered ({self.triggered!r}) must equal bool(reasons) "
                f"({bool(self.reasons)!r}) for reasons {self.reasons!r}"
            )
        expected = override_for(self.reasons)
        if self.overrideTo != expected:
            raise ValueError(
                f"SafetyGate.overrideTo ({self.overrideTo!r}) must be {expected!r} for "
                f"reasons {self.reasons!r}"
            )


def evaluate_safety_gate(
    *,
    gi_symptoms: int | None,
    illness: int | None,
    knee_pain: int | None,
    sleep_h: float | None,
    rhr: float | None,
    rhr_30d_mean: float | None,
    hrv_sdnn: float | None,
    hrv_30d_mean: float | None,
) -> SafetyGate:
    """Evaluate the §6.2 safety gate from objective inputs — the single public entry point.

    ``reasons = collect_reasons(...)``; ``triggered = bool(reasons)``;
    ``overrideTo = override_for(reasons)``. The deterministic predicate E11's
    ``SafetyGateRouter`` calls **before** the LLM — any reason ⇒ short-circuit to the
    forced REST/active-recovery card.

    **Keyword-only, objective-only** — there is **no** energy/soreness/motivation or any
    other subjective parameter (MODELS DailyCheckin "no subjective self-report"); the
    keyword-only signature also prevents pairing the wrong rolling baseline with a
    reading. The HRV/RHR baselines are the **rolling** ``daily_metrics`` values (E6·P2);
    a null rolling baseline (sparse/day-one window) skips that spike/crash reason, so a
    day-one athlete still trips on the check-in flags + the <4 h sleep floor. Pure: no DB
    read/write, no LLM, no HTTP (the row query, the router branch, the REST-brief write,
    and the ``suggestions`` snapshot are E10/E11).
    """
    reasons = collect_reasons(
        gi_symptoms=gi_symptoms,
        illness=illness,
        knee_pain=knee_pain,
        sleep_h=sleep_h,
        rhr=rhr,
        rhr_30d_mean=rhr_30d_mean,
        hrv_sdnn=hrv_sdnn,
        hrv_30d_mean=hrv_30d_mean,
    )
    reasons_t = tuple(reasons)
    return SafetyGate(
        triggered=bool(reasons_t),
        reasons=reasons_t,
        overrideTo=override_for(reasons_t),
    )
