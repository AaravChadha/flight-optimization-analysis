"""Headline metrics and sensitivity sweep.

Definitions (also spelled out in the README):

* 15-min bin load: scheduled movements (departures + arrivals) at one
  airport in one 15-minute bin of one service day.
* hourly load: rolling sum of 4 consecutive bins within a day (windows
  starting at each of the 93 bin offsets). Stricter than clock hours.
* peak reduction (%): drop in the mean-over-days daily maximum load,
  before vs after re-timing. Reported for both bin and hourly loads.
* slots freed (per airport per day): max hourly load before minus max
  hourly load after. Because re-timing conserves the number of flights,
  total daily headroom is conserved; the only real capacity change is AT
  THE PEAK. This counts additional movements schedulable in the formerly
  busiest hour without exceeding the load the airport demonstrably handled.
* capacity proxy: the CAPACITY_PERCENTILE-th percentile of all observed
  rolling-hour loads at that airport in the baseline month. An ASSUMPTION
  standing in for published runway capacity, not a fact.

Simulated results on historical schedules under these assumptions - not
predictions about real operations.
"""

import json

import numpy as np
import pandas as pd

import config
import prepare
from optimize import optimize


def loads_table(flights: pd.DataFrame, shift, airports) -> pd.DataFrame:
    """Long-form (airport, day, bin, load) with shifts applied.

    Only service days of the selected month are kept (arrivals spilling
    into the next month are excluded from metrics; symmetric undercount of
    inbound red-eyes on day 1 is noted in limitations - both effects sit
    in near-empty overnight bins and do not touch daytime peaks).
    """
    b = config.BIN_MINUTES
    day = pd.to_datetime(flights["date"])
    month_days = set(day.dt.date.astype(str))

    dep = flights[flights["origin"].isin(airports)]
    dep_t = dep["dep_min"].to_numpy() + shift[dep.index.to_numpy()]
    deps = pd.DataFrame(
        {"airport": dep["origin"].to_numpy(), "date": dep["date"].to_numpy(),
         "bin": dep_t // b}
    )

    arr = flights[flights["dest"].isin(airports)]
    arr_abs = (
        arr["arr_day_offset"].to_numpy() * 1440
        + arr["arr_min"].to_numpy()
        + shift[arr.index.to_numpy()]
    )
    arr_date = (
        pd.to_datetime(arr["date"]) + pd.to_timedelta(arr_abs // 1440, unit="D")
    ).dt.date.astype(str)
    arrs = pd.DataFrame(
        {"airport": arr["dest"].to_numpy(), "date": arr_date.to_numpy(),
         "bin": (arr_abs % 1440) // b}
    )
    moves = pd.concat([deps, arrs], ignore_index=True)
    moves = moves[moves["date"].isin(month_days)]
    return (
        moves.groupby(["airport", "date", "bin"]).size().rename("load").reset_index()
    )


def _daily_profiles(loads: pd.DataFrame):
    """{(airport, date): ndarray[96]} of bin loads."""
    out = {}
    for (a, d), grp in loads.groupby(["airport", "date"]):
        v = np.zeros(96, dtype=int)
        v[grp["bin"].to_numpy()] = grp["load"].to_numpy()
        out[(a, d)] = v
    return out


def _hourly(v: np.ndarray) -> np.ndarray:
    return np.convolve(v, np.ones(4, dtype=int), mode="valid")  # 93 windows


def airport_metrics(base: pd.DataFrame, after: pd.DataFrame, airports) -> dict:
    pb, pa = _daily_profiles(base), _daily_profiles(after)
    out = {}
    for a in airports:
        days = sorted(d for (ap, d) in pb if ap == a)
        max15_b = np.array([pb[(a, d)].max() for d in days])
        max15_a = np.array([pa[(a, d)].max() for d in days])
        maxh_b = np.array([_hourly(pb[(a, d)]).max() for d in days])
        maxh_a = np.array([_hourly(pa[(a, d)]).max() for d in days])

        all_hours_base = np.concatenate([_hourly(pb[(a, d)]) for d in days])
        c95 = float(np.percentile(all_hours_base, config.CAPACITY_PERCENTILE))
        over_b = int((np.concatenate([_hourly(pb[(a, d)]) for d in days]) >= c95).sum())
        over_a = int((np.concatenate([_hourly(pa[(a, d)]) for d in days]) >= c95).sum())

        out[a] = {
            "mean_daily_max_bin_before": float(max15_b.mean()),
            "mean_daily_max_bin_after": float(max15_a.mean()),
            "peak_bin_reduction_pct": _pct(max15_b.mean(), max15_a.mean()),
            "abs_max_bin_before": int(max15_b.max()),
            "abs_max_bin_after": int(max15_a.max()),
            "mean_daily_max_hour_before": float(maxh_b.mean()),
            "mean_daily_max_hour_after": float(maxh_a.mean()),
            "peak_hour_reduction_pct": _pct(maxh_b.mean(), maxh_a.mean()),
            "slots_freed_per_day": float((maxh_b - maxh_a).mean()),
            "capacity_proxy_p95_hourly": c95,
            "hour_windows_at_or_above_proxy_before": over_b,
            "hour_windows_at_or_above_proxy_after": over_a,
        }
    return out


def _pct(before: float, after: float) -> float:
    return round(100.0 * (before - after) / before, 2) if before else 0.0


def overall(per_airport: dict) -> dict:
    ms = list(per_airport.values())
    tot_b15 = sum(m["mean_daily_max_bin_before"] for m in ms)
    tot_a15 = sum(m["mean_daily_max_bin_after"] for m in ms)
    tot_bh = sum(m["mean_daily_max_hour_before"] for m in ms)
    tot_ah = sum(m["mean_daily_max_hour_after"] for m in ms)
    return {
        "peak_bin_reduction_pct": _pct(tot_b15, tot_a15),
        "peak_hour_reduction_pct": _pct(tot_bh, tot_ah),
        "slots_freed_per_day_total": round(
            sum(m["slots_freed_per_day"] for m in ms), 2
        ),
    }


def worst_day(base: pd.DataFrame, after: pd.DataFrame) -> dict:
    """The single airport-day with the highest baseline 15-min bin load,
    before vs after re-timing - the case where smoothing matters most."""
    pb, pa = _daily_profiles(base), _daily_profiles(after)
    a, d = max(pb, key=lambda k: pb[k].max())
    vb, va = pb[(a, d)], pa[(a, d)]
    peak_bin = int(vb.argmax())
    t = f"{peak_bin * config.BIN_MINUTES // 60:02d}:{peak_bin * config.BIN_MINUTES % 60:02d}"
    return {
        "airport": a,
        "date": d,
        "peak_bin_time_local": t,
        "max_bin_before": int(vb.max()),
        "max_bin_after": int(va.max()),
        "max_hour_before": int(_hourly(vb).max()),
        "max_hour_after": int(_hourly(va).max()),
    }


def run_all() -> dict:
    sel = prepare.load_selection()
    flights = prepare.load_flights()
    airports = sel["airports"]
    base = loads_table(flights, np.zeros(len(flights), dtype=int), airports)

    sensitivity = []
    headline = None
    for w in config.SENSITIVITY_WINDOWS:
        print(f"\n=== window ±{w} min ===")
        shift, stats = optimize(flights, airports, w)
        after = loads_table(flights, shift, airports)
        per_airport = airport_metrics(base, after, airports)
        agg = overall(per_airport)
        sensitivity.append(
            {"window_min": w, "n_shifted": stats["n_shifted"], **agg,
             "per_airport": {
                 a: {
                     "peak_bin_reduction_pct": m["peak_bin_reduction_pct"],
                     "peak_hour_reduction_pct": m["peak_hour_reduction_pct"],
                     "slots_freed_per_day": m["slots_freed_per_day"],
                 }
                 for a, m in per_airport.items()
             }}
        )
        print(f"  shifted {stats['n_shifted']:,} flights | "
              f"peak bin -{agg['peak_bin_reduction_pct']}% | "
              f"peak hour -{agg['peak_hour_reduction_pct']}% | "
              f"slots freed/day {agg['slots_freed_per_day_total']}")
        if w == config.SHIFT_WINDOW_MIN:
            headline = {"per_airport": per_airport, "overall": agg,
                        "stats": stats}
            headline_after = after
            flights.assign(shift_min=shift).to_csv(
                config.DATA_DERIVED / f"shifts_w{w}.csv.gz",
                index=False, compression="gzip",
            )
            after.to_csv(config.DATA_DERIVED / "optimized_bins.csv", index=False)

    case_study = worst_day(base, headline_after)

    summary = {
        "study": "Flight schedule smoothing - simulation on historical BTS data",
        "claims_note": (
            "All results are simulated re-timings of historical schedules "
            "under the stated assumptions. No operational, safety, or "
            "airspace conclusions are implied."
        ),
        "data": {
            "source": "BTS Marketing Carrier On-Time Performance",
            "year": sel["year"],
            "month": sel["selected_month"],
            "airports": airports,
        },
        "config": {
            "bin_minutes": config.BIN_MINUTES,
            "headline_window_min": config.SHIFT_WINDOW_MIN,
            "shift_step_min": config.SHIFT_STEP_MIN,
            "min_turnaround_min": config.MIN_TURNAROUND_MIN,
            "capacity_percentile": config.CAPACITY_PERCENTILE,
            "open_bin_min_mean": config.OPEN_BIN_MIN_MEAN,
        },
        "headline": headline,
        "sensitivity": sensitivity,
        "worst_day_case_study": case_study,
    }
    config.RESULTS.mkdir(parents=True, exist_ok=True)
    (config.RESULTS / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {config.RESULTS / 'summary.json'}")
    return summary


if __name__ == "__main__":
    run_all()
