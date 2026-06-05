"""E8·P1 readiness tests — pure table-driven unit tests (no session/TestClient/LLM).

Mirrors CONSTITUTION §6.1's worked points (sleep −5/hr below 7, +additional −10 below
5; HRV 1 SD below −15 / >1 SD −25; RHR +5–7 bpm −10 / >+7 −20; yesterday hard −15, −25
if boxing & sleep <6 h), the band edges (green ≥75 · amber 50–74 · red <50), and the
epic §4 / MODELS worked examples + the clamp edges and the day-one sparse-baseline path.
Every input is a plain number — there is no DB row, no HTTP, no LLM here (epic R6).
"""

from __future__ import annotations

from app.core.enums import ReadinessBand
from app.services.readiness import (
    HRV_BELOW_BASELINE,
    RHR_ABOVE_BASELINE,
    SLEEP_BELOW_5H,
    SLEEP_BELOW_7H,
    YESTERDAY_HARD_DAY,
    ReadinessPenalty,
    assemble_score,
    band_for,
    collect_penalties,
    hrv_penalty,
    rhr_penalty,
    sleep_penalty,
    yesterday_hard_penalty,
)

# --- sleep_penalty (§6.1 "−5 per hour below 7 (5 h → −10)"; "<5 h: additional −10") ---


def test_sleep_penalty_at_7h_is_empty() -> None:
    assert sleep_penalty(7.0) == []


def test_sleep_penalty_above_7h_is_empty() -> None:
    assert sleep_penalty(8.0) == []


def test_sleep_penalty_at_5h_stacks_both_factors() -> None:
    # §6.1 worked point: 5 h → −10 (sleep_below_7h) AND an additional −10 (sleep_below_5h)
    assert sleep_penalty(5.0) == [
        ReadinessPenalty(SLEEP_BELOW_7H, -10),
        ReadinessPenalty(SLEEP_BELOW_5H, -10),
    ]


def test_sleep_penalty_at_6_5h_one_entry_pinned_rounding() -> None:
    # DECISIONS Decision 2: round(-5 * (7 - 6.5)) = round(-2.5) = -2 (half-to-even)
    result = sleep_penalty(6.5)
    assert result == [ReadinessPenalty(SLEEP_BELOW_7H, -2)]


def test_sleep_penalty_at_6h_one_entry() -> None:
    # round(-5 * (7 - 6.0)) = -5; not below 5 h, so only one entry
    assert sleep_penalty(6.0) == [ReadinessPenalty(SLEEP_BELOW_7H, -5)]


def test_sleep_penalty_at_5_5h_one_entry() -> None:
    # round(-5 * (7 - 5.5)) = round(-7.5) = -8 (half-to-even); still >= 5 h
    assert sleep_penalty(5.5) == [ReadinessPenalty(SLEEP_BELOW_7H, -8)]


def test_sleep_penalty_at_4_5h_stacks() -> None:
    # round(-5 * (7 - 4.5)) = round(-12.5) = -12 (half-to-even) + additional -10
    assert sleep_penalty(4.5) == [
        ReadinessPenalty(SLEEP_BELOW_7H, -12),
        ReadinessPenalty(SLEEP_BELOW_5H, -10),
    ]


def test_sleep_penalty_none_is_empty() -> None:
    # absence is not a bad value (DECISIONS Decision 4)
    assert sleep_penalty(None) == []


# --- hrv_penalty (z = (mean − reading) / sd over the ROLLING baseline) ---


def test_hrv_penalty_below_1sd_is_none() -> None:
    # z = 0.5 -> none
    assert hrv_penalty(hrv_sdnn=95.0, hrv_30d_mean=100.0, hrv_30d_sd=10.0) is None


def test_hrv_penalty_at_exactly_1sd_is_minus_15() -> None:
    # z == 1.0 -> -15 (boundary belongs to the milder tier; DECISIONS Decision 3)
    assert hrv_penalty(hrv_sdnn=90.0, hrv_30d_mean=100.0, hrv_30d_sd=10.0) == ReadinessPenalty(
        HRV_BELOW_BASELINE, -15
    )


def test_hrv_penalty_at_1_5sd_is_minus_25() -> None:
    # z = 1.5 -> -25 (strictly > 1 SD below)
    assert hrv_penalty(hrv_sdnn=85.0, hrv_30d_mean=100.0, hrv_30d_sd=10.0) == ReadinessPenalty(
        HRV_BELOW_BASELINE, -25
    )


