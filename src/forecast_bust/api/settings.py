from dataclasses import dataclass
from pathlib import Path
import os

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class APISettings:
    model_path: Path
    forecast_path: Path
    inference_config_path: Path
    cache_max_initializations: int
    cors_origins: tuple[str, ...]
    historical_path: Path = PROJECT_ROOT / "data/processed/phase2_historical_fixed.csv"

    @classmethod
    def load(cls, path: str | Path | None = None):
        config_path = Path(path or os.environ.get("FORECAST_BUST_API_CONFIG", PROJECT_ROOT / "config/api.yaml")).resolve()
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        size = config["cache_max_initializations"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise ValueError("API cache size must be a positive integer")
        origins = config["cors_origins"]
        configured_origins = os.environ.get("FORECAST_BUST_CORS_ORIGINS")
        if configured_origins is not None:
            origins = [item.strip() for item in configured_origins.split(",") if item.strip()]
        if not isinstance(origins, list) or any(not isinstance(value, str) or not value.startswith(("http://", "https://")) for value in origins):
            raise ValueError("CORS origins must be an explicit list of HTTP(S) origins")
        if os.environ.get("RENDER") == "true" and not configured_origins:
            raise ValueError("FORECAST_BUST_CORS_ORIGINS is required in production")
        # Paths in API YAML are relative to the project root, independent of shell cwd.
        def artifact_path(key: str, packaged: str) -> Path:
            bundled = PROJECT_ROOT / packaged
            return bundled if bundled.is_file() else PROJECT_ROOT / config[key]
        return cls(artifact_path("model_path", "models/phase2_xgboost_calibrated.joblib"),
                   artifact_path("forecast_path", "runtime/v1/gfs_phase2_forecast.csv"),
                   PROJECT_ROOT / config["inference_config_path"], size, tuple(origins),
                   artifact_path("historical_path", "runtime/v1/phase2_historical_fixed.csv"))
