"""Compare cached inference outputs from two real, available forecast runs."""


def _overlap(first: dict, second: dict) -> bool:
    a, b = first["bounding_box"], second["bounding_box"]
    return a["south"] <= b["north"] and b["south"] <= a["north"] and a["west"] <= b["east"] and b["west"] <= a["east"]


def compare_runs(current: dict, previous: dict, lead_day: int) -> dict:
    if current["initialization_time"] == previous["initialization_time"]:
        raise ValueError("Choose two different forecast initializations")
    before = {(row["latitude"], row["longitude"]): row for row in previous["records"] if row["lead_day"] == lead_day}
    after = {(row["latitude"], row["longitude"]): row for row in current["records"] if row["lead_day"] == lead_day}
    if not before or before.keys() != after.keys():
        raise ValueError("Forecast runs do not contain the same grid cells for this lead day")
    cells = []
    for coordinates in sorted(after):
        old, new = before[coordinates], after[coordinates]
        was, now = old["is_bust_predicted"], new["is_bust_predicted"]
        state = "emerging" if now and not was else "resolved" if was and not now else "persistent" if now else "neither"
        cells.append({"latitude": coordinates[0], "longitude": coordinates[1], "lead_day": lead_day,
                      "previous_bust_probability": old["bust_probability"], "current_bust_probability": new["bust_probability"],
                      "delta_bust_probability": new["bust_probability"] - old["bust_probability"],
                      "previous_confidence": old["confidence_score"], "current_confidence": new["confidence_score"],
                      "delta_confidence": new["confidence_score"] - old["confidence_score"], "state": state})
    previous_regions = [item for item in previous["hotspots"] if item["lead_day"] == lead_day]
    current_regions = [item for item in current["hotspots"] if item["lead_day"] == lead_day]
    previous_hotspots, current_hotspots = len(previous_regions), len(current_regions)
    ranked = sorted(cells, key=lambda item: item["delta_bust_probability"])
    return {"current_initialization": current["initialization_time"],
            "previous_initialization": previous["initialization_time"], "lead_day": lead_day,
            "number_of_cells": len(cells),
            "mean_probability_delta": sum(item["delta_bust_probability"] for item in cells) / len(cells),
            "mean_confidence_delta": sum(item["delta_confidence"] for item in cells) / len(cells),
            "emerging_bust_cells": sum(item["state"] == "emerging" for item in cells),
            "resolved_bust_cells": sum(item["state"] == "resolved" for item in cells),
            "persistent_bust_cells": sum(item["state"] == "persistent" for item in cells),
            "previous_hotspot_count": previous_hotspots, "current_hotspot_count": current_hotspots,
            "hotspot_count_delta": current_hotspots - previous_hotspots,
            "new_hotspot_regions": sum(not any(_overlap(item, old) for old in previous_regions) for item in current_regions),
            "resolved_hotspot_regions": sum(not any(_overlap(item, new) for new in current_regions) for item in previous_regions),
            "largest_risk_increases": list(reversed([item for item in ranked if item["delta_bust_probability"] > 0][-5:])),
            "largest_risk_decreases": [item for item in ranked if item["delta_bust_probability"] < 0][:5],
            "cells": cells}
