from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import yaml


def load_v2_config(path: str | Path = "config/v2.yaml") -> dict:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("version") != "v2":
        raise ValueError("Expected a separate version: v2 configuration")
    geo = config["geography"]
    if not (-90 <= geo["south"] < geo["north"] <= 90 and -180 <= geo["west"] < geo["east"] <= 180):
        raise ValueError("Invalid V2 geographic bounds")
    resolution = float(geo["grid_resolution_degrees"])
    if resolution <= 0 or any(abs((geo[high] - geo[low]) / resolution - round((geo[high] - geo[low]) / resolution)) > 1e-8
                           for low, high in (("south", "north"), ("west", "east"))):
        raise ValueError("Geographic bounds must align to the configured regular grid")
    leads = config["forecast"]["lead_days"]
    if sorted(set(leads)) != list(range(1, 11)) or leads != list(range(1, 11)):
        raise ValueError("V2 requires ordered Day 1–10 lead times")
    if config["time"]["initialization_hours"] != [0]:
        raise ValueError("The current V2 24-hour verification planner supports 00 UTC only")
    members = config["forecast"]["gefs"]["members"]
    if len(members) != len(set(members)) or any(not (member == "c00" or member.startswith("p") and member[1:].isdigit())
                                                 for member in members):
        raise ValueError("GEFS members must be unique c00/pNN identifiers")
    step = config["forecast"]["gefs"]["precipitation_step_hours"]
    if 24 % step or step <= 0:
        raise ValueError("GEFS precipitation step must divide 24 hours")
    _ = initialization_dates(config)
    return config


def initialization_dates(config: dict) -> list[str]:
    """Sample each selected season independently, so yearly monsoon coverage is stable."""
    time = config["time"]
    first, last = date.fromisoformat(time["start_date"]), date.fromisoformat(time["end_date"])
    if last < first:
        raise ValueError("V2 end_date precedes start_date")
    sampling = time["sampling"]
    months = sorted(set(sampling["months"]))
    if not months or any(not isinstance(month, int) or not 1 <= month <= 12 for month in months):
        raise ValueError("sampling.months must contain calendar months")
    cadence = sampling["every_n_days"]
    anchor = sampling["anchor_day_of_month"]
    if not isinstance(cadence, int) or cadence < 1 or not isinstance(anchor, int) or not 1 <= anchor <= 28:
        raise ValueError("Invalid seasonal sampling cadence/anchor")
    selected = []
    for year in range(first.year, last.year + 1):
        start = date(year, months[0], anchor)
        end = date(year + 1, 1, 1) if months[-1] == 12 else date(year, months[-1] + 1, 1)
        current = start
        while current < end:
            if first <= current <= last and current.month in months:
                selected.append(current.isoformat())
            current += timedelta(days=cadence)
    if not selected:
        raise ValueError("V2 sampling selected no initializations")
    return selected
