from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import statistics

from ..era5_windows import cached_era5_hours, dates_by_month, required_era5_hours
from .configuration import initialization_dates
from .geography import configured_grid_centers


@dataclass(frozen=True)
class MessageJob:
    source: str
    initialization_date: str
    forecast_hour: int
    variable: str
    url: str
    selector: str
    target: Path
    member: str | None = None
    accumulation_start_hour: int | None = None
    reuse_legacy_cache: bool = False


def message_jobs(config: dict) -> list[MessageJob]:
    dates = initialization_dates(config)
    leads = config["forecast"]["lead_days"]
    gfs = config["forecast"]["gfs"]
    gefs = config["forecast"]["gefs"]
    raw = Path(config["paths"]["raw_dir"])
    legacy = Path(config["paths"]["legacy_gfs_dir"])
    legacy_cached = {path.name for path in legacy.glob("*.grb2") if path.stat().st_size > 0}
    jobs: list[MessageJob] = []
    for day in dates:
        compact = day.replace("-", "")
        for lead in leads:
            hour = lead * 24
            for name, predictor in gfs["predictors"].items():
                if name == "precipitation":
                    for end_hour in range((lead - 1) * 24 + 6, hour + 1, 6):
                        url = f"{gfs['bucket_url']}/gfs.{compact}/00/atmos/gfs.t00z.{gfs['product']}.f{end_hour:03d}"
                        filename = f"gfs_{compact}_00_f{end_hour:03d}_{predictor['cache_suffix']}.grb2"
                        jobs.append(MessageJob("gfs", day, end_hour, name, url,
                                               predictor["selector_template"], raw / "gfs" / filename,
                                               accumulation_start_hour=end_hour - 6))
                    continue
                base = f"{gfs['bucket_url']}/gfs.{compact}/00/atmos/gfs.t00z.{gfs['product']}.f{hour:03d}"
                filename = f"gfs_{compact}_00_f{hour:03d}_{predictor['cache_suffix']}.grb2"
                old = legacy / filename
                target = old if name in {"precipitation", "temperature_2m", "relative_humidity_2m",
                                         "mean_sea_level_pressure", "u_wind_10m", "v_wind_10m"} and filename in legacy_cached else raw / "gfs" / filename
                jobs.append(MessageJob("gfs", day, hour, name, base,
                                       predictor["selector_template"].format(lead=lead), target,
                                       reuse_legacy_cache=target == old))
        if gefs["enabled"]:
            for hour in range(gefs["precipitation_step_hours"], max(leads) * 24 + 1,
                              gefs["precipitation_step_hours"]):
                for member in gefs["members"]:
                    prefix = f"ge{member}"
                    filename = f"{prefix}.t00z.{gefs['product']}.f{hour:03d}"
                    url = f"{gefs['bucket_url']}/gefs.{compact}/00/atmos/{gefs['directory']}/{filename}"
                    target = raw / "gefs" / compact / f"{filename}.apcp.grb2"
                    jobs.append(MessageJob("gefs", day, hour, "precipitation", url,
                                           gefs["precipitation_selector"], target, member,
                                           hour - gefs["precipitation_step_hours"]))
    return jobs


def era5_month_plan(config: dict) -> dict[str, dict]:
    dates = initialization_dates(config)
    required = required_era5_hours(dates, config["forecast"]["lead_days"])
    by_month = dates_by_month(required)
    raw = Path(config["paths"]["raw_dir"]) / "era5"
    result = {}
    for month, day_values in by_month.items():
        target = raw / f"era5_tp_{month}.nc"
        needed = required[required.strftime("%Y%m") == month]
        month_caches = [path for path in raw.glob(f"era5_tp_{month}*.nc") if path.stat().st_size > 0]
        if month_caches:
            available = cached_era5_hours(month_caches)
            missing = needed.difference(available)
        else:
            missing = needed
        result[month] = {"dates": day_values, "required_hours": len(needed), "missing_hours": len(missing),
                         "missing_dates": sorted(set(missing.strftime("%Y-%m-%d"))), "target": target}
    return result


