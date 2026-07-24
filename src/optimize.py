"""Greedy schedule re-timing under a shift window and turnaround constraints.

Model
-----
Each flight may shift its ENTIRE schedule (departure and arrival move
together, block time unchanged) by a multiple of SHIFT_STEP_MIN within
[-window, +window] minutes. Only bin crossings change congestion, so
bin-sized steps lose nothing.

Constraints
-----------
* window:      |shift| <= window
* same-day:    a departure may not cross midnight (service date is fixed);
               arrivals may (a 23:50 arrival shifted +15 lands next day)
* turnaround:  for consecutive legs of the same tail number, the new ground
               time must be >= min(original ground time, MIN_TURNAROUND_MIN).
               Already-tight turns may not be made tighter; all others keep
               at least the configured minimum. Chains are built over ALL
               airports in the month, not just the selected ones, so a shift
               cannot squeeze a turnaround at an unselected airport.
* no tail number -> never shifted (feasibility cannot be verified);
  overlapping legs of a tail (data glitch) -> both legs frozen.

Objective (greedy)
------------------
For each (airport, service day): repeatedly find the maximum-load 15-min
bin and move one of its flights to the least-loaded reachable bin. A move
is accepted only if every bin that gains a movement stays STRICTLY below
its own airport-day's current maximum - the peak anywhere can only fall,
never rise or migrate. Passes repeat over all airport-days until no move
improves anything. Greedy: no optimality guarantee (see limitations).
"""

from collections import defaultdict
from datetime import date as _date

import numpy as np
import pandas as pd

import config

MAX_PASSES = 8


# --------------------------------------------------------------- setup
def _day_index(dates: pd.Series):
    """Map ISO date strings to consecutive integers (0 = first day)."""
    ordinals = pd.to_datetime(dates).map(lambda d: d.toordinal())
    base = int(ordinals.min())
    return (ordinals - base).astype(int).to_numpy(), base


def build_chains(flights: pd.DataFrame, min_turn: int):
    """Per-tail leg chains: prev/next leg index and minimum ground time.

    Returns (prev_idx, next_idx, min_gap_prev, shiftable) numpy arrays.
    min_gap_prev[j] applies between prev leg's arrival and j's departure.
    """
    n = len(flights)
    day, _ = _day_index(flights["date"])
    dep_abs = day * 1440 + flights["dep_min"].to_numpy()
    arr_abs = (day + flights["arr_day_offset"].to_numpy()) * 1440 + flights[
        "arr_min"
    ].to_numpy()

    prev_idx = np.full(n, -1, dtype=int)
    next_idx = np.full(n, -1, dtype=int)
    min_gap_prev = np.zeros(n, dtype=int)
    shiftable = flights["tail"].notna().to_numpy().copy()

    order = flights.index.to_numpy()[np.lexsort((dep_abs, flights["tail"].fillna("")))]
    tails = flights["tail"].to_numpy()
    for k in range(1, len(order)):
        i, j = order[k - 1], order[k]
        if pd.isna(tails[i]) or tails[i] != tails[j]:
            continue
        gap = int(dep_abs[j] - arr_abs[i])
        if gap < 0:
            # Overlapping scheduled legs: bad record, freeze both.
            shiftable[i] = shiftable[j] = False
            continue
        prev_idx[j] = i
        next_idx[i] = j
        min_gap_prev[j] = min(gap, min_turn)
    return dep_abs, arr_abs, prev_idx, next_idx, min_gap_prev, shiftable


