from __future__ import annotations

from pathlib import Path
import pandas as pd
import xarray as xr


def precipitation_netcdf_to_frame(path: str | Path, variable: str, output_name: str) -> pd.DataFrame:
    """Normalize a NetCDF precipitation field to a tabular frame without inventing data."""
    with xr.open_dataset(path) as dataset:
        if variable not in dataset:
            raise KeyError(f"Variable {variable!r} not found in {path}; found {list(dataset.data_vars)}")
        data = dataset[variable]
        rename = {name: canonical for name, canonical in (("lat", "latitude"), ("lon", "longitude"), ("time", "valid_time")) if name in data.dims or name in data.coords}
        data = data.rename(rename)
        required = {"valid_time", "latitude", "longitude"}
        if not required.issubset(data.dims):
            raise ValueError(f"Expected dimensions {required}; found {set(data.dims)}")
        frame = data.to_dataframe(name=output_name).reset_index()
    return frame[["valid_time", "latitude", "longitude", output_name]]

