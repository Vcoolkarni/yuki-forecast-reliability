"""Export one local forecast initialization as an API-ready JSON artifact."""
import argparse
import json
from pathlib import Path

import pandas as pd

from forecast_bust.inference import ForecastInference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast", default="data/interim/gfs_phase2_forecast.csv")
    parser.add_argument("--model", default="models/phase2_xgboost_calibrated.joblib")
    parser.add_argument("--config", default="config/inference.yaml")
    parser.add_argument("--initialization", required=True, help="UTC initialization date or ISO timestamp")
    parser.add_argument("--output", default="reports/phase2_inference.json")
    args = parser.parse_args()
    frame = pd.read_csv(args.forecast)
    selected = pd.Timestamp(args.initialization)
    selected = selected.tz_localize("UTC") if selected.tzinfo is None else selected.tz_convert("UTC")
    frame = frame.loc[pd.to_datetime(frame.initialization_time, utc=True).eq(selected)].copy()
    service = ForecastInference.from_artifact(args.model, args.config)
    artifact = service.predict_initialization(frame)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact, indent=2, allow_nan=False), encoding="utf-8")
    print(f"INFERENCE_JSON={target}; RECORDS={len(artifact['records'])}; LEAD_DAYS={len(artifact['lead_day_summaries'])}")


if __name__ == "__main__":
    main()
