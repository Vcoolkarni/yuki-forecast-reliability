from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = [
    "initialization_time", "valid_time", "latitude", "longitude", "lead_day",
    "forecast_precipitation", "reference_precipitation", "forecast_error",
    "absolute_error", "is_bust",
]


def validate_dataset(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Dataset is missing required columns: {missing}")
    result = frame.copy()
    for column in ("initialization_time", "valid_time"):
        result[column] = pd.to_datetime(result[column], utc=True)
    for column in ("latitude", "longitude", "forecast_precipitation", "reference_precipitation", "forecast_error", "absolute_error"):
        result[column] = pd.to_numeric(result[column], errors="raise")
    result["lead_day"] = pd.to_numeric(result["lead_day"], errors="raise").astype("int16")
    result["is_bust"] = result["is_bust"].astype("int8")
    if not result["is_bust"].isin([0, 1]).all():
        raise ValueError("is_bust must be binary")
    return result

