"""Offline sub-8-GiB V2 profile estimator; no weather-data requests or writes."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

import yaml

from .configuration import initialization_dates
from .geography import configured_grid_centers

GIB = 1024 ** 3


def load_budget_config(path: str | Path = "config/v2_budget_profiles.yaml") -> dict:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if config.get("version") != "v2_budget_profiles":
        raise ValueError("Expected V2 budget profiles configuration")
    if set(config["profiles"]) != {"ULTRALIGHT", "RECOMMENDED", "MAX"}:
        raise ValueError("Expected ULTRALIGHT, RECOMMENDED, MAX profiles")
    if config["gfs"]["precipitation_intervals_per_lead"] != 4:
        raise ValueError("GFS daily precipitation requires four six-hour intervals")
    if config["grid"]["gfs_gefs_resolution_degrees"] != 0.5:
        raise ValueError("These archive-size assumptions are specific to the 0.5-degree products")
    if config["period"]["test"]["start_date"][:4] != "2025":
        raise ValueError("2025 must remain the final test period")
    return config


def _dates(base: dict, config: dict, cadence: int, max_per_year: int) -> list[str]:
    selected = deepcopy(base)
    period = config["period"]
    selected["time"] = {"start_date": period["start_date"], "end_date": period["end_date"],
                        "sampling": {"months": period["months"], "every_n_days": cadence,
                                     "anchor_day_of_month": 1}, "initialization_hours": [0]}
    by_year: dict[int, list[str]] = defaultdict(list)
    for item in initialization_dates(selected):
        by_year[int(item[:4])].append(item)
    result = []
    for year, candidates in sorted(by_year.items()):
        if len(candidates) <= max_per_year:
            result.extend(candidates)
        else:
            # Evenly thin the three-day candidates across the full season;
            # never prefer early monsoon or move a date between split years.
            indices = [round(index * (len(candidates) - 1) / (max_per_year - 1))
                       for index in range(max_per_year)]
            if len(set(indices)) != max_per_year:
                raise ValueError(f"Date thinning produced duplicate indices in {year}")
            result.extend(candidates[index] for index in indices)
    return result


def _era5_month_count(dates: list[str]) -> int:
    months = set()
    for value in dates:
        start = date.fromisoformat(value)
        for offset in range(1, 11):
            day = start + timedelta(days=offset)
            months.add((day.year, day.month))
    return len(months)


def _existing_payload_cache(base: dict) -> dict:
    root = Path(base["paths"]["raw_dir"])
    source_paths = [root / "gfs", root / "smoke" / "gfs", root / "smoke" / "gefs",
                    root / "smoke" / "era5"]
    files = [path for folder in source_paths for path in folder.rglob("*")
             if path.is_file() and path.suffix.lower() in {".grb2", ".nc"}]
    bytes_total = sum(path.stat().st_size for path in files)
    legacy_gfs = [path for path in Path(base["paths"]["legacy_gfs_dir"]).glob("*.grb2") if path.is_file()]
    legacy_era5 = [path for path in (Path(base["paths"]["raw_dir"]).parent / "era5_phase2").glob("*.nc") if path.is_file()]
    # All current V2 GRIB caches are 0.25-degree, and the only ERA5 cache
    # is a 3x3 smoke crop. None covers the proposed 0.5-degree India product.
    compatible = [path for path in files if "0p50" in path.name and path.suffix.lower() == ".grb2"]
    return {"EXISTING_V2_PAYLOAD_FILES": len(files), "EXISTING_V2_PAYLOAD_MIB": round(bytes_total / 1048576, 2),
            "EXISTING_V1_GFS_FILES": len(legacy_gfs),
            "EXISTING_V1_GFS_GIB": round(sum(path.stat().st_size for path in legacy_gfs) / GIB, 3),
            "EXISTING_V1_ERA5_FILES": len(legacy_era5),
            "REUSABLE_MATCHING_FILES": len(compatible),
            "REUSABLE_MATCHING_MIB": round(sum(path.stat().st_size for path in compatible) / 1048576, 2),
            "NOTE": "0.25-degree GFS/GEFS messages and a 3x3 ERA5 crop cannot be silently mixed with a consistent 0.5-degree India-wide dataset."}


def estimate_budget_profiles(base: dict, config: dict) -> list[dict]:
    """Conservative byte planning; profiles above 8 GiB are marked non-executable."""
    if base["forecast"]["lead_days"] != list(range(1, 11)):
        raise ValueError("Budget profiles require Day 1–10")
    grid = dict(config["grid"])
    grid["grid_resolution_degrees"] = grid["gfs_gefs_resolution_degrees"]
    latitudes, longitudes = configured_grid_centers(grid)
    cells = len(latitudes) * len(longitudes)
    gfs = config["gfs"]
    predictors = gfs["instantaneous_predictors"]
    if len(predictors) != len(set(predictors)) or any(name not in base["forecast"]["gfs"]["predictors"] for name in predictors):
        raise ValueError("Unknown or duplicate GFS predictor in budget plan")
    if len(predictors) != 7:
        raise ValueError("Budget profile must retain all seven prioritized instantaneous GFS predictors")
    padding = float(config["estimation"]["observed_message_padding_factor"])
    if padding < 1:
        raise ValueError("Message-size padding must be at least 1")
    gfs_sizes = gfs["observed_max_message_mib"]
    gfs_mib_per_init = padding * (40 * float(gfs_sizes["precipitation"]) +
                                  10 * sum(float(gfs_sizes[name]) for name in predictors))
    era5_mib = float(config["era5"]["estimate_mib_per_month"])
    if era5_mib < 50:  # More than the uncompressed 31-day 0.25° India field.
        raise ValueError("ERA5 monthly budget is below the conservative India-wide floor")
    cache = _existing_payload_cache(base)
    result = []
    for name, profile in config["profiles"].items():
        dates = _dates(base, config, profile["cadence_days"], profile["max_initializations_per_year"])
        if len(dates) < 100 or len({day[:4] for day in dates}) != 5:
            raise ValueError(f"{name} lacks 100+ initializations across all five years")
        splits = {period: sum(bounds["start_date"] <= day <= bounds["end_date"] for day in dates)
                  for period, bounds in ((period, config["period"][period]) for period in ("train", "validation", "test"))}
        if sum(splits.values()) != len(dates) or not all(splits.values()):
            raise ValueError("Budget profile temporal split is incomplete")
        mode = profile["gefs_mode"]
        mean_per_init, spread_per_init = {
            "end_window_mean_spread": (10, 10),
            "daily_mean_end_window_spread": (40, 10),
            "all_interval_mean_spread": (40, 40),
        }.get(mode, (None, None))
        if mean_per_init is None:
            raise ValueError(f"Unsupported GEFS sampling mode: {mode}")
        n = len(dates)
        gfs_messages = n * (40 + 10 * len(predictors))
        gefs_messages = n * (mean_per_init + spread_per_init)
        gefs_sizes = config["gefs"]["observed_max_message_mib"]
        gefs_mib_per_init = padding * (mean_per_init * float(gefs_sizes["mean"]) +
                                   spread_per_init * float(gefs_sizes["spread"]))
        era5_months = _era5_month_count(dates)
        era5_size_gib = era5_months * era5_mib / 1024
        download_gib = (n * (gfs_mib_per_init + gefs_mib_per_init) + era5_months * era5_mib) / 1024
        if download_gib > float(profile["target_download_gib"]):
            raise ValueError(f"{name} exceeds its own {profile['target_download_gib']} GiB planning target")
        grid_rows = n * 10 * cells
        disk_gib = download_gib + grid_rows * int(config["estimation"]["intermediate_copies"]) * int(
            config["estimation"]["intermediate_bytes_per_row"][name]) / GIB
        result.append({
            "PROFILE_NAME": name, "YEARS": "2021–2025", "DATE_RANGE": [dates[0], dates[-1]],
            "TRAIN_PERIOD": config["period"]["train"], "VALIDATION_PERIOD": config["period"]["validation"],
            "TEST_PERIOD": config["period"]["test"], "INITIALIZATIONS_BY_PERIOD": splits,
            "CADENCE": f"every {profile['cadence_days']} days" +
                       (f", evenly thinned to {profile['max_initializations_per_year']}/year" if n // 5 < 41 and profile["cadence_days"] == 3 else ""),
            "INITIALIZATIONS": n, "GFS_VARIABLES": ["precipitation"] + predictors,
            "GEFS_FEATURES": mode, "GFS_MESSAGES": gfs_messages, "GEFS_MESSAGES": gefs_messages,
            "ERA5_MONTHS": era5_months, "ERA5_SIZE_GIB": round(era5_size_gib, 2),
            "TOTAL_ESTIMATED_DOWNLOAD_GIB": round(download_gib, 2),
            "ESTIMATED_DISK_GIB": round(disk_gib, 2),
            "INITIALIZATION_DATES_PER_GIB": round(n / download_gib, 2),
            "GRID_CELLS_PER_LEAD": cells, "GRID_ROWS_CORRELATED_NOT_INDEPENDENT": grid_rows,
            "TARGET_DOWNLOAD_GIB": profile["target_download_gib"],
            "WITHIN_HARD_8_GIB_CAP": download_gib <= float(config["hard_download_cap_gib"]),
            "GFS_MIB_PER_INITIALIZATION": round(gfs_mib_per_init, 3),
            "GEFS_MIB_PER_INITIALIZATION": round(gefs_mib_per_init, 3),
            "CACHE": cache,
            "CAVEAT": "Metadata-sampled sizes plus 25% padding are estimates, not an enforceable network-byte ceiling. Future acquisition must meter actual bytes and stop before 8 GiB.",
        })
    return result
