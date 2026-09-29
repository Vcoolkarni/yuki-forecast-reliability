from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd
import xarray as xr


def required_era5_hours(initialization_dates: list[str], lead_days: list[int]) -> pd.DatetimeIndex:
    """ERA5 hourly endpoints needed for matching daily windows `(start, end]`."""
    required: set[pd.Timestamp] = set()
    for value in initialization_dates:
        initialization = pd.Timestamp(f"{value}T00:00:00")
        for lead in lead_days:
            start = initialization + pd.Timedelta(days=lead - 1)
            end = initialization + pd.Timedelta(days=lead)
            required.update(pd.date_range(start + pd.Timedelta(hours=1), end, freq="h"))
    return pd.DatetimeIndex(sorted(required))


def dates_by_month(hours: pd.DatetimeIndex) -> dict[str, list[str]]:
    grouped: dict[str, set[str]] = defaultdict(set)
    for timestamp in hours:
        grouped[timestamp.strftime("%Y%m")].add(timestamp.strftime("%Y-%m-%d"))
    return {month: sorted(values) for month, values in sorted(grouped.items())}


def discover_era5_cache(raw_dir: str | Path) -> list[Path]:
    raw = Path(raw_dir)
    paths = list(raw.glob("era5_tp_*.nc"))
    paths.extend((raw / "era5_phase2").glob("era5_tp_*.nc"))
    return sorted(set(paths))


def cached_era5_hours(paths: list[Path]) -> pd.DatetimeIndex:
    values = []
    for path in paths:
        with xr.open_dataset(path) as dataset:
            time_name = "valid_time" if "valid_time" in dataset.coords else "time"
            values.extend(pd.to_datetime(dataset[time_name].values).tolist())
    return pd.DatetimeIndex(sorted(set(values)))


def missing_era5_hours(required: pd.DatetimeIndex, paths: list[Path]) -> pd.DatetimeIndex:
    available = cached_era5_hours(paths) if paths else pd.DatetimeIndex([])
    return required.difference(available)


def contiguous_hour_ranges(hours: pd.DatetimeIndex) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Collapse missing hourly timestamps into inclusive contiguous ranges."""
    if not len(hours):
        return []
    ordered = pd.DatetimeIndex(sorted(hours.unique()))
    ranges = []
    start = previous = ordered[0]
    for timestamp in ordered[1:]:
        if timestamp - previous != pd.Timedelta(hours=1):
            ranges.append((start, previous))
            start = timestamp
        previous = timestamp
    ranges.append((start, previous))
    return ranges


def open_cached_era5(paths: list[Path]) -> xr.Dataset:
    if not paths:
        raise FileNotFoundError("No ERA5 cache files were found; run scripts/prepare_phase2_era5.py")
    datasets = [xr.open_dataset(path) for path in paths]
    try:
        time_name = "valid_time" if "valid_time" in datasets[0].coords else "time"
        combined = xr.concat(datasets, dim=time_name, combine_attrs="override").load()
    finally:
        for dataset in datasets:
            dataset.close()
    return combined.sortby(time_name).drop_duplicates(time_name)
