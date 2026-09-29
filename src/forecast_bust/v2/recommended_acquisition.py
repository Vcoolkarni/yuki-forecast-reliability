"""Opt-in 0.5° RECOMMENDED acquisition, isolated from V1 and other V2 caches."""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from hashlib import sha256
from pathlib import Path
import json
import os

import pandas as pd
import requests
import xarray as xr

from ..acquisition import load_cds_credentials, write_era5_request_for_dates
from ..era5_windows import dates_by_month, required_era5_hours
from .acquisition import download_message
from .budget_planning import _dates, estimate_budget_profiles
from .byte_budget import ByteBudget
from .planning import MessageJob

GIB = 1024 ** 3
PROFILE_ROOT = Path("data/raw/v2/recommended_0p50")


def recommended_dates(base: dict, budget_config: dict) -> list[str]:
    settings = budget_config["profiles"]["RECOMMENDED"]
    dates = _dates(base, budget_config, settings["cadence_days"], settings["max_initializations_per_year"])
    if len(dates) != 175 or {year: sum(day.startswith(str(year)) for day in dates)
                             for year in range(2021, 2026)} != {year: 35 for year in range(2021, 2026)}:
        raise ValueError("RECOMMENDED date selection must remain 35 per year, 2021–2025")
    return dates


def split_for_date(day: str) -> str:
    year = int(day[:4])
    if 2021 <= year <= 2023:
        return "train"
    if year == 2024:
        return "validation"
    if year == 2025:
        return "final_test_untouched"
    raise ValueError(f"Unsupported RECOMMENDED initialization year: {year}")


def jobs_for_date(base: dict, budget_config: dict, day: str, root: Path = PROFILE_ROOT,
                  cycle: str = "00", folder: Path | None = None) -> list[MessageJob]:
    """110 GFS + 50 GEFS jobs, with exact six-hour APCP interval metadata."""
    if cycle not in {"00", "06", "12", "18"}:
        raise ValueError("Unsupported NOAA forecast cycle")
    compact = day.replace("-", "")
    gfs = base["forecast"]["gfs"]
    gefs = base["forecast"]["gefs"]
    selected = budget_config["gfs"]["instantaneous_predictors"]
    gfs_product = budget_config["gfs"]["product"]
    gefs_product = budget_config["gefs"]["product"]
    gefs_dir = budget_config["gefs"]["directory"]
    folder = folder or root / split_for_date(day) / day[:4]
    jobs = []
    for lead in range(1, 11):
        for end_hour in range((lead - 1) * 24 + 6, lead * 24 + 1, 6):
            url = f"{gfs['bucket_url']}/gfs.{compact}/{cycle}/atmos/gfs.t{cycle}z.{gfs_product}.f{end_hour:03d}"
            target = folder / "gfs" / compact / f"gfs.t{cycle}z.{gfs_product}.f{end_hour:03d}.apcp_6h.grb2"
            jobs.append(MessageJob("gfs", day, end_hour, "precipitation", url, ":APCP:surface:", target,
                                   accumulation_start_hour=end_hour - 6))
        end_hour = lead * 24
        url = f"{gfs['bucket_url']}/gfs.{compact}/{cycle}/atmos/gfs.t{cycle}z.{gfs_product}.f{end_hour:03d}"
        for name in selected:
            predictor = gfs["predictors"][name]
            target = folder / "gfs" / compact / f"gfs.t{cycle}z.{gfs_product}.f{end_hour:03d}.{predictor['cache_suffix']}.grb2"
            jobs.append(MessageJob("gfs", day, end_hour, name, url,
                                   predictor["selector_template"].format(lead=lead), target))
        for end_hour in range((lead - 1) * 24 + 6, lead * 24 + 1, 6):
            filename = f"geavg.t{cycle}z.{gefs_product}.f{end_hour:03d}"
            url = f"{gefs['bucket_url']}/gefs.{compact}/{cycle}/atmos/{gefs_dir}/{filename}"
            target = folder / "gefs" / compact / f"{filename}.apcp_6h.grb2"
            jobs.append(MessageJob("gefs", day, end_hour, "precipitation_mean_6h", url,
                                   ":APCP:surface:", target, accumulation_start_hour=end_hour - 6))
        filename = f"gespr.t{cycle}z.{gefs_product}.f{lead * 24:03d}"
        url = f"{gefs['bucket_url']}/gefs.{compact}/{cycle}/atmos/{gefs_dir}/{filename}"
        target = folder / "gefs" / compact / f"{filename}.apcp_6h.grb2"
        jobs.append(MessageJob("gefs", day, lead * 24, "precipitation_spread_6h", url,
                               ":APCP:surface:", target, accumulation_start_hour=lead * 24 - 6))
    if len(jobs) != 160 or sum(job.source == "gfs" for job in jobs) != 110:
        raise ValueError("RECOMMENDED must plan 110 GFS and 50 GEFS messages per initialization")
    return jobs


