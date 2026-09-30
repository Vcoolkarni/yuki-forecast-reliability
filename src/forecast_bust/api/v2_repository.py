"""Separate cached V2 forecast-only repository; V1 remains unchanged."""

from collections import OrderedDict
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import RLock
from time import monotonic

import pandas as pd

from ..v2.dataset import TARGETS
from ..v2.inference import V2Inference
from ..v2.geography import contains_grid_center, load_state_polygons, _geometry_bounds
from ..v2.current_store import CurrentObjectStore
from .repository import normalize_initialization


class V2Repository:
    def __init__(self, project_root: Path, source_path: Path | None = None,
                 boundary_path: Path | None = None, cache_size: int = 4):
        if cache_size < 1:
            raise ValueError("V2 forecast cache size must be positive")
        self.project_root = project_root
        configured = os.environ.get("FORECAST_BUST_V2_FORECAST_PATH")
        packaged_demo = project_root / "runtime/v2_historical_demo_forecasts.csv.gz"
        self.source_path = source_path or (Path(configured).resolve() if configured else
                                           packaged_demo if packaged_demo.is_file() else
                                           project_root / "data/interim/v2_historical_demo_forecasts.csv.gz")
        self.boundary_path = boundary_path or project_root / "frontend/public/data/india-states.geojson"
        self.cache_size = cache_size
        self.service = None
        self.frames = {}
        self.polygons = {}
        self.membership = {}
        self.current_runs = {}
        self.current_warning = None
        self.cache = OrderedDict()
        self.lock = RLock()
        self.current_root = Path(os.environ.get("FORECAST_BUST_CURRENT_ROOT",
                            project_root / "data/processed/v2/current")).resolve()
        self.object_store = None
        self.last_object_sync = 0.0
        self.source_kind = "historical_demo" if source_path is None and not configured else "forecast_only_feed"

    def initialize(self):
        with self.lock:
            if self.service is not None:
                return
            service = V2Inference(self.project_root / "models/v2/recommended_0p50",
                                  self.project_root / "config/inference.yaml")
            frame = pd.read_csv(self.source_path)
            if frame.empty or set(frame.columns) & TARGETS:
                raise ValueError("V2 source must be nonempty and forecast-only")
            dates = pd.to_datetime(frame.initialization_time, utc=True)
            frames = {day.isoformat().replace("+00:00", "Z"): frame.loc[dates.eq(day)].copy()
                      for day in sorted(dates.unique())}
            polygons = load_state_polygons(self.boundary_path)
            centers = frame[["latitude", "longitude"]].drop_duplicates()
            membership = {}
            for name, geometry in polygons.items():
                south, north, west, east = _geometry_bounds(geometry)
                candidates = centers.loc[centers.latitude.between(south, north) & centers.longitude.between(west, east)]
                membership[name] = {(float(row.latitude), float(row.longitude)) for row in candidates.itertuples()
                                    if contains_grid_center(geometry, float(row.latitude), float(row.longitude))}
            self._refresh_object_store(force=True)
            current_runs = self._scan_current_runs(service)
            self.frames, self.polygons, self.membership, self.service = frames, polygons, membership, service
            self.current_runs = current_runs

    def _refresh_object_store(self, force: bool = False) -> None:
        if not force and monotonic() - self.last_object_sync < 300:
            return
        self.last_object_sync = monotonic()
        try:
            if self.object_store is None:
                self.object_store = CurrentObjectStore.from_environment()
            if self.object_store is not None:
                self.object_store.sync_latest(self.current_root)
        except Exception as error:
            # Never expose credentials, endpoint URLs, or signed responses.
            self.current_warning = f"Processed-run object store sync failed ({type(error).__name__}); serving last verified run"

    def _scan_current_runs(self, service: V2Inference) -> dict:
        current_runs = {}
        frozen_digest = sha256((self.project_root / "models/v2/recommended_0p50/frozen_selection.json").read_bytes()).hexdigest()
        roots = [self.project_root / "runtime/current", self.current_root]
        manifests = [path for root in roots for path in sorted((root / "runs").glob("*/manifest.json"))]
        for manifest_path in manifests:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if (manifest.get("status") != "complete" or manifest.get("run_kind") != "current_forecast"
                        or manifest.get("run_id") != manifest_path.parent.name
                        or manifest.get("model_id") != service.model_id
                        or manifest.get("frozen_model_selection_sha256") != frozen_digest
                        or manifest.get("feature_names_ordered") != service.features
                        or manifest.get("records") != 38430):
                    raise ValueError("Current run manifest is incompatible with frozen V2")
                for name in ("features.csv.gz", "predictions.json.gz"):
                    artifact = manifest_path.parent / name
                    if (not artifact.is_file() or sha256(artifact.read_bytes()).hexdigest()
                            != manifest["artifacts"][name]["sha256"]):
                        raise ValueError("Current run artifact hash mismatch")
                key = normalize_initialization(manifest["initialization_utc"])
                current_runs[key] = {"manifest": manifest,
                                     "prediction_path": manifest_path.parent / "predictions.json.gz"}
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                self.current_warning = "One published current run failed integrity validation and was excluded"
        return current_runs

    def get(self, initialization: str) -> dict:
        key = normalize_initialization(initialization)
        with self.lock:
            if self.service is None:
                raise RuntimeError("V2 forecast/model is unavailable")
            if key not in self.current_runs and key not in self.frames:
                self._refresh_object_store(force=True)
                self.current_runs = self._scan_current_runs(self.service)
            if key not in self.frames and key not in self.current_runs:
                raise KeyError(key)
            if key not in self.cache:
                # Evict before constructing/loading another full-grid artifact so
                # one-entry caches do not briefly hold both runs in memory.
                while len(self.cache) >= self.cache_size:
                    self.cache.popitem(last=False)
                if key in self.current_runs:
                    source = self.current_runs[key]
                    with gzip.open(source["prediction_path"], "rt", encoding="utf-8") as handle:
                        artifact = json.load(handle)
                    if (len(artifact.get("records", [])) != 38430
                            or artifact.get("initialization_time") != key
                            or artifact.get("model_id") != self.service.model_id
                            or any(set(row) & TARGETS for row in artifact["records"])):
                        raise ValueError("Stored current predictions are incomplete or contain target fields")
                    self.cache[key] = artifact
                else:
                    self.cache[key] = self.service.predict_initialization(self.frames[key])
            self.cache.move_to_end(key)
            return self.cache[key]

    def health(self) -> dict:
        with self.lock:
            if self.service is not None:
                self._refresh_object_store()
                self.current_runs = self._scan_current_runs(self.service)
            ready = self.service is not None and bool(self.frames)
            first = next(iter(self.frames.values())) if self.frames else None
            grid = None
            if first is not None:
                latitudes = sorted(first.latitude.unique())
                longitudes = sorted(first.longitude.unique())
                grid = {"south": float(latitudes[0]), "north": float(latitudes[-1]),
                        "west": float(longitudes[0]), "east": float(longitudes[-1]),
                        "latitude_step_degrees": float(latitudes[1] - latitudes[0]),
                        "longitude_step_degrees": float(longitudes[1] - longitudes[0])}
            run_metadata = {key: {"run_kind": self.source_kind,
                                  "label": "Historical demo · September 2024" if self.source_kind == "historical_demo" else "Forecast-only feed",
                                  "initialization_utc": key, "model_id": self.service.model_id if self.service else None}
                            for key in self.frames}
            run_metadata.update({key: {"run_kind": "current_forecast",
                "label": "Current forecast · latest successfully processed" if key == max(self.current_runs) else "Earlier processed current forecast",
                "initialization_utc": key, "valid_start_utc": item["manifest"]["valid_start_utc"],
                "valid_end_utc": item["manifest"]["valid_end_utc"], "model_id": item["manifest"]["model_id"],
                "run_id": item["manifest"]["run_id"]} for key, item in self.current_runs.items()})
            primary = max(self.current_runs) if self.current_runs else (max(self.frames) if self.frames else None)
            return {"api_ready": True, "status": "ready" if ready else "not_ready", "model_ready": self.service is not None,
                    "forecast_ready": ready, "model_id": self.service.model_id if self.service else None,
                    "decision_threshold": self.service.threshold if self.service else None,
                    "available_initializations": sorted(set(self.frames) | set(self.current_runs)),
                    "source_kind": "mixed" if self.current_runs else self.source_kind,
                    "primary_initialization": primary, "run_metadata": run_metadata,
                    "current_warning": self.current_warning,
                    "features": self.service.features if self.service else [], "grid": grid,
                    "source_label": "Select a current forecast or historical 2024 demo" if self.current_runs else
                                    "Historical 2024 demo; not a live/current forecast" if self.source_kind == "historical_demo"
                                    else "Forecast-only feed; verify its initialization recency before treating it as live",
                    "state_count": len(self.polygons), "cached_initializations": len(self.cache)}

    def run_metadata(self, initialization: str) -> dict:
        key = normalize_initialization(initialization)
        if key in self.current_runs:
            return {"source_kind": "current_forecast", "manifest": self.current_runs[key]["manifest"]}
        if key in self.frames:
            return {"source_kind": self.source_kind}
        raise KeyError(key)

    def comparison_compatible(self, current: str, previous: str) -> bool:
        first, second = self.run_metadata(current), self.run_metadata(previous)
        if first["source_kind"] != second["source_kind"]:
            return False
        if first["source_kind"] == "current_forecast":
            a, b = first["manifest"], second["manifest"]
            return a["model_id"] == b["model_id"] and a["grid"] == b["grid"]
        return True
