"""Explicit, gated BALANCED acquisition or tiny 2022 Day-1/Day-10 smoke validation."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path

import pandas as pd
import xarray as xr

from forecast_bust.acquisition import download_era5, write_era5_request_for_dates
from forecast_bust.era5_windows import required_era5_hours
from forecast_bust.v2.acquisition import (download_message, retrieve_one_era5_month_plan,
                                          write_missing_era5_month_plans)
from forecast_bust.v2.balanced import (assemble_balanced_forecast, attach_balanced_reference,
                                        balanced_gefs_jobs, balanced_gfs_jobs, era5_reference_for_leads)
from forecast_bust.v2.configuration import initialization_dates, load_v2_config
from forecast_bust.v2.feature_schema import forecast_feature_schema
from forecast_bust.v2.planning import message_jobs
from forecast_bust.v2.profile_planning import estimate_profiles, load_profile_config


def _describe(series: pd.Series) -> dict:
    return {"min": float(series.min()), "mean": float(series.mean()), "max": float(series.max())}


def smoke(config: dict, credential_path: Path) -> dict:
    initialization = "2022-07-01"  # pre-2025; no final-test data touched
    leads = [1, 10]
    cfg = deepcopy(config)
    cfg["geography"].update({"south": 20.0, "north": 20.5, "west": 76.0, "east": 76.5})
    cfg["paths"]["raw_dir"] = "data/raw/v2/smoke"
    gfs_jobs = balanced_gfs_jobs(cfg, initialization, leads)
    gefs_jobs = balanced_gefs_jobs(cfg, initialization, leads)
    if len(gfs_jobs) != 34 or len(gefs_jobs) != 16:
        raise ValueError("Smoke request guard: expected exactly 34 GFS and 16 GEFS messages")
    for job in gfs_jobs + gefs_jobs:
        download_message(job, max_message_mib=16.0)

    forecast, provenance = assemble_balanced_forecast(cfg, initialization, leads, gfs_jobs, gefs_jobs)
    required = required_era5_hours([initialization], leads)
    dates = sorted(set(required.strftime("%Y-%m-%d")))
    request_path = Path(cfg["paths"]["raw_dir"]) / "era5" / "requests" / "era5_20220701_day1_day10.json"
    target = Path(cfg["paths"]["raw_dir"]) / "era5" / "era5_20220701_day1_day10.nc"
    write_era5_request_for_dates(cfg, dates, request_path)
    download_era5(request_path, credential_path, target, expected_hours=required)
    with xr.open_dataset(target) as dataset:
        reference = era5_reference_for_leads(dataset, initialization, leads, cfg["geography"])
    schema_config = deepcopy(cfg)
    schema_config["forecast"]["gefs"]["mode"] = "published_6h_mean_spread"
    records = attach_balanced_reference(forecast, reference, list(forecast_feature_schema(schema_config)))
    if len(records) != 18 or len(records[records.lead_day == 1]) != 9 or len(records[records.lead_day == 10]) != 9:
        raise ValueError("Smoke grid record count is inconsistent with the 3×3 crop")
    if records.isna().any().any():
        raise ValueError("Smoke records contain missing values")
    if not (records.valid_time == records.initialization_time + pd.to_timedelta(records.lead_day, unit="D")).all():
        raise ValueError("Forecast/reference valid times are misaligned")
    interim = Path("data/interim/v2/smoke/balanced_20220701_day1_day10.csv")
    interim.parent.mkdir(parents=True, exist_ok=True)
    records.to_csv(interim, index=False)
    report = {
        "initialization_time": "2022-07-01T00:00:00Z", "leads": leads,
        "grid_cells_per_lead": 9, "records": len(records),
        "units": {"gfs_precipitation": "mm/24h", "era5_precipitation": "mm/24h",
                  "gefs_daily_mean": "mm/24h", "gefs_interval_spread": "mm/6h"},
        "components": provenance,
        "per_lead": {str(lead): {
            "gfs_precipitation_mm": _describe(group.forecast_precipitation),
            "era5_precipitation_mm": _describe(group.reference_precipitation),
            "gefs_daily_mean_mm": _describe(group.gefs_precipitation_mean_mm),
            "gefs_6h_spread_mean_mm": _describe(group.gefs_6h_spread_mean_mm),
            "gefs_6h_spread_max_mm": _describe(group.gefs_6h_spread_max_mm),
        } for lead, group in records.groupby("lead_day")},
        "missing_values": int(records.isna().sum().sum()),
        "grid_alignment": "exact 0.25-degree 3x3 centers for GFS, GEFS, ERA5",
        "era5_required_hourly_endpoints": len(required),
        "gfs_messages": len(gfs_jobs), "gefs_messages": len(gefs_jobs),
        "records_csv": str(interim),
    }
    report_path = Path("reports/v2/balanced_smoke_20220701.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def full(config: dict, profile_config: dict, credential_path: Path) -> dict:
    plan = next(item for item in estimate_profiles(config, profile_config)
                if item["PROFILE_NAME"] == "BALANCED" and item["SAMPLING_FREQUENCY"] == "every 3 days")
    if plan["INITIALIZATIONS"] != 205 or plan["ESTIMATED_DOWNLOAD_GIB"] > 45:
        raise ValueError("Full-acquisition guard: selected BALANCED plan differs materially from review")
    cfg = deepcopy(config)
    cfg["time"]["start_date"] = "2021-06-01"
    cfg["time"]["end_date"] = "2025-09-30"
    cfg["time"]["sampling"] = {"months": [6, 7, 8, 9], "every_n_days": 3, "anchor_day_of_month": 1}
    cfg["forecast"]["gefs"]["enabled"] = False  # member-mode planner must not run
    dates = initialization_dates(cfg)
    if len(dates) != 205:
        raise ValueError("Expected exactly 205 BALANCED initialization dates")
    gfs = message_jobs(cfg)
    gefs = [job for day in dates for job in balanced_gefs_jobs(cfg, day, cfg["forecast"]["lead_days"])]
    if len(gfs) != plan["GFS_MESSAGES"] or len(gefs) != plan["GEFS_MESSAGES"]:
        raise ValueError("Full-acquisition job counts do not match estimator")
    for job in gfs + gefs:
        download_message(job, max_message_mib=16.0)
    era5_plans = write_missing_era5_month_plans(cfg)
    for month_plan in era5_plans:
        retrieve_one_era5_month_plan(month_plan, cfg, credential_path)
    return {"initializations": len(dates), "gfs_messages_ready": len(gfs),
            "gefs_messages_ready": len(gefs), "era5_months_requested": len(era5_plans)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--smoke", action="store_true", help="Only 2022-07-01, 3×3 grid, Day 1 and Day 10")
    mode.add_argument("--full", action="store_true", help="205-date BALANCED acquisition; requires --confirm-full")
    parser.add_argument("--confirm-full", action="store_true")
    parser.add_argument("--credentials", default=".secrets/cds_credentials.txt")
    args = parser.parse_args()
    if args.full and not args.confirm_full:
        parser.error("--full requires --confirm-full; review the offline estimate first")
    config = load_v2_config()
    result = full(config, load_profile_config(), Path(args.credentials)) if args.full else smoke(config, Path(args.credentials))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
