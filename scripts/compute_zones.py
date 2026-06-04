"""HR-zone bpm bounds derived as % of max HR (constitution §3; DB.md §5 `zones`).

Zones are anchored to **% of max HR** (constitution §3 "primary anchor = % of max
HR"), not Karvonen/HR-reserve — the DB.md §5 example `[96,125]…[177,192]` is exactly
`round(pct·192)` for the band edges, which HR-reserve math would not reproduce.

Contiguity is structural, not luck: the six band edges are rounded **once** to
shared integers `e0..e5`, then paired `z1=(e0,e1) … z5=(e4,e5)`, so `zN.high` IS
the same integer as `z(N+1).low` for any `max_hr`. The E3·P1 `Zones` validator
(monotonic + contiguous, `z5.high == max_hr`) therefore passes by construction.
"""

from __future__ import annotations

# Z1 50–65%, Z2 65–78%, Z3 78–87%, Z4 87–92%, Z5 92–100% of max HR (constitution §3).
ZONE_EDGES: tuple[float, ...] = (0.50, 0.65, 0.78, 0.87, 0.92, 1.00)


def compute_zones(max_hr: int, rhr: int) -> dict[str, tuple[int, int]]:
    """Return the Z1–Z5 bpm bounds as `{"z1": (lo, hi), …}`.

    `rhr` is accepted because the DB.md §5 `zones` block is conceptually a max/RHR
    pair (and the monthly RecomputeConstants re-derives from both), but it does
    not move the %max cutpoints in the §5-faithful derivation.
    """
    edges = [round(pct * max_hr) for pct in ZONE_EDGES]
    return {
        "z1": (edges[0], edges[1]),
        "z2": (edges[1], edges[2]),
        "z3": (edges[2], edges[3]),
        "z4": (edges[3], edges[4]),
        "z5": (edges[4], edges[5]),
    }