def test_hrv_penalty_at_3sd_is_minus_25() -> None:
    assert hrv_penalty(hrv_sdnn=70.0, hrv_30d_mean=100.0, hrv_30d_sd=10.0) == ReadinessPenalty(
        HRV_BELOW_BASELINE, -25
    )


def test_hrv_penalty_just_past_1sd_is_minus_25() -> None:
    # z = 1.0001 -> -25 (pin the boundary)
    assert hrv_penalty(hrv_sdnn=89.999, hrv_30d_mean=100.0, hrv_30d_sd=10.0) == ReadinessPenalty(
        HRV_BELOW_BASELINE, -25
    )


def test_hrv_penalty_just_under_1sd_is_none() -> None:
    # z = 0.9999 -> none
    assert hrv_penalty(hrv_sdnn=90.001, hrv_30d_mean=100.0, hrv_30d_sd=10.0) is None


def test_hrv_penalty_null_reading_is_none() -> None:
    assert hrv_penalty(hrv_sdnn=None, hrv_30d_mean=100.0, hrv_30d_sd=10.0) is None


def test_hrv_penalty_null_mean_is_none() -> None:
    # day-one sparse baseline (E6·P2) -> skip the term
    assert hrv_penalty(hrv_sdnn=90.0, hrv_30d_mean=None, hrv_30d_sd=10.0) is None


def test_hrv_penalty_null_sd_is_none() -> None:
    assert hrv_penalty(hrv_sdnn=90.0, hrv_30d_mean=100.0, hrv_30d_sd=None) is None


def test_hrv_penalty_nonpositive_sd_is_none() -> None:
    # degenerate window -> no divide-by-zero (DECISIONS Decision 5)
    assert hrv_penalty(hrv_sdnn=90.0, hrv_30d_mean=100.0, hrv_30d_sd=0.0) is None


def test_hrv_penalty_uses_rolling_not_anchor() -> None:
    # A profile-shaped anchor far from the rolling mean must not affect the penalty:
    # the helper has no anchor parameter at all; it compares against the rolling mean.
    # reading 90 vs rolling mean 100, sd 10 -> z == 1 -> -15 regardless of any anchor.
    assert hrv_penalty(hrv_sdnn=90.0, hrv_30d_mean=100.0, hrv_30d_sd=10.0) == ReadinessPenalty(
        HRV_BELOW_BASELINE, -15
    )


# --- rhr_penalty (absolute bpm band off the rolling mean) ---


def test_rhr_penalty_below_band_is_none() -> None:
    # delta = 4 -> none
    assert rhr_penalty(rhr=54.0, rhr_30d_mean=50.0) is None


def test_rhr_penalty_at_band_low_is_minus_10() -> None:
    # delta = 5 -> -10
    assert rhr_penalty(rhr=55.0, rhr_30d_mean=50.0) == ReadinessPenalty(RHR_ABOVE_BASELINE, -10)


def test_rhr_penalty_at_band_high_is_minus_10() -> None:
    # delta = 7 -> -10
    assert rhr_penalty(rhr=57.0, rhr_30d_mean=50.0) == ReadinessPenalty(RHR_ABOVE_BASELINE, -10)


def test_rhr_penalty_above_band_is_minus_20() -> None:
    # delta = 8 -> -20
    assert rhr_penalty(rhr=58.0, rhr_30d_mean=50.0) == ReadinessPenalty(RHR_ABOVE_BASELINE, -20)


def test_rhr_penalty_null_reading_is_none() -> None:
    assert rhr_penalty(rhr=None, rhr_30d_mean=50.0) is None


def test_rhr_penalty_null_mean_is_none() -> None:
    assert rhr_penalty(rhr=55.0, rhr_30d_mean=None) is None


# --- yesterday_hard_penalty (−15; −25 if boxing & sleep <6 h) ---


def test_yesterday_hard_false_is_none() -> None:
    assert (
        yesterday_hard_penalty(False, yesterday_boxing=False, yesterday_sleep_h=8.0) is None
    )


def test_yesterday_hard_true_is_minus_15() -> None:
    assert yesterday_hard_penalty(
        True, yesterday_boxing=False, yesterday_sleep_h=8.0
    ) == ReadinessPenalty(YESTERDAY_HARD_DAY, -15)


def test_yesterday_hard_boxing_low_sleep_is_minus_25_same_key() -> None:
    # boxing AND sleep < 6 h -> -25, SAME factor key (DECISIONS Decision 6)
    penalty = yesterday_hard_penalty(True, yesterday_boxing=True, yesterday_sleep_h=5.0)
    assert penalty == ReadinessPenalty(YESTERDAY_HARD_DAY, -25)
    assert penalty.factor == YESTERDAY_HARD_DAY


