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