def era5_month_jobs(base: dict, dates: list[str], root: Path = PROFILE_ROOT) -> list[dict]:
    required = required_era5_hours(dates, list(range(1, 11)))
    months = dates_by_month(required)
    if len(months) != 25:
        raise ValueError("RECOMMENDED requires 25 bounded ERA5 months")
    jobs = []
    for month, request_dates in months.items():
        year = month[:4]
        split = split_for_date(f"{year}-06-01")
        folder = root / split / year / "era5"
        needed = required[required.strftime("%Y%m") == month]
        jobs.append({"month": month, "request_dates": request_dates,
                     "required_hours": needed, "target": folder / f"era5_tp_{month}.nc",
                     "request_path": folder / "requests" / f"era5_tp_{month}.json"})
    return jobs


def _validate_era5(path: Path, expected_hours: pd.DatetimeIndex, bbox: dict) -> None:
    with xr.open_dataset(path, engine="netcdf4") as dataset:
        variable = "tp" if "tp" in dataset else "total_precipitation"
        if variable not in dataset or str(dataset[variable].attrs.get("units", "")).lower() not in {"m", "metres", "meters"}:
            raise ValueError(f"ERA5 cache lacks precipitation in metres: {path}")
        field = dataset[variable]
        time_name = "valid_time" if "valid_time" in field.coords else "time"
        times = pd.DatetimeIndex(pd.to_datetime(field[time_name].values))
        if times.has_duplicates or len(expected_hours.difference(times)):
            raise ValueError(f"ERA5 cache lacks exact required hourly endpoints: {path}")
        lats = {round(float(value), 8) for value in field.latitude.values}
        lons = {round(float(value), 8) for value in field.longitude.values}
        expected_lats = {round(bbox["south"] + index * .5, 8)
                         for index in range(round((bbox["north"] - bbox["south"]) / .5) + 1)}
        expected_lons = {round(bbox["west"] + index * .5, 8)
                         for index in range(round((bbox["east"] - bbox["west"]) / .5) + 1)}
        if not expected_lats <= lats or not expected_lons <= lons:
            raise ValueError(f"ERA5 lacks co-located 0.5-degree grid centers: {path}")
        if bool(field.isnull().any()):
            raise ValueError(f"ERA5 contains missing precipitation values: {path}")


