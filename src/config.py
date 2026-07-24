"""Central configuration for the schedule-smoothing study.

Every modeling knob lives here so the analysis can be re-run under
different assumptions without touching the pipeline code.
"""

from pathlib import Path

# ---------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
DATA_DERIVED = ROOT / "data" / "derived"
RESULTS = ROOT / "results"
FIGURES = RESULTS / "figures"
DOCS_FIGURES = ROOT / "docs" / "figures"

# ---------------------------------------------------------------- data
YEAR = 2025          # most recent full year published by BTS at build time
MONTHS = list(range(1, 13))

# BTS Marketing Carrier On-Time Performance prezip endpoint.
BTS_URL = (
    "https://transtats.bts.gov/PREZIP/"
    "On_Time_Marketing_Carrier_On_Time_Performance_"
    "Beginning_January_2018_{year}_{month}.zip"
)

# Columns we actually use, verified against the 2025 header.
# NOTE: the raw header spells the operating carrier "Operating_Airline "
# with a trailing space; we normalize whitespace on load.
COLUMNS = [
    "FlightDate",
    "Marketing_Airline_Network",
    "Flight_Number_Marketing_Airline",
    "Tail_Number",
    "Origin",
    "Dest",
    "CRSDepTime",
    "CRSArrTime",
    "Cancelled",
]

# ---------------------------------------------------------------- scope
N_AIRPORTS = 5        # busiest airports by scheduled movements
BIN_MINUTES = 15      # demand bin width

# ---------------------------------------------------------------- model
SHIFT_WINDOW_MIN = 30       # max departure shift, minutes (headline run)
SHIFT_STEP_MIN = 15         # shifts move in bin-sized steps
MIN_TURNAROUND_MIN = 30     # minimum ground time between legs of a tail
SENSITIVITY_WINDOWS = [15, 30, 45, 60]

# Empirical capacity proxy: percentile of observed hourly movements.
# This is an ASSUMPTION standing in for published runway capacity.
CAPACITY_PERCENTILE = 95

# Operating envelope: a flight may only be MOVED INTO a 15-minute
# bin-of-day that the airport actually used at baseline - mean scheduled
# movements per day in that bin >= this threshold. Airports are not
# all 24/7; this keeps re-timing inside each airport's observed
# operating hours (an empirical envelope, not published curfew data).
OPEN_BIN_MIN_MEAN = 1.0

# Shoulder protection: a bin may not grow beyond this multiple of its
# baseline mean load for that time of day (or beyond its own same-day
# baseline load, if that was already higher). Prevents peak drainage from
# ballooning the early-morning / late-evening shoulders, where crew report
# times and passenger tolerance make extra flights operationally costly.
BIN_GROWTH_CAP = 1.5

# Robustness: re-measure headline metrics on a grid offset by ~half a bin
# to size the binning artifact (15-min bins, so 8 minutes).
GRID_OFFSET_MIN = 8
