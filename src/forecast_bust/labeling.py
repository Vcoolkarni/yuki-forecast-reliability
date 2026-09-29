from __future__ import annotations

from typing import Callable
import pandas as pd

Labeler = Callable[[pd.DataFrame, dict], pd.Series]
_LABELERS: dict[str, Labeler] = {}


def register_labeler(name: str):
    def decorator(function: Labeler) -> Labeler:
        _LABELERS[name] = function
        return function
    return decorator


@register_labeler("absolute_error")
def absolute_error_label(frame: pd.DataFrame, config: dict) -> pd.Series:
    threshold = float(config["bust_threshold_mm"])
    if threshold <= 0:
        raise ValueError("bust_threshold_mm must be positive")
    return frame["absolute_error"].ge(threshold).astype("int8")


def add_error_and_labels(frame: pd.DataFrame, config: dict) -> pd.DataFrame:
    result = frame.copy()
    result["forecast_error"] = result["forecast_precipitation"] - result["reference_precipitation"]
    result["absolute_error"] = result["forecast_error"].abs()
    method = config.get("method", "absolute_error")
    if method not in _LABELERS:
        raise ValueError(f"Unknown labeling method {method!r}; available: {sorted(_LABELERS)}")
    result["is_bust"] = _LABELERS[method](result, config)
    return result


def fit_percentile_thresholds(training_frame: pd.DataFrame, percentile: float, by_lead: bool = False) -> dict[int | str, float]:
    """Fit thresholds using training errors only; never pass validation/test rows."""
    if not 0 < percentile < 100:
        raise ValueError("percentile must be between 0 and 100")
    if by_lead:
        return {int(lead): float(group["absolute_error"].quantile(percentile / 100.0)) for lead, group in training_frame.groupby("lead_day")}
    return {"global": float(training_frame["absolute_error"].quantile(percentile / 100.0))}


def apply_percentile_labels(frame: pd.DataFrame, thresholds: dict[int | str, float]) -> pd.DataFrame:
    result = frame.copy()
    if "global" in thresholds:
        result["is_bust"] = result["absolute_error"].ge(thresholds["global"]).astype("int8")
    else:
        mapped = result["lead_day"].map(thresholds)
        if mapped.isna().any():
            raise ValueError("Missing percentile threshold for at least one lead day")
        result["is_bust"] = result["absolute_error"].ge(mapped).astype("int8")
    return result

