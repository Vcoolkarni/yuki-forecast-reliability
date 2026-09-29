"""Analytical, offline acquisition comparisons; never requests or writes data."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import statistics

import yaml

from .configuration import initialization_dates
from .geography import configured_grid_centers

GIB = 1024 ** 3
MIB = 1024 ** 2


def load_profile_config(path: str | Path = "config/v2_profiles.yaml") -> dict:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if config.get("version") != "v2_acquisition_profiles":
        raise ValueError("Expected a V2 acquisition profiles configuration")
    if set(config["profiles"]) != {"LIGHT", "BALANCED", "FULL"}:
        raise ValueError("Expected LIGHT, BALANCED, and FULL profiles")
    if config["sampling_frequencies_days"] != [1, 2, 3]:
        raise ValueError("Expected daily, every-2-day, and every-3-day comparisons")
    if config["gfs"]["precipitation_intervals_per_lead"] != 4 or config["gfs"]["precipitation_interval_hours"] != 6:
        raise ValueError("GFS daily precipitation requires four six-hour intervals")
    if config["gefs"]["full_members"] != 31 or config["gefs"]["published_statistics"] != ["mean", "spread"]:
        raise ValueError("Expected 31 members and published mean/spread products")
    return config


def _sampled_dates(base: dict, profiles: dict, cadence: int) -> list[str]:
    requested = profiles["requested_period"]
    sampling_config = deepcopy(base)
    sampling_config["time"] = {
        "start_date": requested["start_date"], "end_date": requested["end_date"],
        "sampling": {"months": requested["months"], "every_n_days": cadence, "anchor_day_of_month": 1},
        "initialization_hours": [0],
    }
    return initialization_dates(sampling_config)


def _era5_months(dates: list[str], lead_days: list[int]) -> int:
    months: set[str] = set()
    last_lead = max(lead_days)
    for init in dates:
        first = date.fromisoformat(init) + timedelta(days=1)
        for offset in range(last_lead):
            day = first + timedelta(days=offset)
            months.add(f"{day.year:04d}-{day.month:02d}")
    return len(months)


def _period_for(day: str, periods: dict) -> str:
    matches = [name for name, span in periods.items() if span["start_date"] <= day <= span["end_date"]]
    if len(matches) != 1:
        raise ValueError(f"Initialization {day} does not belong to exactly one temporal period")
    return matches[0]


def _gfs_message_mib(base: dict, profiles: dict) -> float:
    legacy = Path(base["paths"]["legacy_gfs_dir"])
    observed = [path.stat().st_size / MIB for path in legacy.glob("*.grb2") if path.stat().st_size > 0]
    return statistics.median(observed) if observed else float(profiles["estimation"]["fallback_gfs_message_mib"])


def estimate_profiles(base: dict, profiles: dict) -> list[dict]:
    """Count only conservatively supported initializations; expose excluded dates."""
    leads = base["forecast"]["lead_days"]
    latitudes, longitudes = configured_grid_centers(base["geography"])
    cells = len(latitudes) * len(longitudes)
    gfs_per_init = len(leads) * (
        profiles["gfs"]["instantaneous_predictors_per_lead"]
        + profiles["gfs"]["precipitation_intervals_per_lead"]
    )
    gefs_intervals = max(leads) * 24 // profiles["gefs"]["precipitation_interval_hours"]
    assumptions = profiles["estimation"]
    gfs_mib = _gfs_message_mib(base, profiles)
    rows = []
    for profile_name, settings in profiles["profiles"].items():
        mode = settings["gefs_mode"]
        if mode not in {"none", "published_6h_mean_spread", "all_31_members"}:
            raise ValueError(f"Unsupported GEFS mode: {mode}")
        gefs_per_init = {"none": 0, "published_6h_mean_spread": 2 * gefs_intervals,
                         "all_31_members": profiles["gefs"]["full_members"] * gefs_intervals}[mode]
        required_sources = ["gfs_0p25", "era5_hourly"]
        if mode == "published_6h_mean_spread":
            required_sources.append("gefs_mean_spread_0p25")
        elif mode == "all_31_members":
            required_sources.append("gefs_member_0p25")
        for cadence in profiles["sampling_frequencies_days"]:
            candidate_dates = _sampled_dates(base, profiles, cadence)
            supported, unsupported = [], []
            for day in candidate_dates:
                failures = [source for source in required_sources if not (
                    profiles["availability"][source]["start_date"] <= day <=
                    profiles["availability"][source]["end_date"]
                )]
                # ERA5 is verified through the end of the Day-10 window.
                verification_end = (date.fromisoformat(day) + timedelta(days=max(leads))).isoformat()
                if verification_end > profiles["availability"]["era5_hourly"]["end_date"]:
                    failures.append("era5_day10_window")
                (unsupported if failures else supported).append((day, failures))
            dates = [day for day, _ in supported]
            if not dates:
                raise ValueError(f"No supported dates for {profile_name}/{cadence}")
            period_counts = {name: sum(_period_for(day, profiles["periods"]) == name for day in dates)
                             for name in ("train", "validation", "test")}
            unsupported_periods: dict[str, dict] = {}
            for day, failures in unsupported:
                year = day[:4]
                entry = unsupported_periods.setdefault(year, {"initializations": 0, "sources": []})
                entry["initializations"] += 1
                entry["sources"] = sorted(set(entry["sources"]) | set(failures))
            n = len(dates)
            # A three-day block is a diversity proxy, not a claim of
            # meteorological independence between adjacent forecasts.
            three_day_blocks = len({
                (day[:4], (date.fromisoformat(day) - date(int(day[:4]), 6, 1)).days // 3)
                for day in dates
            })
            gfs_messages = n * gfs_per_init
            gefs_messages = n * gefs_per_init
            era5_months = _era5_months(dates, leads)
            download_gib = (gfs_messages * gfs_mib + gefs_messages * float(assumptions["gefs_precipitation_message_mib"])
                            + era5_months * float(assumptions["era5_month_mib"])) / 1024
            grid_rows = n * len(leads) * cells
            copies = int(assumptions["intermediate_copies"])
            bytes_per_row = int(assumptions["intermediate_bytes_per_row"][profile_name])
            intermediate_gib = download_gib + grid_rows * bytes_per_row * copies / GIB
            retained = float(assumptions["india_land_plus_halo_fraction"])
            rows.append({
                "PROFILE_NAME": profile_name,
                "DATE_RANGE": [dates[0], dates[-1]],
                "REQUESTED_DATE_RANGE": [profiles["requested_period"]["start_date"], profiles["requested_period"]["end_date"]],
                "TRAIN_PERIOD": profiles["periods"]["train"],
                "VALIDATION_PERIOD": profiles["periods"]["validation"],
                "TEST_PERIOD": profiles["periods"]["test"],
                "SAMPLING_FREQUENCY": f"every {cadence} day" + ("" if cadence == 1 else "s"),
                "INITIALIZATIONS": n,
                "THREE_DAY_BLOCKS": three_day_blocks,
                "INITIALIZATIONS_BY_PERIOD": period_counts,
                "UNSUPPORTED_PERIODS": unsupported_periods,
                "GFS_MESSAGES": gfs_messages,
                "GEFS_MESSAGES": gefs_messages,
                "ERA5_MONTHS": era5_months,
                # Each GRIB message currently entails one .idx GET and one Range GET.
                "INDEX_REQUESTS": gfs_messages + gefs_messages,
                "TOTAL_REQUESTS": 2 * (gfs_messages + gefs_messages) + era5_months,
                "ESTIMATED_DOWNLOAD_GIB": round(download_gib, 2),
                "ESTIMATED_INTERMEDIATE_DISK_GIB": round(intermediate_gib, 2),
                "GRID_ROWS": grid_rows,
                "INITIALIZATIONS_PER_GIB": round(n / download_gib, 2),
                "THREE_DAY_BLOCKS_PER_GIB": round(three_day_blocks / download_gib, 2),
                "GRID_ROWS_AFTER_MASK_ESTIMATE": round(grid_rows * retained),
                "POST_MASK_INTERMEDIATE_SAVINGS_GIB": round(grid_rows * (1 - retained) * bytes_per_row * copies / GIB, 2),
                "GEFS_MODE": mode,
                "ESTIMATE_BASIS": {"gfs_message_mib": round(gfs_mib, 3),
                                   "gefs_precipitation_message_mib": float(assumptions["gefs_precipitation_message_mib"]),
                                   "era5_month_mib": float(assumptions["era5_month_mib"]),
                                   "intermediate_copies": copies, "intermediate_bytes_per_row": bytes_per_row},
            })
    return rows
