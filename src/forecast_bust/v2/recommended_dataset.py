"""Build the RECOMMENDED historical sample solely from validated local caches."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import os

import pandas as pd
import xarray as xr

from ..era5_windows import dates_by_month, required_era5_hours
from ..labeling import apply_percentile_labels, fit_percentile_thresholds
from .acquisition import download_message
from .balanced import assemble_balanced_forecast, attach_balanced_reference, era5_reference_for_leads
from .dataset import validate_historical
from .feature_schema import forecast_feature_schema
from .geography import validate_full_grid_coverage
from .recommended_acquisition import (PROFILE_ROOT, era5_month_jobs, jobs_for_date,
                                      recommended_dates, split_for_date)


def recommended_forecast_config(base: dict, budget_config: dict) -> dict:
    selected = deepcopy(base)
    grid = budget_config["grid"]
    selected["geography"] = {name: grid[name] for name in ("south", "north", "west", "east")}
    selected["geography"]["grid_resolution_degrees"] = .5
    names = ["precipitation", *budget_config["gfs"]["instantaneous_predictors"]]
    selected["forecast"]["gfs"]["predictors"] = {
        name: base["forecast"]["gfs"]["predictors"][name] for name in names}
    selected["forecast"]["gefs"]["mode"] = "published_daily_mean_end_window_spread"
    return selected


def build_recommended_date(base: dict, budget_config: dict, day: str,
                           month_jobs: dict[str, dict], root: Path = PROFILE_ROOT) -> tuple[pd.DataFrame, dict]:
    """Fail closed on every missing GRIB/ERA5 cache and exact 24-hour window."""
    config = recommended_forecast_config(base, budget_config)
    jobs = jobs_for_date(base, budget_config, day, root)
    missing = [str(job.target) for job in jobs if not job.target.is_file() or job.target.stat().st_size == 0]
    if missing:
        raise FileNotFoundError(f"{day} has {len(missing)} missing GRIB messages; first: {missing[0]}")
    for job in jobs:
        download_message(job)  # cache path only; provenance/hash/inventory checks, no network
    forecast, component_provenance = assemble_balanced_forecast(
        config, day, list(range(1, 11)),
        [job for job in jobs if job.source == "gfs"],
        [job for job in jobs if job.source == "gefs"])
    validate_full_grid_coverage(forecast, config["geography"])

    hours = required_era5_hours([day], list(range(1, 11)))
    datasets = []
    try:
        for month in dates_by_month(hours):
            job = month_jobs[month]
            target = Path(job["target"])
            if not target.is_file() or not target.with_suffix(".nc.provenance.json").is_file():
                raise FileNotFoundError(f"Validated ERA5 month cache is missing: {target}")
            source = xr.open_dataset(target, engine="netcdf4")
            datasets.append(source)
        time_name = "valid_time" if "valid_time" in datasets[0].coords else "time"
        reference_source = xr.concat(datasets, dim=time_name, combine_attrs="override")
        reference = era5_reference_for_leads(reference_source, day, list(range(1, 11)), config["geography"])
    finally:
        for source in datasets:
            source.close()
    features = list(forecast_feature_schema(config))
    historical = attach_balanced_reference(forecast, reference, features)
    validate_historical(historical, features)
    if len(historical) != len(forecast) or historical.duplicated(
            ["initialization_time", "lead_day", "latitude", "longitude"]).any():
        raise ValueError(f"{day} historical grid has missing or duplicate records")
    return historical, component_provenance


def build_recommended_dataset(base: dict, budget_config: dict,
                              root: Path = PROFILE_ROOT,
                              output_root: Path = Path("data/processed/v2/recommended_0p50")) -> dict:
    """Build split-isolated daily partitions; fit P90 labels on 2021–23 only."""
    dates = recommended_dates(base, budget_config)
    months = {job["month"]: job for job in era5_month_jobs(base, dates, root)}
    output_root.mkdir(parents=True, exist_ok=True)
    raw_paths: dict[str, list[Path]] = {"train": [], "validation": [], "final_test_untouched": []}
    provenance = {}
    for day in dates:
        split = split_for_date(day)
        path = output_root / split / f"{day}.raw.csv.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            # ERA5 tp is float32 in the NetCDF cache. Restoring that dtype is
            # necessary when reading its decimal CSV representation back;
            # float64 parsing can shift a few values by ~1e-6 mm and break
            # the exact GFS−ERA5 error consistency check.
            frame = pd.read_csv(path, parse_dates=["initialization_time", "valid_time"],
                                dtype={"reference_precipitation": "float32"})
            validate_historical(frame, list(forecast_feature_schema(
                recommended_forecast_config(base, budget_config))))
            validate_full_grid_coverage(frame, recommended_forecast_config(base, budget_config)["geography"])
            if frame.initialization_time.dt.strftime("%Y-%m-%d").nunique() != 1 or frame.initialization_time.dt.strftime("%Y-%m-%d").iloc[0] != day:
                raise ValueError(f"Existing raw partition has the wrong initialization: {path}")
            components = {str(lead): {"gfs_apcp_component_forecast_hours":
                         list(range((lead - 1) * 24 + 6, lead * 24 + 1, 6)),
                         "gefs_spread_component_forecast_hours": [lead * 24]}
                          for lead in range(1, 11)}
        else:
            frame, components = build_recommended_date(base, budget_config, day, months, root)
            temporary = path.with_suffix(path.suffix + ".part")
            frame.to_csv(temporary, index=False, compression="gzip")
            os.replace(temporary, path)
        raw_paths[split].append(path)
        provenance[day] = {"split": split, "rows": len(frame), "components": components,
                           "raw_sha256": sha256(path.read_bytes()).hexdigest()}

    training_errors = pd.concat(
        [pd.read_csv(path, usecols=["lead_day", "absolute_error"])
         for path in raw_paths["train"]], ignore_index=True)
    thresholds = fit_percentile_thresholds(training_errors, float(base["model"]["percentile"]), by_lead=True)
    summary = {"initializations": {}, "rows": {}, "bust_rate": {}, "bust_rate_by_lead": {},
               "mean_reference_precipitation_mm": {}, "mean_absolute_error_mm": {},
               "thresholds_mm": thresholds,
               "feature_names": list(forecast_feature_schema(recommended_forecast_config(base, budget_config))),
               "missing_values": 0, "duplicate_grid_keys": 0,
               "dates": {split: [path.name[:10] for path in paths] for split, paths in raw_paths.items()},
               "partitions": provenance}
    for split, paths in raw_paths.items():
        count = busts = 0
        reference_sum = error_sum = 0.0
        by_lead = {lead: {"rows": 0, "busts": 0} for lead in range(1, 11)}
        for raw_path in paths:
            frame = pd.read_csv(raw_path, parse_dates=["initialization_time", "valid_time"],
                                dtype={"reference_precipitation": "float32"})
            labeled = apply_percentile_labels(frame, thresholds)
            final = raw_path.with_name(raw_path.name.replace(".raw.csv.gz", ".csv.gz"))
            if final.exists():
                existing = pd.read_csv(final, usecols=["is_bust"])
                if not existing.is_bust.reset_index(drop=True).equals(labeled.is_bust.reset_index(drop=True)):
                    raise ValueError(f"Existing V2 labels disagree with training-only P90 thresholds: {final}")
            else:
                temporary = final.with_suffix(final.suffix + ".part")
                labeled.to_csv(temporary, index=False, compression="gzip")
                os.replace(temporary, final)
            day = raw_path.name[:10]
            provenance[day]["labeled_sha256"] = sha256(final.read_bytes()).hexdigest()
            count += len(labeled)
            busts += int(labeled.is_bust.sum())
            reference_sum += float(labeled.reference_precipitation.sum())
            error_sum += float(labeled.absolute_error.sum())
            for lead, group in labeled.groupby("lead_day"):
                by_lead[int(lead)]["rows"] += len(group)
                by_lead[int(lead)]["busts"] += int(group.is_bust.sum())
        summary["initializations"][split] = len(paths)
        summary["rows"][split] = count
        summary["bust_rate"][split] = busts / count
        summary["mean_reference_precipitation_mm"][split] = reference_sum / count
        summary["mean_absolute_error_mm"][split] = error_sum / count
        summary["bust_rate_by_lead"][split] = {
            str(lead): by_lead[lead]["busts"] / by_lead[lead]["rows"] for lead in range(1, 11)}
    manifest = output_root / "dataset_manifest.json"
    manifest.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    ledger = json.loads((root / ".download_budget.json").read_text(encoding="utf-8"))
    gfs_files = gefs_files = forecast_bytes = 0
    for day in dates:
        for job in jobs_for_date(base, budget_config, day, root):
            if not job.target.is_file() or not job.target.with_suffix(job.target.suffix + ".provenance.json").is_file():
                raise FileNotFoundError(f"Acquisition manifest found a missing/unvalidated message: {job.target}")
            forecast_bytes += job.target.stat().st_size
            gfs_files += job.source == "gfs"
            gefs_files += job.source == "gefs"
    era5_files = era5_month_jobs(base, dates, root)
    if any(not item["target"].is_file() for item in era5_files):
        raise FileNotFoundError("Acquisition manifest found an incomplete ERA5 month")
    acquisition = {"profile": "RECOMMENDED", "initializations": summary["initializations"],
                   "gfs_messages": gfs_files, "gefs_messages": gefs_files,
                   "era5_months": len(era5_files), "forecast_cache_bytes": forecast_bytes,
                   "era5_cache_bytes": sum(item["target"].stat().st_size for item in era5_files),
                   "downloaded_payload_bytes": ledger["downloaded_bytes"],
                   "charged_payload_bytes": ledger["charged_bytes"],
                   "hard_limit_bytes": ledger["limit_bytes"],
                   "date_splits": summary["dates"]}
    report_dir = Path("reports/v2/recommended_0p50")
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "acquisition_manifest.json").write_text(
        json.dumps(acquisition, indent=2), encoding="utf-8")
    return summary
