"""Metadata-only model registry. Never loads or overwrites the V1 artifact."""

from __future__ import annotations

from pathlib import Path

import yaml


def model_metadata(version: str = "v1", registry_path: str | Path = "config/model_registry.yaml") -> dict:
    registry = yaml.safe_load(Path(registry_path).read_text(encoding="utf-8"))
    if version not in registry["models"]:
        raise ValueError(f"Unknown model version {version!r}")
    record = {"model_id": version, **registry["models"][version]}
    if record["status"] == "ready" and not Path(record["artifact"]).is_file():
        raise FileNotFoundError(f"Registered {version} artifact is not present")
    return record


def resolve_ready_artifact(version: str = "v1", registry_path: str | Path = "config/model_registry.yaml") -> Path:
    record = model_metadata(version, registry_path)
    if record["status"] != "ready":
        raise ValueError(f"Model {version} is not trained/validated; select the existing V1 model")
    return Path(record["artifact"])
