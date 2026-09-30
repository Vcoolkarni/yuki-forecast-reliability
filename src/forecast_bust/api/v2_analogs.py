"""Forecast-feature nearest analogs from 2021–23 training dates only."""

from pathlib import Path
from threading import RLock
from collections import OrderedDict

import numpy as np
import pandas as pd


FEATURES = ("forecast_precipitation", "forecast_precipitable_water", "forecast_cape_surface",
            "gefs_precipitation_mean_mm", "gefs_end_window_spread_6h_mm")
COLUMNS = ("initialization_time", "lead_day", "latitude", "longitude", *FEATURES,
           "reference_precipitation", "absolute_error", "is_bust")


class V2AnalogRepository:
    def __init__(self, root: Path, index_cache_size: int = 2):
        if index_cache_size < 1:
            raise ValueError("Analog index cache size must be positive")
        self.root = root
        self.index_cache_size = index_cache_size
        self.cache = OrderedDict()
        self.index_cache = OrderedDict()
        self.lock = RLock()

    def _indexed_candidates(self, key: tuple) -> list[dict]:
        lead, latitude, longitude = key
        if lead not in self.index_cache:
            path = self.root / f"day_{lead:02d}.npz"
            with np.load(path, allow_pickle=False) as index:
                loaded = {name: index[name] for name in ("values", "bust", "latitude", "longitude", "dates")}
            if loaded["values"].shape != (105, 3843, len(FEATURES) + 2):
                raise ValueError("V2 analog index has an incompatible shape")
            self.index_cache[lead] = loaded
            if len(self.index_cache) > self.index_cache_size:
                self.index_cache.popitem(last=False)
        self.index_cache.move_to_end(lead)
        index = self.index_cache[lead]
        matches = np.flatnonzero((index["latitude"] == latitude) & (index["longitude"] == longitude))
        if len(matches) != 1:
            raise ValueError("V2 analog grid center is absent from the packaged index")
        cell = int(matches[0])
        names = (*FEATURES, "reference_precipitation", "absolute_error")
        return [{"initialization_time": str(index["dates"][row]), "lead_day": lead,
                 "latitude": latitude, "longitude": longitude,
                 **dict(zip(names, index["values"][row, cell].tolist())),
                 "is_bust": bool(index["bust"][row, cell])} for row in range(105)]

    def retrieve(self, current: dict, limit: int = 5) -> dict:
        key = (current["lead_day"], current["latitude"], current["longitude"])
        with self.lock:
            if key not in self.cache:
                if (self.root / f"day_{key[0]:02d}.npz").is_file():
                    candidates = self._indexed_candidates(key)
                else:
                    candidates = []
                    for path in sorted((self.root / "train").glob("*.csv.gz")):
                        if path.name.endswith(".raw.csv.gz"):
                            continue
                        frame = pd.read_csv(path, usecols=list(COLUMNS))
                        matches = frame.loc[(frame.lead_day == key[0]) &
                                            (frame.latitude == key[1]) & (frame.longitude == key[2])]
                        if len(matches) != 1:
                            raise ValueError(f"V2 training analog grid is incomplete in {path.name}")
                        candidates.append(matches.iloc[0].to_dict())
                if len(candidates) != 105:
                    raise ValueError("V2 analog index requires all 105 training initializations")
                self.cache[key] = candidates
                if len(self.cache) > 64:
                    self.cache.popitem(last=False)
            candidates = self.cache[key]
            self.cache.move_to_end(key)
        matrix = np.array([[item[name] for name in FEATURES] for item in candidates], dtype=float)
        query = np.array([current[name] for name in FEATURES], dtype=float)
        scales = matrix.std(axis=0)
        scales[scales == 0] = 1
        distances = np.linalg.norm((matrix - query) / scales, axis=1)
        selected = []
        for index in np.argsort(distances, kind="stable")[:limit]:
            item = candidates[int(index)]
            distance = float(distances[index])
            selected.append({"initialization_time": pd.Timestamp(item["initialization_time"]).isoformat().replace("+00:00", "Z"),
                "lead_day": int(item["lead_day"]), "latitude": float(item["latitude"]),
                "longitude": float(item["longitude"]), "similarity_score": 1 / (1 + distance),
                "distance": distance, "forecast_precipitation": float(item["forecast_precipitation"]),
                "reference_precipitation": float(item["reference_precipitation"]),
                "absolute_error": float(item["absolute_error"]), "is_bust": bool(item["is_bust"])})
        return {"initialization_time": current["initialization_time"], "latitude": current["latitude"],
                "longitude": current["longitude"], "lead_day": current["lead_day"],
                "number_of_analogs": len(selected),
                "percentage_busted": 100 * sum(item["is_bust"] for item in selected) / len(selected),
                "mean_historical_absolute_error": sum(item["absolute_error"] for item in selected) / len(selected),
                "analogs": selected,
                "provenance": "Verified 2021–23 training forecasts at the same grid center/lead, ranked using forecast-only GFS/GEFS features. Historical ERA5 outcomes are attached after ranking; labels use training-derived lead-specific P90. Descriptive analogs, not a probability forecast."}
