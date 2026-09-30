"""Package frozen V2 inference for the two forecast-only 2024 demo runs.

This does not retrain, evaluate, fetch weather data, or read 2025 outcomes.
"""

from __future__ import annotations

import gzip
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from forecast_bust.v2.inference import V2Inference


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime/v2_historical_demo_forecasts.csv.gz"
OUTPUT = ROOT / "runtime/v2_demo_predictions"
MODEL = ROOT / "models/v2/recommended_0p50"


def main() -> None:
    source_hash = sha256(SOURCE.read_bytes()).hexdigest()
    service = V2Inference(MODEL, ROOT / "config/inference.yaml")
    frozen = json.loads((MODEL / "frozen_selection.json").read_text(encoding="utf-8"))
    frame = pd.read_csv(SOURCE)
    dates = pd.to_datetime(frame.initialization_time, utc=True)
    runs = {}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for date in sorted(dates.unique()):
        key = date.isoformat().replace("+00:00", "Z")
        artifact = service.predict_initialization(frame.loc[dates.eq(date)].copy())
        if artifact["initialization_time"] != key or len(artifact["records"]) != 38430:
            raise ValueError("Frozen demo inference returned an incomplete initialization")
        filename = date.strftime("%Y%m%d%H") + ".json.gz"
        target = OUTPUT / filename
        partial = OUTPUT / (filename + ".part")
        payload = json.dumps(artifact, allow_nan=False, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8")
        with partial.open("wb") as handle:
            with gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as compressed:
                compressed.write(payload)
        digest = sha256(partial.read_bytes()).hexdigest()
        if target.exists() and sha256(target.read_bytes()).hexdigest() != digest:
            partial.unlink()
            raise ValueError("Existing historical demo artifact differs from frozen inference")
        partial.replace(target)
        runs[key] = {"file": filename, "sha256": digest, "records": len(artifact["records"])}
        print(f"DEMO_RUN={key} RECORDS={len(artifact['records'])} SHA256={digest}")
    manifest = {"artifact_kind": "historical_demo_forecast_predictions",
                "source_forecast_sha256": source_hash,
                "model_id": service.model_id,
                "classifier_sha256": frozen["classifier_sha256"],
                "regressor_sha256": frozen["regressor_sha256"],
                "calibrator_sha256": frozen["calibrator_sha256"],
                "runs": runs}
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"DEMO_MANIFEST={OUTPUT / 'manifest.json'}")


if __name__ == "__main__":
    main()
