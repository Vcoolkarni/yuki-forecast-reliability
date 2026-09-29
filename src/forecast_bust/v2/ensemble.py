"""Strict GEFS interval aggregation and forecast-only ensemble summaries."""

from __future__ import annotations

import numpy as np
import pandas as pd

KEY = ["initialization_time", "lead_day", "latitude", "longitude"]
FORBIDDEN = {"reference_precipitation", "forecast_error", "absolute_error", "is_bust", "target_absolute_error_mm"}


def aggregate_member_daily(intervals: pd.DataFrame, step_hours: int = 6) -> pd.DataFrame:
    """Require all [start,end) GEFS intervals before summing one 24-hour day."""
    if not 0 < step_hours <= 24 or 24 % step_hours:
        raise ValueError("GEFS accumulation step must divide one day")
    required = set(KEY + ["member", "start_hour", "end_hour", "apcp_mm"])
    if missing := required - set(intervals.columns):
        raise ValueError(f"Missing GEFS interval fields: {sorted(missing)}")
    if set(intervals.columns) & FORBIDDEN:
        raise ValueError("GEFS forecast features cannot contain reference/target fields")
    data = intervals.copy()
    data["initialization_time"] = pd.to_datetime(data["initialization_time"], utc=True)
    data["lead_day"] = pd.to_numeric(data["lead_day"], errors="raise").astype(int)
    for column in ("latitude", "longitude", "start_hour", "end_hour", "apcp_mm"):
        data[column] = pd.to_numeric(data[column], errors="raise")
    if data[list(required)].isna().any().any() or not np.isfinite(data["apcp_mm"]).all() or (data["apcp_mm"] < 0).any():
        raise ValueError("GEFS interval values must be complete, finite, and nonnegative")
    if data.duplicated(KEY + ["member", "end_hour"]).any():
        raise ValueError("Duplicate GEFS member interval")
    data["expected_lead"] = ((data["end_hour"] - 1) // 24 + 1).astype(int)
    if (data["end_hour"] - data["start_hour"] != step_hours).any() or (data["end_hour"] % step_hours != 0).any() or (data["expected_lead"] != data["lead_day"]).any():
        raise ValueError("GEFS accumulation interval does not match its lead day")
    output = []
    for identity, group in data.groupby(KEY + ["member"], sort=False):
        lead = int(identity[1])
        expected = list(range((lead - 1) * 24 + step_hours, lead * 24 + 1, step_hours))
        observed = sorted(group.end_hour.astype(int).tolist())
        if observed != expected or any(int(row.start_hour) != int(row.end_hour) - step_hours for row in group.itertuples()):
            raise ValueError(f"Incomplete GEFS 24-hour member window for {identity}; expected {expected}, got {observed}")
        output.append((*identity, float(group.apcp_mm.sum())))
    return pd.DataFrame(output, columns=KEY + ["member", "gefs_member_precipitation_mm"])


def add_ensemble_statistics(forecast: pd.DataFrame, member_daily: pd.DataFrame,
                            members: list[str], exceedance_thresholds_mm: list[float]) -> pd.DataFrame:
    """Align by exact init/lead/grid; no missing members or invented grid cells."""
    if not members or len(members) != len(set(members)):
        raise ValueError("A unique GEFS member set is required")
    if set(forecast.columns) & FORBIDDEN or set(member_daily.columns) & FORBIDDEN:
        raise ValueError("Ensemble similarity/features must not use target/reference fields")
    if forecast.duplicated(KEY).any() or member_daily.duplicated(KEY + ["member"]).any():
        raise ValueError("Duplicate deterministic or GEFS grid key")
    if not set(member_daily.member.unique()) <= set(members):
        raise ValueError("Unexpected GEFS member")
    wide = member_daily.pivot(index=KEY, columns="member", values="gefs_member_precipitation_mm")
    if set(wide.columns) != set(members) or wide[members].isna().any().any():
        raise ValueError("Incomplete GEFS ensemble membership; no member may be fabricated")
    matrix = wide[members].to_numpy(dtype=float)
    if not np.isfinite(matrix).all() or (matrix < 0).any():
        raise ValueError("GEFS daily precipitation must be finite and nonnegative")
    statistics = wide[members].iloc[:, :0].copy()
    statistics["gefs_precipitation_mean_mm"] = matrix.mean(axis=1)
    statistics["gefs_precipitation_std_mm"] = matrix.std(axis=1, ddof=0)
    statistics["gefs_precipitation_min_mm"] = matrix.min(axis=1)
    statistics["gefs_precipitation_max_mm"] = matrix.max(axis=1)
    statistics["gefs_precipitation_p10_mm"] = np.percentile(matrix, 10, axis=1)
    statistics["gefs_precipitation_p90_mm"] = np.percentile(matrix, 90, axis=1)
    statistics["gefs_precipitation_range_mm"] = statistics["gefs_precipitation_max_mm"] - statistics["gefs_precipitation_min_mm"]
    # Undefined near dry conditions: keep NaN explicit; downstream model policy must decide.
    statistics["gefs_precipitation_cv"] = np.where(statistics["gefs_precipitation_mean_mm"] > 1.0,
                                                statistics["gefs_precipitation_std_mm"] / statistics["gefs_precipitation_mean_mm"], np.nan)
    for threshold in exceedance_thresholds_mm:
        if threshold <= 0:
            raise ValueError("GEFS exceedance thresholds must be positive")
        statistics[f"gefs_fraction_ge_{threshold:g}mm"] = (matrix >= threshold).mean(axis=1)
    statistics["gefs_member_count"] = len(members)
    result = forecast.merge(statistics.reset_index(), on=KEY, how="left", validate="one_to_one", indicator=True)
    if (result["_merge"] != "both").any() or len(result) != len(wide):
        raise ValueError("GFS/GEFS grid keys do not match exactly; explicit regridding would be required")
    result = result.drop(columns="_merge")
    result["gfs_minus_gefs_mean_precipitation_mm"] = result["forecast_precipitation"] - result["gefs_precipitation_mean_mm"]
    return result
