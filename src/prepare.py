"""Filter, clean, and bin the BTS schedule data.

Pipeline (all driven by config.py):
  1. Scan all downloaded months and pick the N busiest airports by
     scheduled movements (departures + arrivals, cancelled flights dropped).
  2. Pick the busiest month at those airports.
  3. Extract a clean flight table for that month (ALL airports, so that
     tail-number turnaround chains are complete even when a leg touches a
     non-selected airport).
  4. Bin scheduled movements at the selected airports into 15-minute bins.

Times: BTS scheduled times are local to each airport. Congestion at an
airport is a local-clock phenomenon and we never merge time series across
airports, so no timezone conversion is performed.

Overnight arrivals: BTS gives clock times only. If scheduled arrival is
earlier than scheduled departure, the arrival is assigned to the next
calendar day. For US domestic flights the scheduled block time always
exceeds the westbound timezone gain, so this rule is safe.

Midnight departures: BTS occasionally encodes midnight as "2400"; we map it
to 00:00 on the same service date (affects <0.1% of flights).
"""

import argparse
import json
import sys
import zipfile

import numpy as np
import pandas as pd

import config

SLIM_COLS = ["FlightDate", "Origin", "Dest", "Cancelled"]


def read_month(year: int, month: int, columns):
    """Read one monthly CSV straight out of its zip (never unpacked to disk)."""
    path = config.DATA_RAW / f"otp_{year}_{month}.zip"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing - run fetch_data.py first")
    with zipfile.ZipFile(path) as zf:
        member = next(n for n in zf.namelist() if n.endswith(".csv"))
        with zf.open(member) as fh:
            # Normalize header whitespace: the raw file has "Operating_Airline "
            # (trailing space). Read the header first, then map.
            header = pd.read_csv(fh, nrows=0)
        stripped = {c: c.strip() for c in header.columns}
        want = {raw for raw, clean in stripped.items() if clean in columns}
        with zf.open(member) as fh:
            df = pd.read_csv(fh, usecols=sorted(want), dtype=str, na_values=[""])
    return df.rename(columns=stripped)


def hhmm_to_min(s: pd.Series) -> pd.Series:
    """'1250' -> 770. '2400' -> 0 (midnight, same service date)."""
    v = pd.to_numeric(s, errors="coerce")
    v = v.where(v != 2400, 0)
    return (v // 100) * 60 + (v % 100)


def scan_movements(year: int, months):
    """Non-cancelled scheduled movements per airport and per month."""
    per_airport = {}
    per_month = {}
    for m in months:
        df = read_month(year, m, SLIM_COLS)
        df = df[pd.to_numeric(df["Cancelled"]) == 0]
        counts = (
            df["Origin"].value_counts().add(df["Dest"].value_counts(), fill_value=0)
        )
        per_month[m] = counts
        per_airport = counts.add(pd.Series(per_airport), fill_value=0).to_dict()
        print(f"  scanned {year}-{m:02d}: {len(df):,} flights")
    return pd.Series(per_airport).sort_values(ascending=False), per_month


def select_scope(year: int, months):
    """Choose the busiest airports, then the busiest month at those airports."""
    airport_totals, per_month = scan_movements(year, months)
    airports = airport_totals.head(config.N_AIRPORTS).index.tolist()
    month_load = {
        m: int(counts.reindex(airports).fillna(0).sum())
        for m, counts in per_month.items()
    }
    busiest_month = max(month_load, key=month_load.get)
    selection = {
        "year": year,
        "airports": airports,
        "airport_movements_year": {
            a: int(airport_totals[a]) for a in airports
        },
        "month_movements_at_selected": month_load,
        "selected_month": busiest_month,
    }
    config.RESULTS.mkdir(parents=True, exist_ok=True)
    (config.RESULTS / "selection.json").write_text(json.dumps(selection, indent=2))
    return selection


def build_flights(year: int, month: int) -> pd.DataFrame:
    """Clean flight table for one month, all airports.

    Columns: date, carrier, flight_num, tail, origin, dest,
             dep_min (0-1439), arr_min (0-1439), arr_day_offset (0/1).
    """
    df = read_month(year, month, config.COLUMNS)
    n_raw = len(df)
    df = df[pd.to_numeric(df["Cancelled"]) == 0].copy()
    n_flown = len(df)

    df["dep_min"] = hhmm_to_min(df["CRSDepTime"])
    df["arr_min"] = hhmm_to_min(df["CRSArrTime"])
    df = df.dropna(subset=["dep_min", "arr_min", "FlightDate"])
    df["dep_min"] = df["dep_min"].astype(int)
    df["arr_min"] = df["arr_min"].astype(int)
    df["arr_day_offset"] = (df["arr_min"] < df["dep_min"]).astype(int)

    # A tail cannot depart the same airport twice at the same instant;
    # such rows are duplicate records, not duplicate flights.
    dupe_key = ["FlightDate", "Tail_Number", "Origin", "CRSDepTime"]
    dupes = df.duplicated(subset=dupe_key) & df["Tail_Number"].notna()
    n_dupes = int(dupes.sum())
    df = df[~dupes]

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["FlightDate"]).dt.date.astype(str),
            "carrier": df["Marketing_Airline_Network"],
            "flight_num": df["Flight_Number_Marketing_Airline"],
            "tail": df["Tail_Number"],
            "origin": df["Origin"],
            "dest": df["Dest"],
            "dep_min": df["dep_min"],
            "arr_min": df["arr_min"],
            "arr_day_offset": df["arr_day_offset"],
        }
    ).reset_index(drop=True)
    print(
        f"  {year}-{month:02d}: {n_raw:,} records, {n_flown:,} flown, "
        f"{n_dupes:,} duplicate records dropped, {len(out):,} flights kept, "
        f"{int(out['tail'].isna().sum()):,} with no tail number"
    )
    return out


