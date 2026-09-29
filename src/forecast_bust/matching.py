from __future__ import annotations

import pandas as pd


def match_forecast_reference(forecast: pd.DataFrame, reference: pd.DataFrame, tolerance_hours: int = 1) -> pd.DataFrame:
    """Match nearest grid/time reference; inputs must already share the same grid.

    Exact lat/lon matching is deliberate for MVP reproducibility. Regrid upstream when
    source grids differ instead of hiding interpolation inside this operation.
    """
    f = forecast.copy()
    r = reference.copy()
    f["valid_time"] = pd.to_datetime(f["valid_time"], utc=True)
    r["valid_time"] = pd.to_datetime(r["valid_time"], utc=True)
    f = f.sort_values("valid_time")
    r = r.sort_values("valid_time")
    matched = pd.merge_asof(
        f, r, on="valid_time", by=["latitude", "longitude"],
        tolerance=pd.Timedelta(hours=tolerance_hours), direction="nearest",
    )
    missing = matched["reference_precipitation"].isna().sum()
    if missing:
        raise ValueError(f"Reference match failed for {missing} forecast rows")
    return matched