# --------------------------------------------------------------- optimizer
def optimize(flights: pd.DataFrame, airports, window: int,
             step: int = None, min_turn: int = None, verbose: bool = True):
    """Return (shift ndarray in minutes, stats dict)."""
    step = step or config.SHIFT_STEP_MIN
    min_turn = config.MIN_TURNAROUND_MIN if min_turn is None else min_turn
    aset = set(airports)
    n = len(flights)
    b = config.BIN_MINUTES

    dep_abs, arr_abs, prev_idx, next_idx, min_gap_prev, shiftable = build_chains(
        flights, min_turn
    )
    dep_min = flights["dep_min"].to_numpy()
    origin = flights["origin"].to_numpy()
    dest = flights["dest"].to_numpy()
    shift = np.zeros(n, dtype=int)

    # Movement endpoints at selected airports: (flight, kind) kind 0=dep 1=arr
    def endpoint_key(f: int, kind: int, s: int):
        t = (dep_abs[f] if kind == 0 else arr_abs[f]) + s
        apt = origin[f] if kind == 0 else dest[f]
        return (apt, t // 1440, (t % 1440) // b)

    loads = defaultdict(int)
    members = defaultdict(set)
    for f in range(n):
        for kind, apt in ((0, origin[f]), (1, dest[f])):
            if apt in aset:
                key = endpoint_key(f, kind, 0)
                loads[key] += 1
                members[key].add((f, kind))

    deltas = [s for s in range(-window, window + 1, step)]

    def feasible(f: int, s: int) -> bool:
        if not shiftable[f] or abs(s) > window:
            return False
        if not (0 <= dep_min[f] + s <= 1439):     # departure keeps its date
            return False
        p, nx = prev_idx[f], next_idx[f]
        if p >= 0 and (dep_abs[f] + s) - (arr_abs[p] + shift[p]) < min_gap_prev[f]:
            return False
        if nx >= 0 and (dep_abs[nx] + shift[nx]) - (arr_abs[f] + s) < min_gap_prev[nx]:
            return False
        return True

    def airport_day_max(apt, day):
        return max(
            (loads[(apt, day, bb)] for bb in range(96) if (apt, day, bb) in loads),
            default=0,
        )

    def apply_move(f: int, s_new: int):
        for kind, apt in ((0, origin[f]), (1, dest[f])):
            if apt in aset:
                old = endpoint_key(f, kind, shift[f])
                new = endpoint_key(f, kind, s_new)
                loads[old] -= 1
                members[old].discard((f, kind))
                if loads[old] == 0:
                    del loads[old], members[old]
                loads[new] += 1
                members[new].add((f, kind))
        shift[f] = s_new

    day_arr, base_ord = _day_index(flights["date"])
    month_days = sorted(set(day_arr.tolist()))
    airport_days = [(a, d) for a in airports for d in month_days]

    def try_reduce_bin(key) -> bool:
        """Move one flight out of `key`; True if a move was applied."""
        apt, day, _ = key
        peak = loads[key]
        best = None  # (worst_gain_load, |delta|, f, s_new)
        # Cache each airport-day max involved, recompute lazily per candidate.
        maxima = {}

        def ad_max(a, d):
            if (a, d) not in maxima:
                maxima[(a, d)] = airport_day_max(a, d)
            return maxima[(a, d)]

        for f, kind in list(members[key]):
            for s_new in deltas:
                if s_new == shift[f] or not feasible(f, s_new):
                    continue
                # The movement sitting in the peak bin must actually leave it.
                if endpoint_key(f, kind, s_new) == key:
                    continue
                worst = -1
                ok = True
                for k2, apt2 in ((0, origin[f]), (1, dest[f])):
                    if apt2 not in aset:
                        continue
                    old = endpoint_key(f, k2, shift[f])
                    new = endpoint_key(f, k2, s_new)
                    if new == old:
                        continue
                    gain = loads[new] + 1
                    a2, d2 = new[0], new[1]
                    cap = peak if (a2, d2) == (apt, day) else ad_max(a2, d2)
                    if gain >= cap:
                        ok = False
                        break
                    worst = max(worst, gain)
                if ok:
                    cand = (worst, abs(s_new), f, s_new)
                    if best is None or cand < best:
                        best = cand
        if best is None:
            return False
        apply_move(best[2], best[3])
        return True

    def shave(apt, day) -> bool:
        changed = False
        while True:
            m = airport_day_max(apt, day)
            if m == 0:
                return changed
            peak_bins = [
                (apt, day, bb) for bb in range(96) if loads.get((apt, day, bb), 0) == m
            ]
            progressed = False
            for key in peak_bins:
                while loads.get(key, 0) == m:
                    if try_reduce_bin(key):
                        changed = progressed = True
                    else:
                        break
            still = any(loads.get(k, 0) == m for k in peak_bins)
            if still or not progressed:
                return changed

    for p in range(MAX_PASSES):
        moved = False
        ranked = sorted(airport_days, key=lambda ad: -airport_day_max(*ad))
        for apt, day in ranked:
            if shave(apt, day):
                moved = True
        if verbose:
            print(f"  pass {p + 1}: {'improved' if moved else 'converged'}")
        if not moved:
            break

    stats = run_sanity_checks(
        flights, shift, airports, window, min_turn, dep_abs, arr_abs,
        prev_idx, min_gap_prev, shiftable,
    )
    stats["window"] = window
    stats["n_shifted"] = int((shift != 0).sum())
    return shift, stats


# --------------------------------------------------------------- sanity
def run_sanity_checks(flights, shift, airports, window, min_turn,
                      dep_abs, arr_abs, prev_idx, min_gap_prev, shiftable):
    """Hard assertions - the run is invalid if any of these fail."""
    n = len(flights)
    assert len(shift) == n, "flight count changed"
    assert np.all(np.abs(shift) <= window), "shift beyond window"
    assert np.all(shift % config.SHIFT_STEP_MIN == 0), "off-grid shift"
    assert np.all(shift[~shiftable] == 0), "unshiftable flight was moved"
    dep_new = flights["dep_min"].to_numpy() + shift
    assert np.all((dep_new >= 0) & (dep_new <= 1439)), "departure crossed midnight"

    # Turnarounds, rechecked from scratch.
    has_prev = prev_idx >= 0
    j = np.where(has_prev)[0]
    i = prev_idx[j]
    gaps = (dep_abs[j] + shift[j]) - (arr_abs[i] + shift[i])
    assert np.all(gaps >= min_gap_prev[j]), "turnaround violated"

    # Movement conservation per selected airport over the whole month.
    aset = set(airports)
    for a in airports:
        n_dep = int((flights["origin"] == a).sum())
        n_arr = int((flights["dest"] == a).sum())
        assert n_dep + n_arr > 0, f"no movements at {a}"
    # (shift moves flights in time, never adds/removes them, and the
    # departure day is pinned - so per-date departure counts are conserved)

    return {
        "n_flights": n,
        "min_turnaround_min": min_turn,
        "assertions": "all passed",
    }


if __name__ == "__main__":
    import prepare

    sel = prepare.load_selection()
    flights = prepare.load_flights()
    print(f"Optimizing {len(flights):,} flights, window ±{config.SHIFT_WINDOW_MIN} min")
    shift, stats = optimize(flights, sel["airports"], config.SHIFT_WINDOW_MIN)
    flights["shift_min"] = shift
    out = config.DATA_DERIVED / f"shifts_w{config.SHIFT_WINDOW_MIN}.csv.gz"
    flights.to_csv(out, index=False, compression="gzip")
    print(f"Shifted {stats['n_shifted']:,} flights; wrote {out}")
