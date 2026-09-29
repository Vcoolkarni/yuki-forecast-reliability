"""Forecast-feature-only nearest historical situations; outcomes are attached afterward."""

from pathlib import Path
from threading import RLock

import numpy as np
import pandas as pd

from ..features import FEATURE_COLUMNS, build_features


class AnalogRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock = RLock()
        self.frame = None
        self.values = None
        self.means = None
        self.scales = None

    def _initialize(self):
        if self.frame is not None:
            return
        frame = pd.read_csv(self.path)
        needed = set(FEATURE_COLUMNS) | {"initialization_time", "valid_time", "latitude", "longitude",
                                         "lead_day", "reference_precipitation", "absolute_error", "is_bust"}
        available = set(frame.columns) | {"month"}
        if frame.empty or needed - available:
            raise ValueError("Historical analog dataset is missing required forecast or outcome columns")
        frame = build_features(frame)
        values = frame[FEATURE_COLUMNS].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("Historical analog features must be finite")
        means = values.mean(axis=0)
        scales = values.std(axis=0)
        scales[scales == 0] = 1.0
        self.frame, self.values, self.means, self.scales = frame, values, means, scales

    def retrieve(self, current: dict, limit: int = 5) -> dict:
        """Distance never accesses ERA5, error, or bust labels; they are read after ranking."""
        with self.lock:
            self._initialize()
            frame = self.frame
            valid = pd.to_datetime(current["valid_time"], utc=True)
            query = np.array([valid.month if feature == "month" else current[feature] for feature in FEATURE_COLUMNS], dtype=float)
            if not np.isfinite(query).all():
                raise ValueError("Selected forecast features must be finite")
            init = pd.to_datetime(current["initialization_time"], utc=True)
            historical_init = pd.to_datetime(frame["initialization_time"], utc=True)
            eligible = (frame["lead_day"].to_numpy() == current["lead_day"]) & (historical_init != init).to_numpy()
            candidate_indices = np.flatnonzero(eligible)
            if not len(candidate_indices):
                return self._response(current, [])
            distances = np.linalg.norm((self.values[candidate_indices] - query) / self.scales, axis=1)
            order = np.argsort(distances, kind="stable")
            selected = []
            used_dates = set()
            for position in order:
                index = candidate_indices[position]
                row = frame.iloc[index]
                date = pd.Timestamp(row["initialization_time"]).isoformat()
                if date in used_dates:
                    continue
                used_dates.add(date)
                distance = float(distances[position])
                selected.append({"initialization_time": pd.to_datetime(row["initialization_time"], utc=True).isoformat().replace("+00:00", "Z"),
                                 "lead_day": int(row["lead_day"]), "latitude": float(row["latitude"]),
                                 "longitude": float(row["longitude"]), "similarity_score": 1.0 / (1.0 + distance),
                                 "distance": distance, "forecast_precipitation": float(row["forecast_precipitation"]),
                                 "reference_precipitation": float(row["reference_precipitation"]),
                                 "absolute_error": float(row["absolute_error"]), "is_bust": bool(row["is_bust"])})
                if len(selected) == limit:
                    break
            return self._response(current, selected)

    @staticmethod
    def _response(current, selected):
        count = len(selected)
        return {"initialization_time": current["initialization_time"], "latitude": current["latitude"],
                "longitude": current["longitude"], "lead_day": current["lead_day"], "number_of_analogs": count,
                "percentage_busted": 100 * sum(row["is_bust"] for row in selected) / count if count else None,
                "mean_historical_absolute_error": sum(row["absolute_error"] for row in selected) / count if count else None,
                "analogs": selected,
                "provenance": "Historical GFS forecasts matched with ERA5 reanalysis; similarity uses standardized forecast-only model features. Historical is_bust labels come from the stored dataset's fixed 20 mm absolute-error definition and may differ from the trained model's definition. Analogs are descriptive, not a probability forecast."}
