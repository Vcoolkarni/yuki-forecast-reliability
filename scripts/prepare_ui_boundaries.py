"""Extract a reproducible small local map asset from geoBoundaries India ADM1.

Input: geoBoundaries IND ADM1 simplified GeoJSON, release 9469f09.
Source metadata: https://www.geoboundaries.org/api/current/gbOpen/IND/ADM1/
License: CC BY 2.5 India; source DataMeet India / Election Commission of India.
This is a display-only boundary layer and is not used by forecast inference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from pathlib import Path


SOURCE_SHA256 = "4c63fe43294a391e8f2de4e9f86f3edb60f8688275b9fee90c61fb2aa0c26061"
STATES = {"Madhya Pradesh", "Maharashtra", "Rajasthan", "Uttar Pradesh", "Chhattisgarh", "Telangana"}
LABEL_VIEW = (19.5, 24.5, 75.5, 80.5)  # south, north, west, east; for label placement only


def plain_name(value: str) -> str:
    return "".join(character for character in unicodedata.normalize("NFKD", value) if not unicodedata.combining(character))


def polygon_rings(geometry: dict):
    if geometry["type"] == "Polygon":
        yield geometry["coordinates"]
    elif geometry["type"] == "MultiPolygon":
        yield from geometry["coordinates"]
    else:
        raise ValueError("Unexpected ADM1 geometry type")


def inside_ring(longitude: float, latitude: float, ring: list) -> bool:
    inside = False
    for first, second in zip(ring, ring[1:] + ring[:1]):
        x1, y1 = first[:2]
        x2, y2 = second[:2]
        if (y1 > latitude) != (y2 > latitude) and longitude < (x2 - x1) * (latitude - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def inside_geometry(longitude: float, latitude: float, geometry: dict) -> bool:
    for rings in polygon_rings(geometry):
        if inside_ring(longitude, latitude, rings[0]) and not any(inside_ring(longitude, latitude, hole) for hole in rings[1:]):
            return True
    return False


def label_point(geometry: dict) -> tuple[float, float] | None:
    south, north, west, east = LABEL_VIEW
    candidates = [(round(south + y * .1, 2), round(west + x * .1, 2))
                  for y in range(round((north - south) / .1) + 1)
                  for x in range(round((east - west) / .1) + 1)]
    points = [(latitude, longitude) for latitude, longitude in candidates if inside_geometry(longitude, latitude, geometry)]
    if not points:
        return None
    middle_latitude = (min(point[0] for point in points) + max(point[0] for point in points)) / 2
    middle_longitude = (min(point[1] for point in points) + max(point[1] for point in points)) / 2
    return min(points, key=lambda point: (point[0] - middle_latitude) ** 2 + (point[1] - middle_longitude) ** 2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--all-india", action="store_true", help="Include all 36 ADM1 states/UTs")
    args = parser.parse_args()
    raw = args.source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("Boundary source checksum does not match the pinned geoBoundaries release")
    source = json.loads(raw)
    selected = []
    for item in source["features"]:
        name = plain_name(item["properties"]["shapeName"])
        if not args.all_india and name not in STATES:
            continue
        label = label_point(item["geometry"]) if name in STATES else None
        selected.append({"type": "Feature", "properties": {"name": name,
                         "labelLatitude": label[0] if label else None,
                         "labelLongitude": label[1] if label else None}, "geometry": item["geometry"]})
    expected = len(source["features"]) if args.all_india else len(STATES)
    if len(selected) != expected or len({item["properties"]["name"] for item in selected}) != expected:
        raise ValueError("The pinned boundary dataset is missing a requested state")
    output = {"type": "FeatureCollection", "features": selected}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"STATE_BOUNDARIES={len(selected)} BYTES={args.output.stat().st_size}")


if __name__ == "__main__":
    main()
