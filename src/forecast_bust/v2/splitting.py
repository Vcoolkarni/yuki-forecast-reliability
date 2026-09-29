"""Chronological V2 partitions with full initialization/event-window separation."""

from __future__ import annotations

from datetime import date

import pandas as pd


def split_historical_periods(frame: pd.DataFrame, settings: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    init = pd.to_datetime(frame.initialization_time, utc=True)
    valid = pd.to_datetime(frame.valid_time, utc=True)
    bounds = {name: date.fromisoformat(settings[name]) for name in (
        "train_end", "validation_start", "validation_end", "test_start", "test_end")}
    if not bounds["train_end"] < bounds["validation_start"] <= bounds["validation_end"] < bounds["test_start"] <= bounds["test_end"]:
        raise ValueError("V2 train/validation/test periods must be ordered and disjoint")
    embargo = int(settings["embargo_days"])
    if embargo < 10:
        raise ValueError("V2 Day-10 verification requires at least a 10-day split embargo")
    day = init.dt.date
    masks = [day <= bounds["train_end"],
             day.between(bounds["validation_start"], bounds["validation_end"]),
             day.between(bounds["test_start"], bounds["test_end"])]
    if not pd.concat(masks, axis=1).any(axis=1).all():
        raise ValueError("Some initializations fall between configured V2 periods")
    parts = tuple(frame.loc[mask].copy() for mask in masks)
    if any(part.empty for part in parts):
        raise ValueError("Each V2 temporal split needs at least one initialization")
    for earlier, later in zip(parts, parts[1:]):
        earlier_init = pd.to_datetime(earlier.initialization_time, utc=True)
        later_init = pd.to_datetime(later.initialization_time, utc=True)
        gap = later_init.min() - earlier_init.max()
        if gap < pd.Timedelta(days=embargo) or valid.loc[earlier.index].max() >= later_init.min():
            raise ValueError("V2 split lacks an embargo or has overlapping verification windows")
    return parts
