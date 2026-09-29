from __future__ import annotations

import pandas as pd


def find_hotspots(predictions: pd.DataFrame, probability_threshold: float,
                  min_cells: int = 2, connectivity: int = 4) -> list[dict]:
    """Flood-fill elevated-risk cells using 4- or 8-neighbor grid adjacency.

    Input must be a complete regular grid validated by prepare_forecast().
    Only predicted probability is used for membership, never observed weather.
    """
    if not 0 <= probability_threshold <= 1 or min_cells < 1 or connectivity not in (4, 8):
        raise ValueError("Invalid hotspot threshold, minimum size, or connectivity")
    offsets = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    if connectivity == 8:
        offsets += [(-1, -1), (-1, 1), (1, -1), (1, 1)]
    output = []
    for lead, group in predictions.groupby("lead_day", sort=True):
        latitude_index = {value: index for index, value in enumerate(sorted(group.latitude.unique()))}
        longitude_index = {value: index for index, value in enumerate(sorted(group.longitude.unique()))}
        cells = {(latitude_index[row.latitude], longitude_index[row.longitude]): index
                 for index, row in group.iterrows() if row.bust_probability >= probability_threshold}
        unvisited = set(cells)
        number = 0
        while unvisited:
            first = min(unvisited)
            unvisited.remove(first)
            stack, component = [first], [first]
            while stack:
                y, x = stack.pop()
                for dy, dx in offsets:
                    neighbor = (y + dy, x + dx)
                    if neighbor in unvisited:
                        unvisited.remove(neighbor)
                        stack.append(neighbor)
                        component.append(neighbor)
            if len(component) < min_cells:
                continue
            number += 1
            members = group.loc[[cells[cell] for cell in component]]
            output.append({
                "hotspot_id": f"day-{int(lead):02d}-hotspot-{number:03d}",
                "lead_day": int(lead), "number_of_cells": int(len(members)),
                "centroid_latitude": float(members.latitude.mean()),
                "centroid_longitude": float(members.longitude.mean()),
                "mean_bust_probability": float(members.bust_probability.mean()),
                "max_bust_probability": float(members.bust_probability.max()),
                "mean_confidence": float(members.confidence_score.mean()),
                # Geometry metadata only: these are the same original member
                # cells already used for this component and its statistics.
                "member_cells": [{"latitude": float(row.latitude), "longitude": float(row.longitude)}
                                 for row in members.sort_values(["latitude", "longitude"]).itertuples()],
                "bounding_box": {"south": float(members.latitude.min()), "north": float(members.latitude.max()),
                                 "west": float(members.longitude.min()), "east": float(members.longitude.max())},
            })
    return output
