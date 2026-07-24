"""Download BTS Marketing Carrier On-Time Performance data.

Source: Bureau of Transportation Statistics, https://www.transtats.bts.gov/ots/
US government work, public domain. Monthly prezipped CSVs are fetched into
data/raw/ as otp_<year>_<month>.zip. Files already present are skipped, so
the script is safe to re-run.

Usage:
    python src/fetch_data.py                 # all 12 months of config.YEAR
    python src/fetch_data.py --months 3 7    # specific months
"""

import argparse
import sys
import urllib.request

import config


def zip_path(year: int, month: int):
    return config.DATA_RAW / f"otp_{year}_{month}.zip"


def fetch_month(year: int, month: int, force: bool = False) -> bool:
    """Download one month. Returns True on success."""
    dest = zip_path(year, month)
    if dest.exists() and not force:
        print(f"  {dest.name}: already present, skipping")
        return True
    url = config.BTS_URL.format(year=year, month=month)
    print(f"  {dest.name}: downloading {url}")
    try:
        tmp = dest.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(dest)
        return True
    except Exception as exc:  # noqa: BLE001 - report and continue
        print(f"  FAILED month {month}: {exc}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=config.YEAR)
    parser.add_argument("--months", type=int, nargs="+", default=config.MONTHS)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
    print(f"Fetching BTS on-time data for {args.year}, months {args.months}")
    ok = all([fetch_month(args.year, m, args.force) for m in args.months])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