def _size_assumptions(config: dict) -> tuple[float, float, float]:
    estimates = config["estimation"]
    legacy = Path(config["paths"]["legacy_gfs_dir"])
    observed = [path.stat().st_size for path in legacy.glob("*.grb2") if path.stat().st_size > 0]
    gfs = statistics.median(observed) if observed else float(estimates["fallback_gfs_message_mib"]) * 1048576
    return gfs, float(estimates["fallback_gefs_message_mib"]) * 1048576, float(estimates["fallback_era5_month_mib"]) * 1048576


def estimate_acquisition(config: dict) -> dict:
    """Offline estimate only: no inventory requests, downloads, CDS calls, or writes."""
    jobs = message_jobs(config)
    months = era5_month_plan(config)
    gfs_bytes, gefs_bytes, era5_bytes = _size_assumptions(config)
    counts: dict[str, int] = defaultdict(int)
    missing: dict[str, int] = defaultdict(int)
    raw = Path(config["paths"]["raw_dir"])
    v2_cached = {path for pattern in ((raw / "gfs", "*.grb2"), (raw / "gefs", "*/*.grb2"))
                 for path in pattern[0].glob(pattern[1]) if path.stat().st_size > 0 and
                 path.with_suffix(path.suffix + ".provenance.json").is_file()}
    legacy_cached = {path for path in Path(config["paths"]["legacy_gfs_dir"]).glob("*.grb2")
                     if path.stat().st_size > 0}
    cached_targets = v2_cached | legacy_cached
    cached = 0
    download_bytes = 0.0
    for job in jobs:
        counts[job.source] += 1
        if job.target in cached_targets:
            cached += 1
        else:
            missing[job.source] += 1
            download_bytes += gfs_bytes if job.source == "gfs" else gefs_bytes
    uncached_months = sum(item["missing_hours"] > 0 for item in months.values())
    download_bytes += uncached_months * era5_bytes
    dates = initialization_dates(config)
    latitudes, longitudes = configured_grid_centers(config["geography"])
    return {
        "INITIALIZATIONS": len(dates), "DATE_RANGE": [dates[0], dates[-1]],
        "LEADS": len(config["forecast"]["lead_days"]), "GFS_MESSAGES": counts["gfs"],
        "GRID_CELLS_PER_LEAD": len(latitudes) * len(longitudes),
        "PLANNED_GRID_ROWS": len(dates) * len(config["forecast"]["lead_days"]) * len(latitudes) * len(longitudes),
        "GEFS_MESSAGES": counts["gefs"], "ERA5_MONTHS": len(months),
        "CACHED": cached + len(months) - uncached_months,
        "NEW_REQUESTS": missing["gfs"] + missing["gefs"] + uncached_months,
        "INDEX_REQUESTS": missing["gfs"] + missing["gefs"],
        "ESTIMATED_NETWORK_OPERATIONS_EXCLUDING_RETRIES": 2 * (missing["gfs"] + missing["gefs"]) + uncached_months,
        "GFS_NEW": missing["gfs"], "GEFS_NEW": missing["gefs"], "ERA5_MONTHS_INCOMPLETE": uncached_months,
        "ESTIMATED_DOWNLOAD_GIB": round(download_bytes / 1073741824, 2),
        "ESTIMATE_BASIS": {"gfs_message_mib": round(gfs_bytes / 1048576, 3),
                           "gefs_message_mib_assumed": round(gefs_bytes / 1048576, 3),
                           "era5_month_mib_assumed": round(era5_bytes / 1048576, 1)},
        "VARIABLES": list(config["forecast"]["gfs"]["predictors"]),
        "GEFS_MEMBERS": len(config["forecast"]["gefs"]["members"]) if config["forecast"]["gefs"]["enabled"] else 0,
        "GEOGRAPHY": config["geography"],
        "NOTE": "Offline planning estimate, not verified source availability or exact network bytes. Each new GRIB message also needs a small .idx GET; CDS may require follow-up requests.",
    }
