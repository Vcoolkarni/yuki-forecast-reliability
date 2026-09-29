from __future__ import annotations

import pandas as pd
import numpy as np

FEATURE_COLUMNS = [
    "lead_day", "latitude", "longitude", "forecast_precipitation",
    "forecast_temperature_2m", "forecast_relative_humidity_2m",
    "forecast_mean_sea_level_pressure", "forecast_u_wind_10m",
    "forecast_v_wind_10m", "forecast_wind_speed_10m",
    "precipitation_gradient_mm_per_degree", "month",
]


def add_derived_meteorological_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add deterministic features using only fields available at forecast issue time."""
    result = frame.copy()
    wind = {"forecast_u_wind_10m", "forecast_v_wind_10m"}
    if not wind.issubset(result.columns):
        raise ValueError(f"Cannot derive wind speed; missing columns: {sorted(wind - set(result.columns))}")
    result["forecast_wind_speed_10m"] = np.hypot(result["forecast_u_wind_10m"], result["forecast_v_wind_10m"])

    keys = ["initialization_time", "lead_day"]
    gradient_parts = []
    for identity, group in result.groupby(keys, sort=False):
        grid = group.pivot(index="latitude", columns="longitude", values="forecast_precipitation").sort_index().sort_index(axis=1)
        if grid.isna().any().any() or min(grid.shape) < 2:
            raise ValueError(f"Precipitation gradient requires a complete 2-D grid for {identity}")
        latitude_gradient, longitude_gradient = np.gradient(
            grid.to_numpy(dtype=float), grid.index.to_numpy(dtype=float), grid.columns.to_numpy(dtype=float)
        )
        magnitude = pd.DataFrame(np.hypot(latitude_gradient, longitude_gradient), index=grid.index, columns=grid.columns)
        part = magnitude.stack().rename("precipitation_gradient_mm_per_degree").reset_index()
        part["initialization_time"], part["lead_day"] = identity
        gradient_parts.append(part)
    gradients = pd.concat(gradient_parts, ignore_index=True)
    return result.merge(gradients, on=keys + ["latitude", "longitude"], how="left", validate="one_to_one")


def build_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    valid = pd.to_datetime(result["valid_time"], utc=True)
    result["month"] = valid.dt.month.astype("int8")
    missing = [column for column in FEATURE_COLUMNS if column not in result.columns]
    if missing:
        raise ValueError(f"Dataset is missing configured model predictors: {missing}. Rebuild it with the extended GFS pipeline.")
    return result

