"""Post-run sanity checks. Run AFTER `python src/metrics.py`:

    python -m pytest tests/ -q      (or: python tests/test_sanity.py)

These re-verify every claim the optimizer makes about its own output,
recomputed from the saved artifacts rather than trusting in-memory state.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config  # noqa: E402
import prepare  # noqa: E402
from optimize import build_chains  # noqa: E402

W = config.SHIFT_WINDOW_MIN


def _load():
    sel = prepare.load_selection()
    flights = prepare.load_flights()
    shifted = pd.read_csv(
        config.DATA_DERIVED / f"shifts_w{W}.csv.gz", dtype={"flight_num": str}
    )
    return sel, flights, shifted


def test_flight_count_unchanged():
    _, flights, shifted = _load()
    assert len(shifted) == len(flights), "flight count changed"


def test_no_shift_beyond_window():
    _, _, shifted = _load()
    s = shifted["shift_min"].to_numpy()
    assert np.all(np.abs(s) <= W), "a flight moved beyond its window"
    assert np.all(s % config.SHIFT_STEP_MIN == 0), "off-grid shift"


def test_departure_day_pinned():
    _, _, shifted = _load()
    dep_new = shifted["dep_min"] + shifted["shift_min"]
    assert dep_new.between(0, 1439).all(), "a departure crossed midnight"


def test_no_turnaround_violated():
    _, flights, shifted = _load()
    dep_abs, arr_abs, prev_idx, _, min_gap_prev, _ = build_chains(
        flights, config.MIN_TURNAROUND_MIN
    )
    shift = shifted["shift_min"].to_numpy()
    j = np.where(prev_idx >= 0)[0]
    i = prev_idx[j]
    gaps = (dep_abs[j] + shift[j]) - (arr_abs[i] + shift[i])
    assert np.all(gaps >= min_gap_prev[j]), "turnaround constraint violated"


def test_total_movements_conserved():
    """Departures + arrivals per airport, unclipped, before vs after."""
    sel, flights, shifted = _load()
    for a in sel["airports"]:
        before = (flights["origin"] == a).sum() + (flights["dest"] == a).sum()
        after = (shifted["origin"] == a).sum() + (shifted["dest"] == a).sum()
        assert before == after, f"movement count changed at {a}"


def test_daily_departure_counts_conserved():
    _, flights, shifted = _load()
    before = flights.groupby(["date", "origin"]).size()
    after = shifted.groupby(["date", "origin"]).size()
    assert before.equals(after), "per-day departure counts changed"


def test_no_airport_day_peak_increased():
    sel, _, _ = _load()
    base = pd.read_csv(config.DATA_DERIVED / "baseline_bins.csv")
    opt = pd.read_csv(config.DATA_DERIVED / "optimized_bins.csv")
    bmax = base.groupby(["airport", "date"])["load"].max()
    omax = opt.groupby(["airport", "date"])["load"].max()
    joined = pd.concat([bmax.rename("b"), omax.rename("o")], axis=1).dropna()
    assert (joined["o"] <= joined["b"]).all(), "an airport-day peak increased"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print("all sanity checks passed")
