# TASK-001: compute_zones from maxHR and RHR

Depends on: None
Suggested commit: `feat(scripts): add compute_zones (%max-HR Z1–Z5 bpm bounds)`

## Goal

A pure, I/O-free `compute_zones(max_hr, rhr)` that returns the Z1–Z5 bpm bounds as **%max-HR** bands with
**shared integer edges**, so the result is contiguous + monotonic by construction and passes the E3·P1
`Zones` validator for any `max_hr`.

## Files

- `scripts/compute_zones.py` — **new**:
  - `ZONE_EDGES: tuple[float, ...] = (0.50, 0.65, 0.78, 0.87, 0.92, 1.00)` — the six %max band edges
    (constitution §3: Z1 50–65%, Z2 65–78%, Z3 78–87%, Z4 87–92%, Z5 92–100%).
  - `compute_zones(max_hr: int, rhr: int) -> dict[str, tuple[int, int]]`:
    - `edges = [round(pct * max_hr) for pct in ZONE_EDGES]` → six **shared** integer edges `e0..e5`.
    - return `{"z1": (edges[0], edges[1]), "z2": (edges[1], edges[2]), "z3": (edges[2], edges[3]),
      "z4": (edges[3], edges[4]), "z5": (edges[4], edges[5])}` — adjacent zones reuse the same edge int.
    - `rhr` is accepted (the §5 `zones` is conceptually a max/RHR pair; RecomputeConstants re-derives from
      both) but does **not** move the %max cutpoints (see PLAN Decisions / RESEARCH Uncertainty). Keep it a
      named param, unused in the cutpoint math.
- `tests/scripts/test_compute_zones.py` — **new**: the §5-exact case + the contiguity/monotonicity invariants.

## Acceptance

- [ ] `compute_zones(192, 58) == {"z1": (96,125), "z2": (125,150), "z3": (150,167), "z4": (167,177),
      "z5": (177,192)}` — the DB.md §5 example verbatim.
- [ ] For a range of `max_hr` (e.g. 170, 185, 200, 210): every `zN.high == z(N+1).low` (contiguous), each
      `low < high`, and the lows are strictly increasing (monotonic) — i.e. the result satisfies the E3·P1
      `Zones` validator's invariants.
- [ ] `z1.low == round(0.50 * max_hr)` and `z5.high == max_hr` (the band spans 50%→100% of max).
- [ ] Changing `rhr` does not change the returned bounds (rhr is not in the cutpoint math).

## Steps

### RED
- [ ] `tests/scripts/test_compute_zones.py`: assert the `compute_zones(192, 58)` equality against the §5
      dict; a parametrized test over several `max_hr` asserting `zN.high == z(N+1).low`, `low < high`, lows
      strictly increasing, `z5.high == max_hr`; a test that two different `rhr` values give identical output.

### GREEN
- [ ] Implement `compute_zones` with the single shared-edges rounding (the smallest code that passes).

### REFACTOR
- [ ] Keep it a pure function (no DB, no I/O); module-level `ZONE_EDGES`; type hints; a one-line docstring
      citing constitution §3 + DB.md §5.

## Notes

The contiguity guarantee is the whole point: round the **six edges once** and pair adjacent edges
(`z1=(e0,e1) … z5=(e4,e5)`) so `zN.high` *is* the same int as `z(N+1).low` — never round a zone's low and
high independently (that can produce `z1.high=124, z2.low=125` and the E3·P1 contiguity validator would
reject it). Verified at `max_hr=192`: `round(.50·192)=96, round(.65·192)=125, round(.78·192)=150,
round(.87·192)=167, round(.92·192)=177, round(1.0·192)=192` → exactly DB.md §5.
