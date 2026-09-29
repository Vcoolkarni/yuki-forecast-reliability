from __future__ import annotations

from pathlib import Path
import yaml


def load_config(path: str | Path) -> dict:
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle)
    required = ["geography", "time", "forecast", "reference", "paths", "labeling", "model"]
    missing = [key for key in required if key not in cfg]
    if missing:
        raise ValueError(f"Missing configuration sections: {missing}")
    bbox = cfg["geography"]
    if not (-90 <= bbox["south"] < bbox["north"] <= 90):
        raise ValueError("Invalid latitude bounds")
    if not (-180 <= bbox["west"] < bbox["east"] <= 180):
        raise ValueError("Invalid longitude bounds")
    if not cfg["forecast"]["lead_days"] or min(cfg["forecast"]["lead_days"]) < 1:
        raise ValueError("lead_days must contain positive integers")
    return cfg


def ensure_directories(cfg: dict) -> None:
    for key, value in cfg["paths"].items():
        if key.endswith("_dir"):
            Path(value).mkdir(parents=True, exist_ok=True)

