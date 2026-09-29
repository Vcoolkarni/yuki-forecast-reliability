import argparse
from pathlib import Path

import pandas as pd
import yaml

from forecast_bust.acquisition import download_era5, write_era5_request_for_dates
from forecast_bust.date_selection import configured_initialization_dates
from forecast_bust.era5_windows import contiguous_hour_ranges, dates_by_month, discover_era5_cache, missing_era5_hours, required_era5_hours


parser = argparse.ArgumentParser()
parser.add_argument("--initialization-date", help="Validate/acquire only one configured initialization date")
parser.add_argument("--check-only", action="store_true", help="Report missing coverage without downloading")
args = parser.parse_args()

cfg = yaml.safe_load(Path("config/phase2.yaml").read_text())
configured = configured_initialization_dates(cfg)
if args.initialization_date:
    if args.initialization_date not in configured:
        raise ValueError("--initialization-date must occur in time.initialization_dates")
    selected = [args.initialization_date]
else:
    selected = configured

required = required_era5_hours(selected, cfg["forecast"]["lead_days"])
raw_dir = Path(cfg["paths"]["raw_dir"])
cache_dir = raw_dir / "era5_phase2"
cache_dir.mkdir(parents=True, exist_ok=True)
existing = discover_era5_cache(raw_dir)
missing = missing_era5_hours(required, existing)
print(f"ERA5_REQUIRED_HOURS={len(required)}")
print(f"ERA5_MISSING_HOURS={len(missing)}")
for start, end in contiguous_hour_ranges(missing):
    count = int((end - start) / pd.Timedelta(hours=1)) + 1
    print(f"ERA5_MISSING_RANGE={start.isoformat()}..{end.isoformat()} HOURS={count}")

if not args.check_only and len(missing):
    for month, dates in dates_by_month(missing).items():
        target = cache_dir / f"era5_tp_{dates[0].replace('-', '')}_{dates[-1].replace('-', '')}_central_india.nc"
        plan = Path(cfg["paths"]["interim_dir"]) / f"era5_phase2_{month}_request.json"
        write_era5_request_for_dates(cfg, dates, plan)
        expected = missing[missing.strftime("%Y%m") == month]
        download_era5(plan, ".secrets/cds_credentials.txt", target, expected_hours=expected)

remaining = missing_era5_hours(required, discover_era5_cache(raw_dir))
print(f"ERA5_REMAINING_MISSING_HOURS={len(remaining)}")
for start, end in contiguous_hour_ranges(remaining):
    count = int((end - start) / pd.Timedelta(hours=1)) + 1
    print(f"ERA5_REMAINING_RANGE={start.isoformat()}..{end.isoformat()} HOURS={count}")
if len(remaining):
    raise ValueError("ERA5 cache coverage is incomplete for the selected initialization dates and leads")
print("ERA5_COVERAGE_OK=true")
