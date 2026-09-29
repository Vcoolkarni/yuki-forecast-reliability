from collections import OrderedDict
from datetime import datetime, timezone
from threading import RLock

import pandas as pd

from ..inference import ForecastInference
from ..inference.validation import TARGET_COLUMNS
from .settings import APISettings


def normalize_initialization(value: str) -> str:
    """Normalize an ISO date/timestamp to UTC; date-only inputs mean 00 UTC."""
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError) as error:
        raise ValueError("Initialization must be an ISO date or timestamp, e.g. 2026-09-12") from error
    timestamp = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp.astimezone(timezone.utc)
    return timestamp.isoformat().replace("+00:00", "Z")


class ForecastRepository:
    """Load local inputs once and cache inference results per initialization.

    A lock prevents concurrent requests from computing the same initialization
    twice. The bounded LRU cache is per API worker; restart to reload model/data.
    """

    def __init__(self, settings: APISettings):
        self.settings = settings
        self.service = None
        self.frames = {}
        self.grid = None
        self.cache = OrderedDict()
        self.lock = RLock()

    def initialize(self):
        with self.lock:
            if self.service is not None:
                return
            service = ForecastInference.from_artifact(self.settings.model_path, self.settings.inference_config_path)
            frame = pd.read_csv(self.settings.forecast_path)
            forbidden = set(frame.columns) & TARGET_COLUMNS
            if forbidden:
                raise ValueError("API forecast source contains training/reference columns")
            if frame.empty or "initialization_time" not in frame:
                raise ValueError("API forecast source must contain initialization_time and forecast rows")
            times = pd.to_datetime(frame.initialization_time, utc=True, errors="raise")
            if times.isna().any():
                raise ValueError("API forecast source contains missing initialization times")
            grouped = {timestamp.isoformat().replace("+00:00", "Z"): frame.loc[times.eq(timestamp)].copy()
                       for timestamp in sorted(times.unique())}
            if {"latitude", "longitude"}.issubset(frame.columns):
                latitudes = sorted(frame.latitude.unique())
                longitudes = sorted(frame.longitude.unique())
                self.grid = {"south": float(latitudes[0]), "north": float(latitudes[-1]),
                             "west": float(longitudes[0]), "east": float(longitudes[-1]),
                             "latitude_step_degrees": float(min(b-a for a, b in zip(latitudes, latitudes[1:]))) if len(latitudes) > 1 else None,
                             "longitude_step_degrees": float(min(b-a for a, b in zip(longitudes, longitudes[1:]))) if len(longitudes) > 1 else None}
            self.frames = grouped
            self.service = service

    def get(self, initialization: str) -> dict:
        key = normalize_initialization(initialization)
        with self.lock:
            if self.service is None:
                raise RuntimeError("Model/forecast source is not ready")
            if key not in self.frames:
                raise KeyError(key)
            if key not in self.cache:
                self.cache[key] = self.service.predict_initialization(self.frames[key])
                if len(self.cache) > self.settings.cache_max_initializations:
                    self.cache.popitem(last=False)
            self.cache.move_to_end(key)
            return self.cache[key]

    def health(self) -> dict:
        with self.lock:
            ready = self.service is not None
            return {
                "api_ready": True, "model_ready": ready, "forecast_ready": ready and bool(self.frames),
                "status": "ready" if ready and self.frames else "not_ready",
                "model_id": self.service.model_id if ready else None,
                "decision_threshold": self.service.threshold if ready else None,
                "features": self.service.bundle["features"] if ready else [],
                "available_initializations": sorted(self.frames), "cached_initializations": len(self.cache),
                "grid": self.grid,
            }
