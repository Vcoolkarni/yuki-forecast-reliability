"""V2 multi-year historical schema, exact verification matching, and manifests."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json

import numpy as np
import pandas as pd

from . import SCHEMA_VERSION

IDENTITY = ["initialization_time", "valid_time", "latitude", "longitude", "lead_day"]
TARGETS = {"reference_precipitation", "forecast_error", "absolute_error", "target_absolute_error_mm", "is_bust"}
BASE_FORECAST = ["forecast_precipitation", "forecast_temperature_2m", "forecast_relative_humidity_2m",
                 "forecast_mean_sea_level_pressure", "forecast_u_wind_10m", "forecast_v_wind_10m",
                 "forecast_wind_speed_10m", "precipitation_gradient_mm_per_degree"]
NULLABLE_FORECAST = {"gefs_precipitation_cv"}  # Undefined for ensemble means <= 1 mm.


def validate_forecast(frame: pd.DataFrame, required_features: list[str]) -> pd.DataFrame:
    if forbidden := TARGETS & set(frame.columns):
        raise ValueError(f"Forecast-time data contains reference/target fields: {sorted(forbidden)}")
    required = set(IDENTITY + BASE_FORECAST + required_features)
    if missing := required - set(frame.columns):
        raise ValueError(f"V2 forecast is missing columns: {sorted(missing)}")
    result = frame.copy()
    result["initialization_time"] = pd.to_datetime(result.initialization_time, utc=True)
    result["valid_time"] = pd.to_datetime(result.valid_time, utc=True)
    if result[IDENTITY].isna().any().any() or result.duplicated(["initialization_time", "lead_day", "latitude", "longitude"]).any():
        raise ValueError("V2 forecast has null or duplicate initialization/lead/grid keys")
    if not ((result.valid_time - result.initialization_time) == pd.to_timedelta(result.lead_day, unit="D")).all():
        raise ValueError("V2 valid_time must equal initialization plus lead_day")
    if not result.lead_day.between(1, 10).all():
        raise ValueError("V2 forecast contains an unsupported lead day")
    numeric = ["latitude", "longitude"] + BASE_FORECAST + [name for name in required_features if name not in NULLABLE_FORECAST]
    if not np.isfinite(result[numeric].to_numpy(dtype=float)).all():
        raise ValueError("V2 forecast contains missing/non-finite predictors")
    if (result.forecast_precipitation < 0).any():
        raise ValueError("Precipitation cannot be negative")
    return result


def attach_reference_and_error(forecast: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    """Exact valid time/coordinate match; never interpolate missing ERA5 hours/cells."""
    required = {"valid_time", "latitude", "longitude", "reference_precipitation"}
    if required - set(reference.columns):
        raise ValueError("ERA5 reference schema is incomplete")
    verified = reference.copy()
    verified["valid_time"] = pd.to_datetime(verified.valid_time, utc=True)
    if verified.duplicated(["valid_time", "latitude", "longitude"]).any():
        raise ValueError("Duplicate ERA5 reference grid/time key")
    result = forecast.merge(verified[["valid_time", "latitude", "longitude", "reference_precipitation"]], on=["valid_time", "latitude", "longitude"],
                            how="left", validate="many_to_one", indicator=True)
    if (result["_merge"] != "both").any() or not np.isfinite(result.reference_precipitation.to_numpy(dtype=float)).all():
        raise ValueError("Missing exact ERA5 reference match; refusing to fabricate values")
    result = result.drop(columns="_merge")
    result["forecast_error"] = result.forecast_precipitation - result.reference_precipitation
    result["absolute_error"] = result.forecast_error.abs()
    result["target_absolute_error_mm"] = result.absolute_error
    return result


def validate_historical(frame: pd.DataFrame, required_features: list[str]) -> pd.DataFrame:
    forecast = validate_forecast(frame.drop(columns=list(TARGETS & set(frame.columns))), required_features)
    required = {"reference_precipitation", "forecast_error", "absolute_error", "target_absolute_error_mm"}
    if missing := required - set(frame.columns):
        raise ValueError(f"V2 historical target columns missing: {sorted(missing)}")
    values = frame[list(required)].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (frame.reference_precipitation < 0).any():
        raise ValueError("Historical reference/error values must be finite and precipitation nonnegative")
    expected = forecast.forecast_precipitation.to_numpy() - frame.reference_precipitation.to_numpy()
    if not np.allclose(expected, frame.forecast_error) or not np.allclose(np.abs(expected), frame.absolute_error) or not np.allclose(frame.absolute_error, frame.target_absolute_error_mm):
        raise ValueError("Expected absolute-error target is inconsistent with GFS−ERA5")
    return frame.copy()


def dataset_manifest(dataset_path: str | Path, config_path: str | Path, frame: pd.DataFrame) -> dict:
    """A reproducibility record; caller writes it only after a validated build."""
    path, config_file = Path(dataset_path), Path(config_path)
    return {"schema_version": SCHEMA_VERSION, "dataset_sha256": sha256(path.read_bytes()).hexdigest(),
            "config_sha256": sha256(config_file.read_bytes()).hexdigest(),
            "initializations": sorted(pd.to_datetime(frame.initialization_time, utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ").unique().tolist()),
            "leads": sorted(int(value) for value in frame.lead_day.unique()),
            "rows": len(frame), "latitude_range": [float(frame.latitude.min()), float(frame.latitude.max())],
            "longitude_range": [float(frame.longitude.min()), float(frame.longitude.max())],
            "columns": list(frame.columns), "reference": "ERA5 reanalysis hourly total precipitation, exact 24-hour (start,end] window",
            "provenance": "GFS/GEFS GRIB byte-range inventory plus ERA5 CDS monthly caches"}


def write_dataset_manifest(manifest: dict, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    return destination