def test_yesterday_hard_boxing_adequate_sleep_is_minus_15() -> None:
    # boxing but sleep >= 6 h -> -15
    assert yesterday_hard_penalty(
        True, yesterday_boxing=True, yesterday_sleep_h=6.0
    ) == ReadinessPenalty(YESTERDAY_HARD_DAY, -15)


def test_yesterday_hard_nonboxing_low_sleep_is_minus_15() -> None:
    # not boxing, even with low sleep -> -15 (variant needs BOTH conditions)
    assert yesterday_hard_penalty(
        True, yesterday_boxing=False, yesterday_sleep_h=5.0
    ) == ReadinessPenalty(YESTERDAY_HARD_DAY, -15)


def test_yesterday_hard_boxing_null_sleep_is_minus_15() -> None:
    assert yesterday_hard_penalty(
        True, yesterday_boxing=True, yesterday_sleep_h=None
    ) == ReadinessPenalty(YESTERDAY_HARD_DAY, -15)


# --- collect_penalties (fixed MODELS order) ---


def test_collect_penalties_fixed_order_and_negative() -> None:
    penalties = collect_penalties(
        sleep_h=4.5,  # sleep_below_7h + sleep_below_5h
        hrv_sdnn=85.0,
        hrv_30d_mean=100.0,
        hrv_30d_sd=10.0,  # hrv_below_baseline (z=1.5 -> -25)
        rhr=58.0,
        rhr_30d_mean=50.0,  # rhr_above_baseline (delta=8 -> -20)
        yesterday_hard_day=True,
        yesterday_boxing=False,
        yesterday_sleep_h=8.0,  # yesterday_hard_day -15
    )
    assert [p.factor for p in penalties] == [
        SLEEP_BELOW_7H,
        SLEEP_BELOW_5H,
        HRV_BELOW_BASELINE,
        RHR_ABOVE_BASELINE,
        YESTERDAY_HARD_DAY,
    ]
    assert all(p.points < 0 for p in penalties)


def test_collect_penalties_skips_non_firing() -> None:
    penalties = collect_penalties(
        sleep_h=8.0,
        hrv_sdnn=110.0,
        hrv_30d_mean=100.0,
        hrv_30d_sd=10.0,
        rhr=48.0,
        rhr_30d_mean=50.0,
        yesterday_hard_day=False,
        yesterday_boxing=False,
        yesterday_sleep_h=8.0,
    )
    assert penalties == []


# --- assemble_score (100 − Σpoints, clamped [0,100] as the LAST step) ---


def test_assemble_score_no_penalties_is_100() -> None:
    assert assemble_score([]) == 100


def test_assemble_score_single_penalty() -> None:
    assert assemble_score([ReadinessPenalty("x", -10)]) == 90


def test_assemble_score_clamps_at_100() -> None:
    # No input can exceed 100 (MODELS ceiling); the empty list is the maximum.
    assert assemble_score([]) == 100


def test_assemble_score_clamps_at_0() -> None:
    # Stack summing below −100 → clamped to 0, never negative.
    stack = [
        ReadinessPenalty("a", -25),
        ReadinessPenalty("b", -25),
        ReadinessPenalty("c", -25),
        ReadinessPenalty("d", -25),
        ReadinessPenalty("e", -10),
    ]  # raw = 100 − 110 = −10 → clamped 0
    assert assemble_score(stack) == 0


def test_assemble_score_returns_int() -> None:
    for penalties in ([], [ReadinessPenalty("x", -10)], [ReadinessPenalty("y", -200)]):
        assert isinstance(assemble_score(penalties), int)


# --- band_for (green ≥75 · amber 50–74 · red <50, inclusive lower edges) ---


def test_band_for_100_is_green() -> None:
    assert band_for(100) == ReadinessBand.green


def test_band_for_75_is_green() -> None:
    assert band_for(75) == ReadinessBand.green


def test_band_for_74_is_amber() -> None:
    assert band_for(74) == ReadinessBand.amber


def test_band_for_50_is_amber() -> None:
    assert band_for(50) == ReadinessBand.amber


def test_band_for_49_is_red() -> None:
    assert band_for(49) == ReadinessBand.red


def test_band_for_0_is_red() -> None:
    assert band_for(0) == ReadinessBand.red


def test_band_values_are_lowercase() -> None:
    # MODELS lowercase wire values (DECISIONS Decision 7); DB UPPERCASE is E11's concern.
    assert ReadinessBand.green.value == "green"
    assert ReadinessBand.amber.value == "amber"
    assert ReadinessBand.red.value == "red"
