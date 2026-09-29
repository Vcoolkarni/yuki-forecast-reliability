"""Package only immutable, deployment-safe inference inputs from local artifacts.

This does not train or evaluate a model. The V2 analog index uses only the
2021–23 training split and keeps its original floating-point values/order.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from forecast_bust.api.v2_analogs import COLUMNS, FEATURES


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
TRAIN = ROOT / "data/processed/v2/recommended_0p50/train"
GRID_CELLS = 3843


def digest(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def copy_immutable(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file() or digest(target) != digest(source):
        shutil.copy2(source, target)
    if digest(target) != digest(source):
        raise ValueError(f"Runtime copy failed checksum validation: {target.name}")


def build_analogs() -> None:
    paths = sorted(path for path in TRAIN.glob("*.csv.gz") if not path.name.endswith(".raw.csv.gz"))
    if len(paths) != 105 or any(not 2021 <= int(path.name[:4]) <= 2023 for path in paths):
        raise ValueError("Analog package requires exactly 105 labelled 2021–23 training initializations")
    names = (*FEATURES, "reference_precipitation", "absolute_error")
    dates: list[str] = []
    latitude: np.ndarray | None = None
    longitude: np.ndarray | None = None
    values = [np.empty((len(paths), GRID_CELLS, len(names)), dtype=np.float64) for _ in range(10)]
    busts = [np.empty((len(paths), GRID_CELLS), dtype=np.bool_) for _ in range(10)]
    for index, path in enumerate(paths):
        frame = pd.read_csv(path, usecols=list(COLUMNS))
        if (frame.empty or frame.initialization_time.nunique() != 1 or
                not frame.initialization_time.iloc[0].startswith(path.name[:10]) or
                not 2021 <= int(frame.initialization_time.iloc[0][:4]) <= 2023 or
                frame.is_bust.isna().any()):
            raise ValueError(f"Analog source is invalid or outside the 2021–23 training period: {path.name}")
        dates.append(pd.Timestamp(frame.initialization_time.iloc[0]).isoformat().replace("+00:00", "Z"))
        for lead in range(1, 11):
            day = frame.loc[frame.lead_day.eq(lead)].sort_values(["latitude", "longitude"])
            if len(day) != GRID_CELLS or day[["latitude", "longitude"]].duplicated().any():
                raise ValueError(f"Incomplete analog grid: {path.name}, Day {lead}")
            lat = day.latitude.to_numpy(dtype=np.float64)
            lon = day.longitude.to_numpy(dtype=np.float64)
            if latitude is None:
                latitude, longitude = lat, lon
            elif not np.array_equal(lat, latitude) or not np.array_equal(lon, longitude):
                raise ValueError(f"Analog grid mismatch: {path.name}, Day {lead}")
            values[lead - 1][index] = day[list(names)].to_numpy(dtype=np.float64)
            busts[lead - 1][index] = day.is_bust.to_numpy(dtype=np.bool_)
    if len(set(dates)) != 105:
        raise ValueError("Analog initialization dates are not unique")
    destination = RUNTIME / "analogs_v2"
    destination.mkdir(parents=True, exist_ok=True)
    for lead in range(1, 11):
        target = destination / f"day_{lead:02d}.npz"
        # Atomic replacement means a failed package build never leaves a valid-looking index.
        partial = target.with_name(target.name + ".part")
        with partial.open("wb") as handle:
            np.savez_compressed(handle, values=values[lead - 1], bust=busts[lead - 1],
                                latitude=latitude, longitude=longitude, dates=np.array(dates))
        partial.replace(target)
    metadata = {"source": "2021–23 labelled training partitions only", "initializations": len(dates),
                "grid_cells_per_lead": GRID_CELLS, "features": list(FEATURES),
                "value_columns": list(names), "source_sha256": {path.name: digest(path) for path in paths},
                "index_sha256": {f"day_{lead:02d}.npz": digest(destination / f"day_{lead:02d}.npz")
                                 for lead in range(1, 11)}}
    (destination / "manifest.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def main() -> None:
    copies = {
        ROOT / "data/interim/gfs_phase2_forecast.csv": RUNTIME / "v1/gfs_phase2_forecast.csv",
        ROOT / "data/processed/phase2_historical_fixed.csv": RUNTIME / "v1/phase2_historical_fixed.csv",
        ROOT / "data/interim/v2_historical_demo_forecasts.csv.gz": RUNTIME / "v2_historical_demo_forecasts.csv.gz",
    }
    current = ROOT / "data/processed/v2/current"
    latest = json.loads((current / "latest.json").read_text(encoding="utf-8"))
    identifier = latest["run_id"]
    if not identifier.isdigit() or len(identifier) != 10:
        raise ValueError("Current run pointer has an invalid run ID")
    manifest = json.loads((current / "runs" / identifier / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "complete" or manifest.get("run_id") != identifier:
        raise ValueError("Current run is not complete")
    for name in ("features.csv.gz", "predictions.json.gz"):
        source = current / "runs" / identifier / name
        if digest(source) != manifest["artifacts"][name]["sha256"]:
            raise ValueError(f"Current run checksum mismatch: {name}")
        copies[source] = RUNTIME / "current/runs" / identifier / name
    copies[current / "runs" / identifier / "manifest.json"] = RUNTIME / "current/runs" / identifier / "manifest.json"
    copies[current / "latest.json"] = RUNTIME / "current/latest.json"
    for source, target in copies.items():
        copy_immutable(source, target)
    build_analogs()
    files = [path for path in RUNTIME.rglob("*") if path.is_file()]
    print(f"RUNTIME_FILES={len(files)} RUNTIME_BYTES={sum(path.stat().st_size for path in files)}")


if __name__ == "__main__":
    main()
