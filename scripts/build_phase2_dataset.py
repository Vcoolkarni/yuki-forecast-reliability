from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import xarray as xr
import yaml

from forecast_bust.acquisition import download_gfs_grib_message
from forecast_bust.date_selection import configured_initialization_dates
from forecast_bust.features import add_derived_meteorological_features
from forecast_bust.era5_windows import discover_era5_cache, missing_era5_hours, open_cached_era5, required_era5_hours
from forecast_bust.labeling import add_error_and_labels
from forecast_bust.matching import match_forecast_reference
from forecast_bust.schema import validate_dataset


cfg = yaml.safe_load(Path("config/phase2.yaml").read_text())
dates = configured_initialization_dates(cfg)
leads = cfg["forecast"]["lead_days"]
predictors = cfg["forecast"]["predictors"]
raw = Path(cfg["paths"]["raw_dir"]) / "gfs_phase2"
raw.mkdir(parents=True, exist_ok=True)


def job_parts(date: str, lead: int, predictor_name: str):
    compact = date.replace("-", "")
    hour = lead * 24
    url = f"https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{compact}/00/atmos/gfs.t00z.pgrb2.0p25.f{hour:03d}"
    predictor = predictors[predictor_name]
    selector = predictor["selector_template"].format(lead=lead)
    target = raw / f"gfs_{compact}_00_f{hour:03d}_{predictor['cache_suffix']}.grb2"
    return url, selector, target


def acquire(job):
    date, lead, predictor_name = job
    url, selector, target = job_parts(date, lead, predictor_name)
    download_gfs_grib_message(url, target, selector)
    return target


jobs = [(date, lead, predictor_name) for date in dates for lead in leads for predictor_name in cfg["forecast"]["variables"]]
with ThreadPoolExecutor(max_workers=6) as pool:
    list(pool.map(acquire, jobs))
print(f"GFS_MESSAGES_READY={len(jobs)}")

forecast_parts = []
for date in dates:
    previous = None
    init = pd.Timestamp(f"{date}T00:00:00Z")
    for lead in leads:
        _, _, path = job_parts(date, lead, "precipitation")
        with xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""}) as dataset:
            cumulative = dataset[next(iter(dataset.data_vars))].sel(latitude=slice(cfg["geography"]["north"], cfg["geography"]["south"]), longitude=slice(cfg["geography"]["west"], cfg["geography"]["east"])).load()
        daily = cumulative if previous is None else cumulative - previous
        if float(daily.min()) < -0.01:
            raise ValueError(f"Negative daily GFS accumulation for {date} lead {lead}")
        daily = daily.clip(min=0)
        frame = daily.to_dataframe(name="forecast_precipitation").reset_index()
        for predictor_name in cfg["forecast"]["variables"]:
            if predictor_name == "precipitation":
                continue
            predictor = predictors[predictor_name]
            _, _, predictor_path = job_parts(date, lead, predictor_name)
            with xr.open_dataset(predictor_path, engine="cfgrib", backend_kwargs={"indexpath": ""}) as dataset:
                field = dataset[next(iter(dataset.data_vars))].sel(latitude=slice(cfg["geography"]["north"], cfg["geography"]["south"]), longitude=slice(cfg["geography"]["west"], cfg["geography"]["east"])).load()
            predictor_frame = field.to_dataframe(name=predictor["output_column"]).reset_index()[["latitude", "longitude", predictor["output_column"]]]
            frame = frame.merge(predictor_frame, on=["latitude", "longitude"], how="left", validate="one_to_one")
        frame["initialization_time"] = init
        frame["valid_time"] = init + pd.Timedelta(days=lead)
        frame["lead_day"] = lead
        output_columns = [predictors[name]["output_column"] for name in cfg["forecast"]["variables"]]
        forecast_parts.append(frame[["initialization_time", "valid_time", "latitude", "longitude", "lead_day"] + output_columns])
        previous = cumulative

forecast = pd.concat(forecast_parts, ignore_index=True)
forecast = add_derived_meteorological_features(forecast)
forecast.to_csv("data/interim/gfs_phase2_forecast.csv", index=False)

era5_paths = discover_era5_cache(cfg["paths"]["raw_dir"])
required_hours = required_era5_hours(dates, leads)
missing_hours = missing_era5_hours(required_hours, era5_paths)
if len(missing_hours):
    raise ValueError(f"ERA5 cache is missing {len(missing_hours)} required hourly records; run scripts/prepare_phase2_era5.py")
dataset = open_cached_era5(era5_paths)
tp = dataset["tp"]
time_name = "valid_time" if "valid_time" in tp.coords else "time"
reference_parts = []
for date in dates:
    init = pd.Timestamp(f"{date}T00:00:00")
    for lead in leads:
        start = init + pd.Timedelta(days=lead - 1)
        end = init + pd.Timedelta(days=lead)
        window = tp.where((tp[time_name] > start) & (tp[time_name] <= end), drop=True)
        if window.sizes.get(time_name, 0) != 24:
            raise ValueError(f"Expected 24 ERA5 hours for {date} lead {lead}")
        accumulated = window.sum(time_name) * 1000.0
        frame = accumulated.to_dataframe(name="reference_precipitation").reset_index()
        frame["valid_time"] = end.tz_localize("UTC")
        reference_parts.append(frame[["valid_time", "latitude", "longitude", "reference_precipitation"]])

reference = pd.concat(reference_parts, ignore_index=True)
reference.to_csv("data/interim/era5_phase2_reference.csv", index=False)
matched = match_forecast_reference(forecast, reference, cfg["reference"]["match_tolerance_hours"])
labeled = validate_dataset(add_error_and_labels(matched, cfg["labeling"]))
labeled.to_csv("data/processed/phase2_historical_fixed.csv", index=False)
print(f"DATASET_ROWS={len(labeled)}")
print(f"INITIALIZATIONS={labeled.initialization_time.nunique()}")
print(f"LEADS={labeled.lead_day.nunique()}")
