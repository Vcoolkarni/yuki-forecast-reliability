from __future__ import annotations

import numpy as np
import pandas as pd

from ..features import FEATURE_COLUMNS, add_derived_meteorological_features, build_features

TARGET_COLUMNS = frozenset({"reference_precipitation", "forecast_error", "absolute_error", "is_bust"})
WEATHER_COLUMNS = [column for column in FEATURE_COLUMNS if column not in {"month", "lead_day", "latitude", "longitude"}]
IDENTITY_COLUMNS = ["initialization_time", "valid_time", "lead_day", "latitude", "longitude"]


def validate_feature_contract(features: list[str]) -> None:
    if not isinstance(features, list) or not features or len(set(features)) != len(features):
        raise ValueError("Model bundle must contain a unique, non-empty feature list")
    forbidden = set(features) & TARGET_COLUMNS
    if forbidden:
        raise ValueError(f"Target/reference leakage in model features: {sorted(forbidden)}")
    if features != FEATURE_COLUMNS:
        raise ValueError("Saved model feature contract differs from current preprocessing")


def prepare_forecast(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    validate_feature_contract(features)
    forbidden = set(frame.columns) & TARGET_COLUMNS
    if forbidden:
        raise ValueError(f"Inference input contains training-only target/reference fields: {sorted(forbidden)}")
    if frame.empty:
        raise ValueError("Inference requires one non-empty forecast initialization")
    if frame.columns.duplicated().any():
        raise ValueError("Inference input has duplicate column names")
    required = IDENTITY_COLUMNS + [column for column in WEATHER_COLUMNS if column not in {
        "forecast_wind_speed_10m", "precipitation_gradient_mm_per_degree"
    }]
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing required forecast fields: {sorted(missing)}")
    result = frame.copy()
    for column in ("initialization_time", "valid_time"):
        result[column] = pd.to_datetime(result[column], utc=True, errors="raise")
        if result[column].isna().any():
            raise ValueError(f"Missing timestamp in {column}")
    if result.initialization_time.nunique() != 1:
        raise ValueError("Inference accepts exactly one initialization at a time")
    for column in set(features) - {"month"}:
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="raise")
            if not np.isfinite(result[column]).all():
                raise ValueError(f"Non-finite forecast feature: {column}")
    if not result.lead_day.isin(range(1, 11)).all() or set(result.lead_day) != set(range(1, 11)):
        raise ValueError("Forecast must contain integer lead days 1 through 10")
    result["lead_day"] = result.lead_day.astype(int)
    expected_valid = result.initialization_time + pd.to_timedelta(result.lead_day, unit="D")
    if not result.valid_time.eq(expected_valid).all():
        raise ValueError("valid_time must equal initialization_time plus lead_day days")
    if not result.latitude.between(-90, 90).all() or not result.longitude.between(-180, 180).all():
        raise ValueError("Invalid geographic coordinates")
    if result.duplicated(["lead_day", "latitude", "longitude"]).any():
        raise ValueError("Duplicate lead/grid-cell rows")
    baseline = None
    for _, group in result.groupby("lead_day"):
        latitudes = np.sort(group.latitude.unique())
        longitudes = np.sort(group.longitude.unique())
        if min(len(latitudes), len(longitudes)) < 2 or len(group) != len(latitudes) * len(longitudes):
            raise ValueError("Each lead requires a complete rectangular grid")
        for coordinates in (latitudes, longitudes):
            if not np.allclose(np.diff(coordinates), np.diff(coordinates)[0], rtol=1e-6, atol=1e-8):
                raise ValueError("Hotspot inference requires a regular latitude/longitude grid")
        grid = (tuple(latitudes), tuple(longitudes))
        if baseline is not None and grid != baseline:
            raise ValueError("All lead days must share the same forecast grid")
        baseline = grid
    if not {"forecast_wind_speed_10m", "precipitation_gradient_mm_per_degree"}.issubset(result.columns):
        # Reuse the existing forecast-only preprocessing instead of introducing a new formula.
        result = result.drop(columns=["forecast_wind_speed_10m", "precipitation_gradient_mm_per_degree"], errors="ignore")
        result = add_derived_meteorological_features(result)
    result = build_features(result)
    if not np.isfinite(result[features].to_numpy(dtype=float)).all():
        raise ValueError("Model features must all be finite")
    return result.sort_values(["lead_day", "latitude", "longitude"]).reset_index(drop=True)
