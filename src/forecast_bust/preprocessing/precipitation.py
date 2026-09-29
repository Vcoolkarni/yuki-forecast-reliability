from __future__ import annotations

from pathlib import Path
import pandas as pd
import xarray as xr


def gfs_subset_to_frame(path: str | Path, initialization_time: str, lead_day: int) -> pd.DataFrame:
    """Convert a cropped accumulated GFS precipitation field to the forecast schema."""
    with xr.open_dataset(path) as dataset:
        data = dataset["forecast_precipitation"]
        units = str(data.attrs.get("units", "")).lower().replace(" ", "")
        if units not in {"kgm**-2", "kgm-2", "mm"}:
            raise ValueError(f"Unsupported GFS precipitation units: {units!r}")
        frame = data.to_dataframe(name="forecast_precipitation").reset_index()
    init = pd.Timestamp(initialization_time)
    if init.tzinfo is None:
        init = init.tz_localize("UTC")
    else:
        init = init.tz_convert("UTC")
    frame["initialization_time"] = init
    frame["valid_time"] = init + pd.Timedelta(days=lead_day)
    frame["lead_day"] = int(lead_day)
    return frame[["initialization_time", "valid_time", "latitude", "longitude", "lead_day", "forecast_precipitation"]]


def era5_hourly_to_accumulation(path: str | Path, start: str, end: str) -> pd.DataFrame:
    """Sum ERA5 hourly total precipitation over (start, end], converting metres to mm."""
    with xr.open_dataset(path) as dataset:
        variable = "tp" if "tp" in dataset else "total_precipitation"
        if variable not in dataset:
            raise KeyError("ERA5 file has no total precipitation variable")
        data = dataset[variable]
        time_name = "valid_time" if "valid_time" in data.coords else "time"
        window = data.where((data[time_name] > pd.Timestamp(start)) & (data[time_name] <= pd.Timestamp(end)), drop=True)
        if window.sizes.get(time_name, 0) != 24:
            raise ValueError(f"Expected 24 ERA5 hourly fields in the verification window; found {window.sizes.get(time_name, 0)}")
        accumulated = window.sum(time_name) * 1000.0
        accumulated.attrs["units"] = "mm"
        frame = accumulated.to_dataframe(name="reference_precipitation").reset_index()
    frame["valid_time"] = pd.Timestamp(end)
    return frame[["valid_time", "latitude", "longitude", "reference_precipitation"]]
