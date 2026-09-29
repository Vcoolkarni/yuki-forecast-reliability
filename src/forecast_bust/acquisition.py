from __future__ import annotations

from pathlib import Path
import json
from datetime import date, timedelta
import yaml
import requests
from dataclasses import dataclass


def write_era5_request(cfg: dict, output: str | Path) -> Path:
    """Write (do not submit) the smallest ERA5 request implied by the config."""
    bbox = cfg["geography"]
    start = date.fromisoformat(cfg["time"]["start_date"])
    end = date.fromisoformat(cfg["time"]["end_date"])
    if end < start:
        raise ValueError("end_date must not precede start_date")
    dates = []
    current = start
    while current <= end:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return write_era5_request_for_dates(cfg, dates, output)


def write_era5_request_for_dates(cfg: dict, dates: list[str], output: str | Path) -> Path:
    """Write a bounded ERA5 request for explicit dates within one calendar month."""
    bbox = cfg["geography"]
    if not dates:
        raise ValueError("At least one ERA5 date is required")
    parsed_dates = [date.fromisoformat(value) for value in dates]
    year_months = {(value.year, value.month) for value in parsed_dates}
    if len(year_months) != 1:
        raise ValueError("ERA5 cache requests must be split by calendar month")
    request = {
        "product_type": ["reanalysis"], "variable": ["total_precipitation"],
        "year": sorted({value.strftime("%Y") for value in parsed_dates}),
        "month": sorted({value.strftime("%m") for value in parsed_dates}),
        "day": sorted({value.strftime("%d") for value in parsed_dates}),
        "time": [f"{hour:02d}:00" for hour in range(24)], "data_format": "netcdf",
        "download_format": "unarchived",
        "area": [bbox["north"], bbox["west"], bbox["south"], bbox["east"]],
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"dataset": "reanalysis-era5-single-levels", "request": request}, indent=2), encoding="utf-8")
    return output


def load_cds_credentials(path: str | Path) -> tuple[str, str]:
    """Load local CDS credentials without copying them into project outputs."""
    credential_path = Path(path)
    if not credential_path.is_file():
        raise FileNotFoundError(f"CDS credential file not found: {credential_path}")
    text = credential_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("CDS credential file is empty")
    parsed = yaml.safe_load(text)
    default_url = "https://cds.climate.copernicus.eu/api"
    if isinstance(parsed, dict):
        url = str(parsed.get("url", default_url)).strip()
        key = str(parsed.get("key", "")).strip()
    else:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) == 1:
            url, key = default_url, lines[0]
        elif len(lines) == 2 and lines[0].startswith("http"):
            url, key = lines
        else:
            raise ValueError("Unsupported CDS credential format")
    if not url.startswith("https://") or not key:
        raise ValueError("CDS credentials require an HTTPS URL and a non-empty key")
    return url, key


def download_era5(request_plan: str | Path, credential_path: str | Path, target: str | Path, expected_hours=None) -> Path:
    """Submit an already-reviewed request plan to CDS."""
    import cdsapi
    plan = json.loads(Path(request_plan).read_text(encoding="utf-8"))
    target = Path(target)
    if target.is_file() and target.stat().st_size > 0:
        if expected_hours is None:
            return target
        import pandas as pd
        import xarray as xr
        with xr.open_dataset(target) as dataset:
            time_name = "valid_time" if "valid_time" in dataset.coords else "time"
            cached = pd.DatetimeIndex(pd.to_datetime(dataset[time_name].values))
        if not pd.DatetimeIndex(expected_hours).difference(cached).size:
            return target
    url, key = load_cds_credentials(credential_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    client = cdsapi.Client(url=url, key=key, quiet=True)
    client.retrieve(plan["dataset"], plan["request"], str(target))
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("CDS reported completion but produced no data file")
    return target


@dataclass(frozen=True)
class GribMessage:
    start: int
    end: int | None
    description: str

    @property
    def size(self) -> int | None:
        return None if self.end is None else self.end - self.start + 1


def inspect_gfs_grib_message(grib_url: str, selector: str) -> GribMessage:
    """Resolve one public GFS inventory entry without downloading the GRIB message."""
    inventory_response = requests.get(f"{grib_url}.idx", timeout=60)
    inventory_response.raise_for_status()
    lines = [line for line in inventory_response.text.splitlines() if line.strip()]
    matches = [(index, line) for index, line in enumerate(lines) if selector in line]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one inventory match for {selector!r}; found {len(matches)}")
    index, line = matches[0]
    fields = line.split(":")
    start = int(fields[1])
    end = int(lines[index + 1].split(":")[1]) - 1 if index + 1 < len(lines) else None
    return GribMessage(start=start, end=end, description=":".join(fields[3:]))


def download_gfs_grib_message(grib_url: str, target: str | Path, selector: str = ":APCP:surface:") -> tuple[Path, str]:
    """Download one GRIB2 message via its public NOAA `.idx` byte offsets."""
    target = Path(target)
    if target.is_file() and target.stat().st_size > 0:
        return target, "cached"
    message = inspect_gfs_grib_message(grib_url, selector)
    range_value = f"bytes={message.start}-{message.end}" if message.end is not None else f"bytes={message.start}-"
    response = requests.get(grib_url, headers={"Range": range_value}, timeout=120)
    response.raise_for_status()
    if response.status_code != 206:
        raise RuntimeError("NOAA server ignored the byte range; refusing a full global download")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(response.content)
    if target.stat().st_size == 0:
        raise RuntimeError("Downloaded GFS message is empty")
    return target, message.description

