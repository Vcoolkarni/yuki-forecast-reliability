"""Grid-cell state membership from bundled administrative polygons, never centroids."""

from __future__ import annotations

from pathlib import Path
import json

import pandas as pd


def configured_grid_centers(geography: dict) -> tuple[list[float], list[float]]:
    """Exact regular center coordinates implied by the configured envelope."""
    step = float(geography["grid_resolution_degrees"])
    if step <= 0:
        raise ValueError("Grid resolution must be positive")
    counts = [(geography[high] - geography[low]) / step for low, high in (("south", "north"), ("west", "east"))]
    if any(abs(count - round(count)) > 1e-8 for count in counts):
        raise ValueError("Geographic envelope is not aligned to the configured grid")
    latitudes = [round(geography["south"] + index * step, 8) for index in range(round(counts[0]) + 1)]
    longitudes = [round(geography["west"] + index * step, 8) for index in range(round(counts[1]) + 1)]
    return latitudes, longitudes


def validate_full_grid_coverage(records: pd.DataFrame, geography: dict) -> None:
    """Fail if any initialization/lead lacks even one configured grid center."""
    latitudes, longitudes = configured_grid_centers(geography)
    expected = {(latitude, longitude) for latitude in latitudes for longitude in longitudes}
    for identity, group in records.groupby(["initialization_time", "lead_day"]):
        actual = {(round(float(row.latitude), 8), round(float(row.longitude), 8))
                  for row in group[["latitude", "longitude"]].itertuples(index=False)}
        if len(group) != len(expected) or actual != expected:
            raise ValueError(f"Incomplete or duplicate forecast grid for {identity}: expected {len(expected)} cells, got {len(group)}")


def load_state_polygons(path: str | Path) -> dict[str, dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("type") != "FeatureCollection":
        raise ValueError("State boundary asset must be a GeoJSON FeatureCollection")
    states = {}
    for feature in data["features"]:
        name = feature.get("properties", {}).get("name")
        geometry = feature.get("geometry", {})
        if not name or geometry.get("type") not in {"Polygon", "MultiPolygon"} or name in states:
            raise ValueError("State boundary asset has missing/duplicate/unsupported geometry")
        states[name] = geometry
    return states


def _on_segment(x: float, y: float, a: list[float], b: list[float]) -> bool:
    cross = (x - a[0]) * (b[1] - a[1]) - (y - a[1]) * (b[0] - a[0])
    return abs(cross) < 1e-10 and min(a[0], b[0]) - 1e-10 <= x <= max(a[0], b[0]) + 1e-10 and min(a[1], b[1]) - 1e-10 <= y <= max(a[1], b[1]) + 1e-10


def _ring_contains(ring: list[list[float]], longitude: float, latitude: float) -> bool:
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if _on_segment(longitude, latitude, a, b):
            return True
        if (a[1] > latitude) != (b[1] > latitude):
            crossing = a[0] + (latitude - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if longitude < crossing:
                inside = not inside
    return inside


def contains_grid_center(geometry: dict, latitude: float, longitude: float) -> bool:
    """GeoJSON uses lon/lat; holes exclude centers, while polygon edges count inside."""
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    for polygon in polygons:
        if _ring_contains(polygon[0], longitude, latitude) and not any(
            _ring_contains(hole, longitude, latitude) for hole in polygon[1:]
        ):
            return True
    return False


def select_state_cells(records: pd.DataFrame, state: str, polygons: dict[str, dict]) -> pd.DataFrame:
    if state not in polygons:
        raise ValueError(f"State {state!r} is not in the installed boundary asset")
    geometry = polygons[state]
    mask = [contains_grid_center(geometry, float(row.latitude), float(row.longitude))
            for row in records[["latitude", "longitude"]].itertuples(index=False)]
    return records.loc[mask].copy()


def _geometry_bounds(geometry: dict) -> tuple[float, float, float, float]:
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    points = [point for polygon in polygons for ring in polygon for point in ring]
    return min(point[1] for point in points), max(point[1] for point in points), min(point[0] for point in points), max(point[0] for point in points)


def state_reliability_summary(records: pd.DataFrame, state: str, polygons: dict[str, dict],
                              coverage: dict, hotspots: list[dict] | None = None) -> dict:
    """Summarize only available predicted grid cells and mark partial coverage."""
    selected = select_state_cells(records, state, polygons)
    if selected.empty:
        raise ValueError("No supported forecast grid cells fall inside this state")
    required = {"initialization_time", "lead_day", "latitude", "longitude", "bust_probability", "confidence_score", "is_bust_predicted"}
    if missing := required - set(selected.columns):
        raise ValueError(f"State summary lacks inference fields: {sorted(missing)}")
    if selected.initialization_time.nunique() != 1:
        raise ValueError("A state summary must cover exactly one initialization")
    if sorted(selected.lead_day.unique().tolist()) != list(range(1, 11)):
        raise ValueError("State summary requires Day 1–10 predictions")
    bounds = _geometry_bounds(polygons[state])
    complete = bounds[0] >= coverage["south"] and bounds[1] <= coverage["north"] and bounds[2] >= coverage["west"] and bounds[3] <= coverage["east"]
    member_keys = {(float(row.latitude), float(row.longitude)) for row in selected[["latitude", "longitude"]].drop_duplicates().itertuples(index=False)}
    hotspots = hotspots or []
    days = []
    for lead, group in selected.groupby("lead_day", sort=True):
        active = [item for item in hotspots if item["lead_day"] == lead and any(
            (member["latitude"], member["longitude"]) in member_keys for member in item.get("member_cells", []))]
        days.append({"lead_day": int(lead), "grid_cell_count": len(group),
                     "mean_bust_probability": float(group.bust_probability.mean()),
                     "mean_confidence": float(group.confidence_score.mean()),
                     "maximum_bust_probability": float(group.bust_probability.max()),
                     "percentage_predicted_bust": float(100 * group.is_bust_predicted.mean()),
                     "hotspot_count_intersecting_state": len(active)})
    highest = selected.loc[selected.bust_probability.idxmax()]
    return {"state": state, "initialization_time": str(selected.initialization_time.iloc[0]),
            "coverage": "polygon_within_declared_grid_envelope" if complete else "partial_grid_domain",
            "caveat": "State metrics summarize only predicted grid-cell centers inside the polygon, not an area-weighted state forecast.",
            "grid_cell_count": len(member_keys), "days": days,
            "highest_risk_lead": max(days, key=lambda item: item["mean_bust_probability"])["lead_day"],
            "lowest_confidence_lead": min(days, key=lambda item: item["mean_confidence"])["lead_day"],
            "mean_risk_changes": [{"from_day": days[index - 1]["lead_day"], "to_day": days[index]["lead_day"],
                                   "delta_probability": days[index]["mean_bust_probability"] - days[index - 1]["mean_bust_probability"]}
                                  for index in range(1, len(days))],
            "highest_risk_grid_cell": {"latitude": float(highest.latitude), "longitude": float(highest.longitude),
                                       "lead_day": int(highest.lead_day), "bust_probability": float(highest.bust_probability)}}
