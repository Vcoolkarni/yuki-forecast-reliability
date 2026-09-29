"""V2 forecast-time predictor contract; labels/reference data are never features."""

from __future__ import annotations

from .dataset import TARGETS

DERIVED_GFS = {
    "forecast_wind_speed_10m": {"source": "GFS UGRD/VGRD 10 m", "unit": "m/s", "transformation": "hypot(u,v)",
                                  "interpretation": "Near-surface wind intensity"},
    "precipitation_gradient_mm_per_degree": {"source": "GFS daily APCP", "unit": "mm/degree",
                                               "transformation": "gridwise hypot(dP/dlat,dP/dlon)",
                                               "interpretation": "Forecast rainfall spatial contrast"},
}
GEFS_DERIVED = {
    "gefs_precipitation_mean_mm": "Member mean daily precipitation",
    "gefs_precipitation_std_mm": "Population standard deviation of member daily precipitation",
    "gefs_precipitation_min_mm": "Minimum member daily precipitation",
    "gefs_precipitation_max_mm": "Maximum member daily precipitation",
    "gefs_precipitation_p10_mm": "10th percentile of member daily precipitation",
    "gefs_precipitation_p90_mm": "90th percentile of member daily precipitation",
    "gefs_precipitation_range_mm": "Maximum minus minimum member daily precipitation",
    "gefs_precipitation_cv": "Standard deviation / mean when mean > 1 mm; otherwise undefined",
    "gfs_minus_gefs_mean_precipitation_mm": "Deterministic GFS daily rainfall minus GEFS mean",
}
BALANCED_GEFS_DERIVED = {
    "gefs_precipitation_mean_mm": "Sum of four published 6-hour ensemble means; daily ensemble mean",
    "gefs_6h_spread_mean_mm": "Mean of four published 6-hour ensemble standard deviations; not daily spread",
    "gefs_6h_spread_max_mm": "Maximum published 6-hour ensemble standard deviation; not daily spread",
    "gefs_6h_spread_rms_mm": "Root-mean-square of four published 6-hour ensemble standard deviations; not daily spread",
    "gfs_minus_gefs_mean_precipitation_mm": "GFS daily rainfall minus published GEFS daily mean",
}
RECOMMENDED_GEFS_DERIVED = {
    "gefs_precipitation_mean_mm": "Sum of four published six-hour ensemble means; daily ensemble mean",
    "gefs_end_window_spread_6h_mm": "Published ensemble standard deviation for the final six hours only; not daily spread",
    "gfs_minus_gefs_mean_precipitation_mm": "GFS daily rainfall minus published GEFS daily mean",
}


def forecast_feature_schema(config: dict) -> dict[str, dict]:
    result = {"lead_day": {"source": "forecast lead", "unit": "day", "transformation": "none",
                           "interpretation": "Error-growth horizon"}}
    for name, predictor in config["forecast"]["gfs"]["predictors"].items():
        result[predictor["output_column"]] = {
            "source": f"NOAA GFS {predictor['selector_template']}", "unit": predictor["unit"],
            "transformation": predictor["temporal"], "interpretation": name.replace("_", " ")}
    result.update(DERIVED_GFS)
    if config["forecast"]["gefs"]["enabled"]:
        if config["forecast"]["gefs"].get("mode") == "published_daily_mean_end_window_spread":
            for name, meaning in RECOMMENDED_GEFS_DERIVED.items():
                result[name] = {"source": "NOAA GEFS published six-hour APCP mean/spread",
                                "unit": "mm", "transformation": "four interval means or one final interval spread",
                                "interpretation": meaning}
            return result
        if config["forecast"]["gefs"].get("mode") == "published_6h_mean_spread":
            for name, meaning in BALANCED_GEFS_DERIVED.items():
                result[name] = {"source": "NOAA GEFS 0.25° published 6-hour APCP mean/spread",
                                "unit": "mm as named", "transformation": "four exact 6-hour interval products",
                                "interpretation": meaning}
            return result
        for name, meaning in GEFS_DERIVED.items():
            result[name] = {"source": "NOAA GEFS 0.25° member APCP", "unit": "mm or dimensionless as named",
                            "transformation": "strict four 6-hour intervals per member per lead, then ensemble statistic",
                            "interpretation": meaning}
        for threshold in config["forecast"]["gefs"]["exceedance_thresholds_mm"]:
            result[f"gefs_fraction_ge_{threshold:g}mm"] = {
                "source": "NOAA GEFS member APCP", "unit": "fraction", "transformation": "members at/above threshold / member count",
                "interpretation": f"Member fraction with >= {threshold:g} mm daily precipitation"}
    if set(result) & TARGETS:
        raise ValueError("Reference/target column included in V2 forecast feature schema")
    return result
