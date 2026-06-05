"""Deterministic, objective-only readiness score (E8·P1; CONSTITUTION §6.1).

A **pure** module: start at 100, subtract the five itemised §6.1 penalties, clamp to
``[0, 100]``, and band the result (``green`` ≥75 · ``amber`` 50–74 · ``red`` <50). It
takes already-resolved **objective** physiological inputs — last night's ``sleep_h``;
``hrv_sdnn`` against the rolling ``hrv_30d_mean``/``hrv_30d_sd``; ``rhr`` against the
rolling ``rhr_30d_mean``; and **yesterday's** ``hard_day``/boxing load — and returns a
``Readiness`` value object. There is **no** subjective check-in input, **no** LLM call,
and **no** DB read/write (the query that loads the ``daily_metrics`` rows and the
write-back of ``readiness_score``/``band`` are E10/E11). It imports only stdlib + the
shared ``ReadinessBand`` enum — no FastAPI/HTTP/DB session/LLM.

Baselines are the **rolling** ``daily_metrics`` values (E6·P2), **never** the monthly
zone-derivation anchors — "one rolling baseline, not two competing ones" (DB.md §5 ¹).
A null rolling baseline (sparse/day-one window, E6·P2's documented path) ⇒ **skip** that
HRV/RHR term, never a fabricated 0 or a crash.

Penalty magnitudes are **named constants transcribed verbatim from §6.1** (single
source) so a mis-transcription is caught by a per-factor test at the §6.1 worked point.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import ReadinessBand

# --- The five MODELS `factor` keys (MODELS § Readiness / ReadinessPenalty) ---
SLEEP_BELOW_7H = "sleep_below_7h"
SLEEP_BELOW_5H = "sleep_below_5h"
HRV_BELOW_BASELINE = "hrv_below_baseline"
RHR_ABOVE_BASELINE = "rhr_above_baseline"
YESTERDAY_HARD_DAY = "yesterday_hard_day"

# --- Pinned penalty magnitudes, transcribed verbatim from CONSTITUTION §6.1 ---
# §6.1 "Sleep last night <7 h: −5 per hour below 7 (so 5 h → −10)"
SLEEP_PER_HOUR_BELOW_7 = -5
# §6.1 "Sleep <5 h: additional −10"
SLEEP_BELOW_5H_POINTS = -10
# §6.1 "Morning HRV vs baseline: 1 SD below → −15 · (>1 SD below → −25)"
HRV_1SD_POINTS = -15
HRV_OVER_1SD_POINTS = -25
# §6.1 "Morning RHR vs baseline: +5–7 bpm → −10 · (>+7 bpm → −20)"
RHR_BAND_POINTS = -10
RHR_OVER_BAND_POINTS = -20
# §6.1 "Yesterday was a hard/quality day: −15 (−25 if boxing and sleep <6 h)"
HARD_DAY_POINTS = -15
HARD_DAY_BOXING_LOW_SLEEP_POINTS = -25

# --- Pinned thresholds (§6.1) ---
SLEEP_FULL_H = 7  # below this, the per-hour sleep penalty applies
SLEEP_DEEP_H = 5  # below this, the additional −10 stacks
HARD_DAY_LOW_SLEEP_H = 6  # boxing & sleep below this → the −25 variant
RHR_BAND_LOW = 5  # +5 bpm: band floor
RHR_BAND_HIGH = 7  # +7 bpm: band ceiling (above → the −20 tier)
HRV_SD_THRESHOLD = 1.0  # 1 SD below the rolling mean

# --- Band thresholds (§6.1 / MODELS): green ≥75 · amber 50–74 · red <50 ---
GREEN_MIN = 75
AMBER_MIN = 50


@dataclass(frozen=True)
class ReadinessPenalty:
    """One itemised readiness penalty (MODELS ``ReadinessPenalty``).

    ``factor`` is one of the five pinned keys above; ``points`` is always **negative**.
    """

    factor: str
    points: int


def sleep_penalty(sleep_h: float | None) -> list[ReadinessPenalty]:
    """Sleep penalties (§6.1) — −5 per hour below 7, plus an additional −10 below 5.

    Returns 0, 1, or 2 entries (the two are **separate stacked** factors, not a
    replacement). ``None`` sleep (no reading) → ``[]`` (absence ≠ 0 h; the <4 h floor is
    the safety gate's, E8·P2 — DECISIONS Decision 4).
    """
    if sleep_h is None or sleep_h >= SLEEP_FULL_H:
        return []
    penalties = [
        # DECISIONS Decision 2: linear −5 × deficit, rounded to nearest int at emit.
        ReadinessPenalty(
            SLEEP_BELOW_7H, round(SLEEP_PER_HOUR_BELOW_7 * (SLEEP_FULL_H - sleep_h))
        )
    ]
    # §6.1 "Sleep <5 h: additional −10" is **strict** (`<5`): at exactly 5.0 h only the
    # `<7 h` per-hour penalty applies (the §6.1 "5 h → −10" worked row is that per-hour
    # term alone), and the deep-sleep −10 stacks only **below** 5 h (review #2 — the plan's
    # `<=5` over-penalized exactly-5.0 h, shifting band edges).
    if sleep_h < SLEEP_DEEP_H:
        penalties.append(ReadinessPenalty(SLEEP_BELOW_5H, SLEEP_BELOW_5H_POINTS))
    return penalties


def hrv_penalty(
    hrv_sdnn: float | None,
    hrv_30d_mean: float | None,
    hrv_30d_sd: float | None,
) -> ReadinessPenalty | None:
    """HRV penalty vs the **rolling** baseline (§6.1) — 1 SD below → −15, >1 SD → −25.

    ``z = (hrv_30d_mean − hrv_sdnn) / hrv_30d_sd`` (SDs below the rolling mean). The 1-SD
    boundary belongs to the milder tier: ``z == 1`` → −15, ``z > 1`` → −25, ``z < 1`` →
    ``None`` (DECISIONS Decision 3). Returns ``None`` when any input is ``None`` or
    ``hrv_30d_sd <= 0`` (skip the term — DECISIONS Decision 5; no divide-by-zero).
    """
    if hrv_sdnn is None or hrv_30d_mean is None or hrv_30d_sd is None or hrv_30d_sd <= 0:
        return None
    z = (hrv_30d_mean - hrv_sdnn) / hrv_30d_sd
    if z > HRV_SD_THRESHOLD:
        return ReadinessPenalty(HRV_BELOW_BASELINE, HRV_OVER_1SD_POINTS)
    if z >= HRV_SD_THRESHOLD:  # z == 1.0 exactly
        return ReadinessPenalty(HRV_BELOW_BASELINE, HRV_1SD_POINTS)
    return None


def rhr_penalty(
    rhr: float | None,
    rhr_30d_mean: float | None,
) -> ReadinessPenalty | None:
    """RHR penalty vs the **rolling** mean (§6.1) — +5–7 bpm → −10, >+7 bpm → −20.

    An **absolute bpm band** (no SD — DB.md §2 has only ``rhr_30d_mean``).
    ``delta = rhr − rhr_30d_mean``: ``5 <= delta <= 7`` → −10; ``delta > 7`` → −20;
    ``delta < 5`` → ``None``. Returns ``None`` when either input is ``None``
    (skip — DECISIONS Decision 5).
    """
    if rhr is None or rhr_30d_mean is None:
        return None
    delta = rhr - rhr_30d_mean
    if delta > RHR_BAND_HIGH:
        return ReadinessPenalty(RHR_ABOVE_BASELINE, RHR_OVER_BAND_POINTS)
    if delta >= RHR_BAND_LOW:
        return ReadinessPenalty(RHR_ABOVE_BASELINE, RHR_BAND_POINTS)
    return None


def yesterday_hard_penalty(
    yesterday_hard_day: bool,
    *,
    yesterday_boxing: bool,
    sleep_h: float | None,
) -> ReadinessPenalty | None:
    """Yesterday-hard penalty (§6.1) — −15, or −25 if it was boxing **and** sleep <6 h.

    ``yesterday_hard_day`` false → ``None``. The −25 case is a **magnitude variant of the
    same** ``yesterday_hard_day`` factor, not a sixth key (DECISIONS Decision 6). The
    "sleep <6 h" clause reads **last night's** ``sleep_h`` — the only sleep readiness takes
    (§6.1 input is "last night's sleep"; there is no "yesterday's sleep" signal) — so the
    −25 fires when yesterday was boxing **and** the athlete under-recovered last night
    (review #1 — the plan keyed this on a fabricated ``yesterday_sleep_h``).
    """
    if not yesterday_hard_day:
        return None
    if yesterday_boxing and sleep_h is not None and sleep_h < HARD_DAY_LOW_SLEEP_H:
        return ReadinessPenalty(YESTERDAY_HARD_DAY, HARD_DAY_BOXING_LOW_SLEEP_POINTS)
    return ReadinessPenalty(YESTERDAY_HARD_DAY, HARD_DAY_POINTS)


def collect_penalties(
    *,
    sleep_h: float | None,
    hrv_sdnn: float | None,
    hrv_30d_mean: float | None,
    hrv_30d_sd: float | None,
    rhr: float | None,
    rhr_30d_mean: float | None,
    yesterday_hard_day: bool,
    yesterday_boxing: bool = False,
) -> list[ReadinessPenalty]:
    """Itemise the firing penalties in the **fixed MODELS order** (epic §3/§4).

    Calls the per-factor helpers in order — ``sleep_below_7h``, ``sleep_below_5h``,
    ``hrv_below_baseline``, ``rhr_above_baseline``, ``yesterday_hard_day`` — and
    concatenates the non-``None`` results, so the list is stable and reproducible and the
    score is exactly ``100 + Σ points`` of this list. The boxing −25 escalation reads the
    same last-night ``sleep_h`` (review #1).
    """
    penalties: list[ReadinessPenalty] = []
    penalties.extend(sleep_penalty(sleep_h))
    if (hrv := hrv_penalty(hrv_sdnn, hrv_30d_mean, hrv_30d_sd)) is not None:
        penalties.append(hrv)
    if (rhr_p := rhr_penalty(rhr, rhr_30d_mean)) is not None:
        penalties.append(rhr_p)
    if (
        hard := yesterday_hard_penalty(
            yesterday_hard_day,
            yesterday_boxing=yesterday_boxing,
            sleep_h=sleep_h,
        )
    ) is not None:
        penalties.append(hard)
    return penalties


def assemble_score(penalties: list[ReadinessPenalty]) -> int:
    """Start at 100, sum the (negative) points, then **clamp to [0, 100]** (§6.1).

    The clamp is the **single last step** applied to the summed score — never per-penalty
    and never before summation (MODELS "starts at 100, subtract penalties, clamp to
    [0,100]"). Returns an ``int`` (MODELS ``score`` is ``integer 0–100``).
    """
    raw = 100 + sum(p.points for p in penalties)
    return max(0, min(100, raw))


def band_for(score: int) -> ReadinessBand:
    """Map the **clamped** score to its band (§6.1 / MODELS).

    Inclusive lower edges: ``score >= 75`` → ``green``; ``50 <= score < 75`` → ``amber``;
    ``score < 50`` → ``red``. Returns the lowercase MODELS ``ReadinessBand`` (the DB's
    UPPERCASE persistence is E11's concern — DECISIONS Decision 7).
    """
    if score >= GREEN_MIN:
        return ReadinessBand.green
    if score >= AMBER_MIN:
        return ReadinessBand.amber
    return ReadinessBand.red


@dataclass(frozen=True)
class Readiness:
    """The readiness result (MODELS ``Readiness``).

    ``score`` is the clamped ``int`` 0–100; ``band`` is the lowercase
    ``ReadinessBand``; ``penalties`` is the itemised, fixed-order list of the firing
    ``ReadinessPenalty`` entries (``score == 100 + Σ points`` before clamping).
    """

    score: int
    band: ReadinessBand
    penalties: list[ReadinessPenalty]


def compute_readiness(
    *,
    sleep_h: float | None,
    hrv_sdnn: float | None,
    hrv_30d_mean: float | None,
    hrv_30d_sd: float | None,
    rhr: float | None,
    rhr_30d_mean: float | None,
    yesterday_hard_day: bool,
    yesterday_boxing: bool = False,
) -> Readiness:
    """Compute the objective-only readiness score, band, and itemised penalties (§6.1).

    The single public entry point E10/E11 call. Start at 100, subtract the five itemised
    §6.1 penalties, clamp to ``[0, 100]``, and band the result. **Keyword-only,
    objective-only** — there is **no** energy/soreness/motivation/subjective parameter
    (MODELS; CONSTITUTION §6.1); the keyword-only signature also prevents pairing the
    wrong rolling baseline with a reading.

    ``sleep_h`` is **last night's** sleep — the only sleep §6.1 reads (it drives both the
    sleep penalties and the boxing −25 escalation). The HRV/RHR baselines are the
    **rolling** ``daily_metrics`` values (E6·P2); a null rolling baseline (sparse/day-one
    window) skips that term. ``yesterday_hard_day``/``yesterday_boxing`` are **yesterday's
    load** flags — the E11 loader passes the prior day's row. Pure: no DB read/write, no
    LLM, no HTTP (E10/E11 own the load + write-back).
    """
    penalties = collect_penalties(
        sleep_h=sleep_h,
        hrv_sdnn=hrv_sdnn,
        hrv_30d_mean=hrv_30d_mean,
        hrv_30d_sd=hrv_30d_sd,
        rhr=rhr,
        rhr_30d_mean=rhr_30d_mean,
        yesterday_hard_day=yesterday_hard_day,
        yesterday_boxing=yesterday_boxing,
    )
    score = assemble_score(penalties)
    return Readiness(score=score, band=band_for(score), penalties=penalties)