def download_era5_month(job: dict, base: dict, budget: ByteBudget, credentials: Path) -> bool:
    """Transfer a CDS result through the same byte ledger as GRIB payloads."""
    target = Path(job["target"])
    request_path = Path(job["request_path"])
    request_config = {"geography": base["geography"]}
    write_era5_request_for_dates(request_config, job["request_dates"], request_path)
    plan = json.loads(request_path.read_text(encoding="utf-8"))
    request_hash = sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    provenance_path = target.with_suffix(".nc.provenance.json")
    pending_provenance = provenance_path.with_suffix(provenance_path.suffix + ".pending")
    if target.is_file():
        if not provenance_path.is_file() and pending_provenance.is_file():
            pending = json.loads(pending_provenance.read_text(encoding="utf-8"))
            if pending.get("request_sha256") == request_hash and pending.get("sha256") == sha256(target.read_bytes()).hexdigest():
                os.replace(pending_provenance, provenance_path)
        if not provenance_path.is_file():
            raise ValueError(f"ERA5 cache has no completion provenance: {target}")
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        if provenance.get("request_sha256") != request_hash or provenance.get("sha256") != sha256(target.read_bytes()).hexdigest():
            raise ValueError(f"ERA5 cache provenance/hash mismatch: {target}")
        _validate_era5(target, job["required_hours"], base["geography"])
        return False
    import cdsapi
    url, key = load_cds_credentials(credentials)
    client = cdsapi.Client(url=url, key=key, quiet=True, progress=False)
    result = client.retrieve(plan["dataset"], plan["request"])
    content_length = int(result.content_length)
    if content_length <= 0:
        raise ValueError("CDS supplied no finite ERA5 content length")
    part = target.with_suffix(".nc.part")
    part_metadata = target.with_suffix(".nc.part.json")
    offset = part.stat().st_size if part.exists() else 0
    if part.exists():
        if not part_metadata.is_file():
            raise ValueError("ERA5 partial cache cannot be safely resumed; preserving it for inspection")
        partial_info = json.loads(part_metadata.read_text(encoding="utf-8"))
        if (partial_info.get("request_sha256") != request_hash
                or partial_info.get("content_length") != content_length
                or not partial_info.get("etag")):
            raise ValueError("ERA5 partial cache cannot be safely resumed; preserving it for inspection")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        partial_info = None
    if offset > content_length:
        raise ValueError("ERA5 partial cache exceeds CDS result size")
    budget.ensure_capacity(content_length - offset)
    if offset < content_length:
        headers = {"Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
            headers["If-Range"] = partial_info["etag"]
        budget.reserve_transfer(content_length - offset)
        # cdsapi 0.7.7 delegates to ecmwf-datastores-client Results. Its public
        # location/session/request_options fields support a metered streaming GET;
        # Results.download() would bypass the hard transfer cap.
        with result.session.get(result.location, headers=headers, stream=True,
                                **result.request_options) as response:
            response.raise_for_status()
            if offset:
                if response.status_code != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    raise RuntimeError("CDS did not honor the ERA5 partial byte range")
                response_validator = response.headers.get("ETag") or response.headers.get("Last-Modified")
                if response_validator and response_validator != partial_info["etag"]:
                    raise RuntimeError("CDS ERA5 payload changed during partial resume")
            elif response.status_code != 200:
                raise RuntimeError("Unexpected CDS download response")
            else:
                etag = response.headers.get("ETag") or response.headers.get("Last-Modified")
                part_metadata.write_text(json.dumps({"request_sha256": request_hash,
                                                     "content_length": content_length,
                                                     "etag": etag}), encoding="utf-8")
            with part.open("ab") as handle:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        if handle.tell() + len(chunk) > content_length:
                            raise RuntimeError("CDS response exceeded declared payload size")
                        budget.consume(len(chunk))
                        handle.write(chunk)
    if part.stat().st_size != content_length:
        raise RuntimeError("ERA5 transfer incomplete; partial cache preserved")
    _validate_era5(part, job["required_hours"], base["geography"])
    digest = sha256(part.read_bytes()).hexdigest()
    pending_provenance.write_text(json.dumps({"request_sha256": request_hash, "sha256": digest,
                                               "byte_size": content_length, "required_hours": len(job["required_hours"]),
                                               "grid_centers": "ERA5 native 0.25-degree, co-located 0.5-degree centers verified"}, indent=2), encoding="utf-8")
    os.replace(part, target)
    part_metadata.unlink()
    os.replace(pending_provenance, provenance_path)
    return True


def run_recommended(base: dict, budget_config: dict, credentials: Path,
                    root: Path = PROFILE_ROOT, printer=print) -> None:
    plan = next(item for item in estimate_budget_profiles(base, budget_config)
                if item["PROFILE_NAME"] == "RECOMMENDED")
    if plan["INITIALIZATIONS"] != 175 or not plan["WITHIN_HARD_8_GIB_CAP"]:
        raise ValueError("RECOMMENDED plan no longer matches the approved 175-date, <=8-GiB design")
    selected = dict(base)
    selected["geography"] = {"south": budget_config["grid"]["south"], "north": budget_config["grid"]["north"],
                             "west": budget_config["grid"]["west"], "east": budget_config["grid"]["east"],
                             "grid_resolution_degrees": .25}
    dates = recommended_dates(base, budget_config)
    profile_id = sha256(json.dumps({"dates": dates, "budget": budget_config,
                                    "gfs_predictors": base["forecast"]["gfs"]["predictors"]}, sort_keys=True).encode()).hexdigest()
    limit = 8 * GIB
    with ByteBudget(root, limit, profile_id) as meter:
        cached = new = completed = 0
        printer(f"PROFILE=RECOMMENDED INITIALIZATIONS=175 HARD_LIMIT_GIB=8.000 "
                f"DOWNLOADED_GIB={meter.downloaded_bytes / GIB:.3f}")
        month_jobs = era5_month_jobs(selected, dates, root)
        for year in range(2021, 2026):
            for era5_job in (item for item in month_jobs if item["month"].startswith(str(year))):
                created = download_era5_month(era5_job, selected, meter, credentials)
                new += int(created)
                cached += int(not created)
                printer(f"STAGE=ERA5 YEAR={year} DATE={era5_job['month']} "
                        f"DOWNLOADED_GIB={meter.downloaded_bytes / GIB:.3f}/8.000 "
                        f"CHARGED_GIB={meter.charged_bytes / GIB:.3f}/8.000 "
                        f"INITIALIZATIONS_COMPLETED={completed}/175 CACHED_FILES={cached} NEW_FILES={new}")
            for day in (value for value in dates if value.startswith(str(year))):
                jobs = jobs_for_date(base, budget_config, day, root)
                def transfer(job: MessageJob) -> bool:
                    existed = job.target.is_file()
                    download_message(job, max_message_mib=16.0, budget=meter)
                    return existed

                # Bound concurrent NOAA requests within one initialization only;
                # the byte ledger serializes reservations/writes across workers.
                with ThreadPoolExecutor(max_workers=24) as pool:
                    for existed in pool.map(transfer, jobs):
                        cached += int(existed)
                        new += int(not existed)
                completed += 1
                printer(f"STAGE=FORECAST YEAR={year} DATE={day} SPLIT={split_for_date(day)} "
                        f"DOWNLOADED_GIB={meter.downloaded_bytes / GIB:.3f}/8.000 "
                        f"CHARGED_GIB={meter.charged_bytes / GIB:.3f}/8.000 "
                        f"INITIALIZATIONS_COMPLETED={completed}/175 CACHED_FILES={cached} NEW_FILES={new}")
