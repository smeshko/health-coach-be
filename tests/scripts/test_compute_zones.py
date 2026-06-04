"""TASK-001: %max-HR zone bounds with shared integer edges.

The whole point is structural contiguity: round the six band edges once and pair
adjacent edges, so zN.high IS the same int as z(N+1).low for any max_hr — the
E3·P1 `Zones` validator then passes by construction, not by rounding luck.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPUTE_ZONES_PATH = REPO_ROOT / "scripts" / "compute_zones.py"


def _load():
    spec = importlib.util.spec_from_file_location("compute_zones", COMPUTE_ZONES_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_db_md_example_bounds() -> None:
    compute_zones = _load().compute_zones
    assert compute_zones(192, 58) == {
        "z1": (96, 125),
        "z2": (125, 150),
        "z3": (150, 167),
        "z4": (167, 177),
        "z5": (177, 192),
    }


@pytest.mark.parametrize("max_hr", [170, 185, 192, 200, 210])
def test_contiguous_and_monotonic(max_hr: int) -> None:
    compute_zones = _load().compute_zones
    z = compute_zones(max_hr, 55)
    names = ("z1", "z2", "z3", "z4", "z5")
    # low < high per zone
    for n in names:
        assert z[n][0] < z[n][1], (n, z[n])
    # contiguous: each high == next low (names[1:] is intentionally shorter)
    for cur, nxt in zip(names, names[1:], strict=False):
        assert z[cur][1] == z[nxt][0], (cur, nxt, z)
    # lows strictly increasing
    lows = [z[n][0] for n in names]
    assert lows == sorted(set(lows)), lows
    # band spans 50% -> 100% of max
    assert z["z1"][0] == round(0.50 * max_hr)
    assert z["z5"][1] == max_hr


def test_rhr_does_not_move_cutpoints() -> None:
    compute_zones = _load().compute_zones
    assert compute_zones(190, 45) == compute_zones(190, 70)
