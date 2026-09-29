"""BALANCED forecast-only acquisition and exact daily interval assembly."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import math

import numpy as np
import pandas as pd
import xarray as xr

from ..features import add_derived_meteorological_features
from ..era5_windows import required_era5_hours
from .dataset import attach_reference_and_error, validate_forecast, validate_historical
from .feature_schema import forecast_feature_schema
from .geography import configured_grid_centers
from .planning import MessageJob, message_jobs

EXPECTED_UNITS = {
    "precipitation": "kg m**-2", "precipitation_mean_6h": "kg m**-2",
    "precipitation_spread_6h": "kg m**-2", "temperature_2m": "K",
    "relative_humidity_2m": "%", "mean_sea_level_pressure": "Pa",
    "u_wind_10m": "m s**-1", "v_wind_10m": "m s**-1",
    "precipitable_water": "kg m**-2", "cape_surface": "J kg**-1",
}


def component_hours(lead_day: int, step_hours: int = 6) -> list[int]:
    """Ends of the four disjoint intervals covering (D−1)*24 to D*24."""
    if not 1 <= lead_day <= 10 or step_hours != 6:
        raise ValueError("BALANCED supports Day 1–10 with six-hour intervals")
    return list(range((lead_day - 1) * 24 + step_hours, lead_day * 24 + 1, step_hours))


def balanced_gefs_jobs(config: dict, initialization_date: str, leads: list[int]) -> list[MessageJob]:
    gefs = config["forecast"]["gefs"]
    compact = initialization_date.replace("-", "")
    raw = Path(config["paths"]["raw_dir"]) / "gefs" / compact
    jobs = []
    for lead in leads:
        for end_hour in component_hours(lead):
            for product, variable in (("geavg", "precipitation_mean_6h"),
                                      ("gespr", "precipitation_spread_6h")):
                filename = f"{product}.t00z.{gefs['product']}.f{end_hour:03d}"
                url = f"{gefs['bucket_url']}/gefs.{compact}/00/atmos/{gefs['directory']}/{filename}"
                jobs.append(MessageJob("gefs", initialization_date, end_hour, variable, url,
                                       gefs["precipitation_selector"], raw / f"{filename}.apcp.grb2",
                                       accumulation_start_hour=end_hour - 6))
    return jobs


def balanced_gfs_jobs(config: dict, initialization_date: str, leads: list[int]) -> list[MessageJob]:
    planned = deepcopy(config)
    planned["time"]["start_date"] = initialization_date
    planned["time"]["end_date"] = initialization_date
    planned["time"]["sampling"] = {"months": [date.fromisoformat(initialization_date).month],
                                    "every_n_days": 1, "anchor_day_of_month": date.fromisoformat(initialization_date).day}
    planned["forecast"]["lead_days"] = leads
    planned["forecast"]["gefs"]["enabled"] = False
    # The single-date sampler permits anchors through day 28. Dates on days
    # 29–31 use a direct one-day candidate list via the caller's full planner.
    if date.fromisoformat(initialization_date).day > 28:
        raise ValueError("Use the full sampled-date planner for initialization days after the 28th")
    return message_jobs(planned)


def _expected_grid(geography: dict) -> set[tuple[float, float]]:
    latitudes, longitudes = configured_grid_centers(geography)
    return {(lat, lon) for lat in latitudes for lon in longitudes}


def decode_message(job: MessageJob, geography: dict) -> pd.DataFrame:
    """Decode a cached single GRIB message and crop its exact regular grid."""
    with xr.open_dataset(job.target, engine="cfgrib", backend_kwargs={"indexpath": ""}) as dataset:
        if len(dataset.data_vars) != 1:
            raise ValueError(f"Expected exactly one GRIB variable in {job.target}")
        field = dataset[next(iter(dataset.data_vars))]
        expected_unit = EXPECTED_UNITS.get(job.variable)
        if expected_unit is not None and field.attrs.get("units") != expected_unit:
            raise ValueError(f"Unexpected {job.variable} GRIB units in {job.target}: {field.attrs.get('units')!r}")
        expected_step = "accum" if job.accumulation_start_hour is not None else "instant"
        if field.attrs.get("GRIB_stepType") != expected_step:
            raise ValueError(f"Unexpected {job.variable} GRIB step type in {job.target}")
        if job.accumulation_start_hour is not None:
            units = str(field.attrs.get("units", "")).lower().replace(" ", "")
            if units not in {"kgm**-2", "kgm-2", "mm"}:
                raise ValueError(f"Unsupported APCP units {units!r} for {job.target}")
        cropped = field.sel(latitude=slice(geography["north"], geography["south"]),
                            longitude=slice(geography["west"], geography["east"])).load()
        frame = cropped.to_dataframe(name="value").reset_index()[["latitude", "longitude", "value"]]
    frame["latitude"] = frame.latitude.round(8)
    frame["longitude"] = frame.longitude.round(8)
    if frame.duplicated(["latitude", "longitude"]).any() or set(zip(frame.latitude, frame.longitude)) != _expected_grid(geography):
        raise ValueError(f"GRIB grid does not exactly match configured crop: {job.target}")
    if not np.isfinite(frame.value.to_numpy(dtype=float)).all():
        raise ValueError(f"Missing/non-finite GRIB values: {job.target}")
    if job.accumulation_start_hour is not None and (frame.value < 0).any():
        raise ValueError(f"Negative six-hour precipitation: {job.target}")
    return frame.sort_values(["latitude", "longitude"]).reset_index(drop=True)


def assemble_daily_intervals(items: list[tuple[MessageJob, pd.DataFrame]], lead_day: int,
                             statistic: str) -> pd.DataFrame:
    """Require exactly four non-overlapping, aligned interval fields."""
    hours = component_hours(lead_day)
    if sorted(job.forecast_hour for job, _ in items) != hours or len(items) != 4:
        raise ValueError(f"Incomplete Day {lead_day} {statistic} intervals; expected component hours {hours}")
    ordered = sorted(items, key=lambda item: item[0].forecast_hour)
    reference = ordered[0][1][["latitude", "longitude"]].reset_index(drop=True)
    values = []
    for job, frame in ordered:
        if job.accumulation_start_hour != job.forecast_hour - 6:
            raise ValueError("Overlapping or incorrectly bounded accumulation interval")
        if not frame[["latitude", "longitude"]].reset_index(drop=True).equals(reference):
            raise ValueError("GFS/GEFS interval grid misalignment")
        value = frame.value.to_numpy(dtype=float)
        if not np.isfinite(value).all() or (value < 0).any():
            raise ValueError("Missing or negative interval precipitation")
        values.append(value)
    matrix = np.stack(values, axis=0)
    if statistic in {"gfs_daily", "gefs_daily_mean"}:
        result = matrix.sum(axis=0)
        column = "forecast_precipitation" if statistic == "gfs_daily" else "gefs_precipitation_mean_mm"
    elif statistic in {"gefs_6h_spread_mean", "gefs_6h_spread_max", "gefs_6h_spread_rms"}:
        result = {"gefs_6h_spread_mean": lambda: matrix.mean(axis=0),
                  "gefs_6h_spread_max": lambda: matrix.max(axis=0),
                  "gefs_6h_spread_rms": lambda: np.sqrt(np.square(matrix).mean(axis=0))}[statistic]()
        column = statistic + "_mm"
    else:
        raise ValueError(f"Unsupported interval statistic {statistic}")
    return reference.assign(**{column: result})


def assemble_balanced_forecast(config: dict, initialization_date: str, leads: list[int],
                               gfs_jobs: list[MessageJob], gefs_jobs: list[MessageJob],
                               cycle: str = "00") -> tuple[pd.DataFrame, dict]:
    """Build exact-grid forecast features from already downloaded messages."""
    geography = config["geography"]
    decoded = {job.target: decode_message(job, geography) for job in gfs_jobs + gefs_jobs}
    if cycle not in {"00", "06", "12", "18"}:
        raise ValueError("Unsupported NOAA forecast cycle")
    init = pd.Timestamp(f"{initialization_date}T{cycle}:00:00Z")
    parts, provenance = [], {}
    for lead in leads:
        hours = component_hours(lead)
        gfs_intervals = [(job, decoded[job.target]) for job in gfs_jobs
                         if job.variable == "precipitation" and job.forecast_hour in hours]
        day = assemble_daily_intervals(gfs_intervals, lead, "gfs_daily")
        for job in gfs_jobs:
            if job.variable == "precipitation" or job.forecast_hour != lead * 24:
                continue
            column = config["forecast"]["gfs"]["predictors"][job.variable]["output_column"]
            day = day.merge(decoded[job.target].rename(columns={"value": column}),
                            on=["latitude", "longitude"], how="left", validate="one_to_one")
        mean_items = [(job, decoded[job.target]) for job in gefs_jobs
                      if job.variable == "precipitation_mean_6h" and job.forecast_hour in hours]
        spread_items = [(job, decoded[job.target]) for job in gefs_jobs
                        if job.variable == "precipitation_spread_6h" and job.forecast_hour in hours]
        day = day.merge(assemble_daily_intervals(mean_items, lead, "gefs_daily_mean"),
                        on=["latitude", "longitude"], how="left", validate="one_to_one")
        if len(spread_items) == 1:
            spread_job, spread_frame = spread_items[0]
            if (spread_job.forecast_hour != lead * 24
                    or spread_job.accumulation_start_hour != lead * 24 - 6):
                raise ValueError("RECOMMENDED GEFS spread must be the final six-hour interval")
            day = day.merge(spread_frame.rename(columns={"value": "gefs_end_window_spread_6h_mm"}),
                            on=["latitude", "longitude"], how="left", validate="one_to_one")
        elif len(spread_items) == 4:
            for statistic in ("gefs_6h_spread_mean", "gefs_6h_spread_max", "gefs_6h_spread_rms"):
                day = day.merge(assemble_daily_intervals(spread_items, lead, statistic),
                                on=["latitude", "longitude"], how="left", validate="one_to_one")
        else:
            raise ValueError(f"Day {lead} requires exactly one end-window or four GEFS spread intervals")
        day["gfs_minus_gefs_mean_precipitation_mm"] = day.forecast_precipitation - day.gefs_precipitation_mean_mm
        day["initialization_time"] = init
        day["valid_time"] = init + pd.Timedelta(days=lead)
        day["lead_day"] = lead
        parts.append(day)
        provenance[str(lead)] = {"gfs_apcp_component_forecast_hours": hours,
                                 "gefs_mean_component_forecast_hours": hours,
                                 "gefs_spread_component_forecast_hours": [job.forecast_hour for job, _ in spread_items],
                                 "verification_start_exclusive": (init + pd.Timedelta(days=lead - 1)).isoformat(),
                                 "verification_end_inclusive": (init + pd.Timedelta(days=lead)).isoformat()}
    result = add_derived_meteorological_features(pd.concat(parts, ignore_index=True))
    schema_config = deepcopy(config)
    schema_config["forecast"]["gefs"]["mode"] = (
        "published_daily_mean_end_window_spread" if "gefs_end_window_spread_6h_mm" in result
        else "published_6h_mean_spread")
    return validate_forecast(result, list(forecast_feature_schema(schema_config))), provenance


def era5_reference_for_leads(dataset: xr.Dataset, initialization_date: str, leads: list[int],
                             geography: dict) -> pd.DataFrame:
    """Sum exactly 24 ERA5 hourly endpoint accumulations over each GFS window."""
    variable = "tp" if "tp" in dataset else "total_precipitation"
    if variable not in dataset:
        raise ValueError("ERA5 total precipitation is absent")
    field = dataset[variable]
    units = str(field.attrs.get("units", "")).lower().replace(" ", "")
    if units not in {"m", "metres", "meters"}:
        raise ValueError(f"Expected ERA5 precipitation in metres, got {units!r}")
    time_name = "valid_time" if "valid_time" in field.coords else "time"
    times = pd.DatetimeIndex(pd.to_datetime(field[time_name].values, utc=True))
    if times.has_duplicates:
        raise ValueError("ERA5 cache contains duplicate hourly timestamps")
    init = pd.Timestamp(f"{initialization_date}T00:00:00Z")
    parts = []
    for lead in leads:
        expected = required_era5_hours([initialization_date], [lead]).tz_localize("UTC")
        if not expected.difference(times).empty:
            raise ValueError(f"Missing ERA5 hourly endpoints for Day {lead}: {expected.difference(times).tolist()}")
        selected = field.sel({time_name: expected.tz_localize(None).to_numpy()})
        if selected.sizes[time_name] != 24:
            raise ValueError(f"Expected 24 ERA5 hourly fields for Day {lead}")
        target_latitudes, target_longitudes = configured_grid_centers(geography)
        # ERA5 may remain on its native 0.25° grid while GFS/GEFS use 0.5°.
        # Select only exact co-located centers; never interpolate or fabricate.
        try:
            crop = selected.sel(latitude=target_latitudes, longitude=target_longitudes)
        except KeyError as error:
            raise ValueError("ERA5 lacks exact co-located forecast grid centers") from error
        values = crop.sum(time_name, skipna=False) * 1000.0
        frame = values.to_dataframe(name="reference_precipitation").reset_index()
        frame = frame[["latitude", "longitude", "reference_precipitation"]]
        frame["latitude"] = frame.latitude.round(8)
        frame["longitude"] = frame.longitude.round(8)
        if set(zip(frame.latitude, frame.longitude)) != _expected_grid(geography):
            raise ValueError("ERA5/GFS grid centers do not align exactly")
        if not np.isfinite(frame.reference_precipitation.to_numpy(dtype=float)).all() or (frame.reference_precipitation < 0).any():
            raise ValueError("ERA5 reference has missing or negative precipitation")
        frame["valid_time"] = init + pd.Timedelta(days=lead)
        parts.append(frame)
    return pd.concat(parts, ignore_index=True)


def attach_balanced_reference(forecast: pd.DataFrame, reference: pd.DataFrame,
                              feature_names: list[str]) -> pd.DataFrame:
    return validate_historical(attach_reference_and_error(forecast, reference), feature_names)