def bin_loads(flights: pd.DataFrame, airports) -> pd.DataFrame:
    """Movements per (airport, date, 15-min bin) at the selected airports.

    Departures count at the origin, arrivals at the destination (on the
    arrival day). Returns long-form: airport, date, bin, load.
    """
    b = config.BIN_MINUTES
    dep = flights[flights["origin"].isin(airports)]
    deps = pd.DataFrame(
        {
            "airport": dep["origin"],
            "date": dep["date"],
            "bin": dep["dep_min"] // b,
        }
    )
    arr = flights[flights["dest"].isin(airports)].copy()
    arr_date = pd.to_datetime(arr["date"]) + pd.to_timedelta(
        arr["arr_day_offset"], unit="D"
    )
    arrs = pd.DataFrame(
        {
            "airport": arr["dest"],
            "date": arr_date.dt.date.astype(str),
            "bin": arr["arr_min"] // b,
        }
    )
    moves = pd.concat([deps, arrs], ignore_index=True)
    return (
        moves.groupby(["airport", "date", "bin"]).size().rename("load").reset_index()
    )


def load_selection() -> dict:
    return json.loads((config.RESULTS / "selection.json").read_text())


def load_flights() -> pd.DataFrame:
    sel = load_selection()
    path = config.DATA_DERIVED / f"flights_{sel['year']}_{sel['selected_month']:02d}.csv.gz"
    return pd.read_csv(path, dtype={"flight_num": str}, keep_default_na=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reuse-selection",
        action="store_true",
        help="skip the 12-month scan and reuse results/selection.json",
    )
    args = parser.parse_args()

    if args.reuse_selection and (config.RESULTS / "selection.json").exists():
        selection = load_selection()
        print("Reusing cached selection.")
    else:
        print("Scanning all months for airport/month selection...")
        selection = select_scope(config.YEAR, config.MONTHS)

    print(f"Selected airports: {selection['airports']}")
    print(f"Selected month:    {selection['year']}-{selection['selected_month']:02d}")

    print("Building clean flight table...")
    flights = build_flights(selection["year"], selection["selected_month"])
    config.DATA_DERIVED.mkdir(parents=True, exist_ok=True)
    out = config.DATA_DERIVED / (
        f"flights_{selection['year']}_{selection['selected_month']:02d}.csv.gz"
    )
    flights.to_csv(out, index=False, compression="gzip")
    print(f"  wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")

    print("Binning baseline demand...")
    baseline = bin_loads(flights, selection["airports"])
    baseline.to_csv(config.DATA_DERIVED / "baseline_bins.csv", index=False)
    peak = baseline.groupby("airport")["load"].max()
    print("Peak 15-min bin load per airport (baseline):")
    print(peak.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
